import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResearchView, type ResearchClient, type StoredResult } from "./ResearchView";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const stored: StoredResult = { legacy_receipt: { fee_bps: 40 }, trace: [] };

async function mount(getResultDownload: ResearchClient["getResultDownload"]) {
  // The client boundary is deferred to observe the real component's pending state.
  const client: ResearchClient = {
    submitRun: vi.fn().mockResolvedValue({ id: "export-job", state: "running" }),
    getJob: vi.fn().mockResolvedValue({ id: "export-job", state: "succeeded" }),
    getResult: vi.fn().mockResolvedValue(stored),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    getResultDownload,
  };
  render(<ResearchView client={client} />);
  expect(screen.queryByRole("button", { name: "Export result" })).toBeNull();
  for (const [label, value] of [
    [/dataset path/i, "LOCAL-EXPORT-FIXTURE.csv"],
    [/fee basis points/i, "40"],
    [/^from$/i, "0"],
    [/^to$/i, "1000"],
  ] as const) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  fireEvent.click(screen.getByRole("button", { name: "Run" }));
  return await screen.findByRole<HTMLButtonElement>("button", { name: "Export result" });
}

function expectBusy(button: HTMLButtonElement) {
  expect(button.getAttribute("aria-busy")).toBe("true");
  expect(button.textContent).toBe("Exporting result\u2026");
  expect(button.disabled).toBe(true);
  expect(screen.getByTestId("research-export-result-busy-status").textContent).toBe("Exporting result\u2026");
}

function expectSettled(button: HTMLButtonElement, status = "Export complete") {
  expect(button.getAttribute("aria-busy")).toBe("false");
  expect(button.textContent).toBe("Export result");
  expect(button.disabled).toBe(false);
  expect(screen.getByTestId("research-export-result-busy-status").textContent).toBe(status);
}

describe("Research Export result busy affordance", () => {
  it("adds distinct button and polite sibling testids outside the unchanged runbar", async () => {
    const button = await mount(vi.fn(() => new Promise<Response>(() => {})));
    expect(button.getAttribute("data-testid")).toBe("research-export-result");
    expect(button.getAttribute("aria-keyshortcuts")).toBe("Enter Space");
    const status = screen.getByTestId("research-export-result-busy-status");
    expect(status.tagName).toBe("P");
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.parentElement).toBe(button.parentElement);
    expect(screen.getByTestId("research-runbar").contains(status)).toBe(false);
    expect(screen.getByTestId("research-runbar").contains(button)).toBe(false);
    expect(status.textContent).toBe("");
    const raw = screen.getByTestId("research-export");
    expect(raw.tagName).toBe("PRE");
    expect(raw.textContent).toBe(JSON.stringify(stored));
    expect(screen.getByTestId("research-receipt-detail").contains(raw)).toBe(true);
  });

  it("keeps the focused button busy through request and blob, blocks repeats, then downloads", async () => {
    const request = deferred<Response>();
    const body = deferred<Blob>();
    const download = vi.fn(() => request.promise);
    const button = await mount(download);
    // jsdom cannot create blob URLs or perform browser downloads.
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:export-result");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    button.focus();
    fireEvent.click(button);
    expect(document.activeElement).toBe(button);
    expectBusy(button);
    fireEvent.click(button);
    expect(download).toHaveBeenCalledTimes(1);
    expect(download).toHaveBeenCalledWith("export-job");
    await act(async () => { request.resolve({ blob: () => body.promise } as Response); });
    expectBusy(button);
    expect(create).not.toHaveBeenCalled();
    const blob = new Blob(['{"synthetic":true}'], { type: "application/json" });
    await act(async () => { body.resolve(blob); });
    expectSettled(button);
    expect(document.activeElement).toBe(button);
    expect(create).toHaveBeenCalledWith(blob);
    expect(click).toHaveBeenCalledTimes(1);
    const anchor = click.mock.instances[0] as HTMLAnchorElement;
    expect(anchor.download).toBe("research-receipt-export-job.json");
    expect(anchor.href).toBe("blob:export-result");
    expect(document.body.contains(anchor)).toBe(false);
    expect(revoke).toHaveBeenCalledWith("blob:export-result");
  });

  it("guards synchronous activations before React commits disabled", async () => {
    const request = deferred<Response>();
    const download = vi.fn(() => request.promise);
    const button = await mount(download);
    act(() => {
      button.click();
      button.click();
    });
    expect(download).toHaveBeenCalledTimes(1);
    expectBusy(button);
    await act(async () => { request.reject(new Error("download refused")); });
    expectSettled(button, "Export failed");
  });

  it.each([new Error("request failed: 403"), "non-Error failure"])(
    "preserves the canonical raw failure alert and clears it on retry: %s", async (error) => {
      const request = deferred<Response>();
      const retry = deferred<Response>();
      const download = vi.fn<ResearchClient["getResultDownload"]>()
        .mockImplementationOnce(() => request.promise)
        .mockImplementationOnce(() => retry.promise);
      const button = await mount(download);
      fireEvent.click(button);
      expectBusy(button);
      await act(async () => { request.reject(error); });
      const message = error instanceof Error ? error.message : "export failed";
      const alert = screen.getByTestId("research-export-error");
      expect(alert.getAttribute("role")).toBe("alert");
      expect(alert.textContent).toBe(message);
      expectSettled(button, "Export failed");
      fireEvent.click(button);
      expectBusy(button);
      expect(screen.queryByTestId("research-export-error")).toBeNull();
      expect(download).toHaveBeenCalledTimes(2);
      await act(async () => { retry.reject(error); });
      expectSettled(button, "Export failed");
    },
  );
});
