import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ResearchView, type ResearchClient } from "./ResearchView";

afterEach(cleanup);

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

// A controlled client boundary keeps the real mounted handler pending without
// network timing or an engine dependency; all React behavior runs unchanged.
function setup() {
  const submission = deferred<Awaited<ReturnType<ResearchClient["submitRun"]>>>();
  const requests: Parameters<ResearchClient["submitRun"]>[0][] = [];
  const client: ResearchClient = {
    submitRun(request) {
      requests.push(request);
      return submission.promise;
    },
    async cancelJob() {},
    async getJob(id) { return { id, state: "succeeded" }; },
    async getResult() { return null; },
    async getResultDownload() { return new Response("{}"); },
  };
  render(<ResearchView client={client} />);
  for (const [label, value] of [
    [/dataset path/i, "fixtures/synthetic.csv"],
    [/fee basis points/i, "40"],
    [/^from$/i, "0"],
    [/^to$/i, "1000"],
  ] as const) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  const run = screen.getByRole<HTMLButtonElement>("button", { name: "Run" });
  return { submission, requests, run };
}

function expectIdle(run: HTMLButtonElement, status: HTMLElement, text: string) {
  expect(run.textContent).toBe("Run");
  expect(run.getAttribute("aria-busy")).toBe("false");
  expect(run.disabled).toBe(false);
  expect(status.textContent).toBe(text);
}

function expectBusy(run: HTMLButtonElement, status: HTMLElement) {
  expect(run.getAttribute("aria-busy")).toBe("true");
  expect(run.textContent).toBe("Running\u2026");
  expect(run.disabled).toBe(true);
  expect(status.textContent).toBe("Running\u2026");
  expect(screen.getByTestId("research-state-submitting").textContent)
    .toContain("Submitting research run…");
}

describe("Research Run busy affordance", () => {
  it("exposes a distinct primary selector and keyboard/live semantics", () => {
    const { run } = setup();
    expect(screen.getByTestId("research-run")).toBe(run);
    expect(within(screen.getByTestId("research-runbar")).getByTestId("research-run")).toBe(run);
    expect(run.getAttribute("aria-keyshortcuts")).toBe("Enter Space");
    const status = screen.getByTestId("research-run-busy-status");
    expect(status.tagName).toBe("P");
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(run.nextElementSibling).toBe(status);
    expectIdle(run, status, "");
    expect(screen.queryByTestId("research-submit-retry")).toBeNull();
  });

  it("guards same-tick activation before React commits disabled, then settles", async () => {
    const { run, requests, submission } = setup();
    run.focus();
    expect(document.activeElement).toBe(run);
    act(() => {
      run.click();
      // Native clicks share this batch, so disabled has not committed yet.
      expect(run.disabled).toBe(false);
      run.click();
      expect(requests).toHaveLength(1);
    });
    const status = screen.getByTestId("research-run-busy-status");
    expectBusy(run, status);
    fireEvent.click(run);
    expect(requests).toEqual([{
      datasetPath: "fixtures/synthetic.csv", feeBps: 40,
      fromMs: 0, toMs: 1000, packPath: "",
    }]);
    await act(async () => {
      submission.resolve({ id: "synthetic-run", state: "queued" });
      await submission.promise;
    });
    expectIdle(run, status, "Run submitted");
    expect(screen.getByTestId("research-job-id").textContent).toContain("synthetic-run");
    expect(screen.queryByTestId("research-state-submitting")).toBeNull();
    expect(screen.queryByTestId("research-state-error")).toBeNull();
  });

  it("preserves canonical failure and Retry surfaces and releases the guard", async () => {
    const { run, requests, submission } = setup();
    fireEvent.click(run);
    const status = screen.getByTestId("research-run-busy-status");
    expectBusy(run, status);
    await act(async () => { submission.reject(new Error("synthetic submit failure")); });
    expectIdle(run, status, "Run submitted");
    const failure = screen.getByTestId("research-state-error");
    expect(failure.textContent).toContain("Could not submit research run — check the workstation is running.");
    expect(screen.getByTestId("research-state-error-detail").textContent).toBe("synthetic submit failure");
    expect(screen.getByRole("alert").textContent).toBe("synthetic submit failure");
    const retry = within(failure).getByTestId("research-submit-retry");
    expect(retry.textContent).toBe("Retry");
    await act(async () => { fireEvent.click(retry); });
    expect(requests).toHaveLength(2);
    expectIdle(run, status, "Run submitted");
    expect(screen.getByTestId("research-state-error")).toBeDefined();
  });

  it("does not announce a submission or retain the guard after invalid input", async () => {
    const { run, requests, submission } = setup();
    fireEvent.change(screen.getByLabelText(/fee basis points/i), { target: { value: "" } });
    fireEvent.click(run);
    expect(requests).toHaveLength(0);
    expectIdle(run, screen.getByTestId("research-run-busy-status"), "");
    expect(screen.getByRole("alert").textContent).toBe("Fee basis points must be a nonnegative integer");
    expect(screen.queryByTestId("research-state-error")).toBeNull();
    fireEvent.change(screen.getByLabelText(/fee basis points/i), { target: { value: "40" } });
    fireEvent.click(run);
    expect(requests).toHaveLength(1);
    await act(async () => { submission.resolve({ id: "corrected-run", state: "queued" }); });
    expectIdle(run, screen.getByTestId("research-run-busy-status"), "Run submitted");
  });
});
