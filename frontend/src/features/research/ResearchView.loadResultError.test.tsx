import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResearchView, type ResearchClient, type StoredResult } from "./ResearchView";

afterEach(cleanup);

const result: StoredResult = {
  legacy_receipt: { equity: 123, fee_bps: 40, trades: [] },
  trace: [{ bar_ts: 1000, input: { close: 12 }, conditions: [] }],
};

async function startJob(getResult: ResearchClient["getResult"]): Promise<ResearchClient> {
  const client: ResearchClient = {
    submitRun: vi.fn().mockResolvedValue({ id: "local-load-job", state: "running" }),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    // Isolate manual loads from the unchanged auto-poll path without timer races.
    getJob: () => new Promise(() => {}),
    getResult,
    getResultDownload: vi.fn(),
  };
  render(<ResearchView client={client} />);
  for (const [label, value] of [
    [/dataset path/i, "LOCAL-LOAD-FIXTURE.csv"],
    [/fee basis points/i, "40"],
    [/^from$/i, "0"],
    [/^to$/i, "1000"],
  ] as const) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  fireEvent.click(screen.getByRole("button", { name: /^Run$/ }));
  await screen.findByTestId("research-job-id");
  return client;
}

describe("Research manual Load result honesty", () => {
  it.each([
    new TypeError("Failed to fetch"),
    new Error("request failed: 403"),
    new Error("request failed: 503"),
    "unexpected load exception",
  ])("names the actual failure, preserves cancellation and permits retry for %s", async (error) => {
    let finishRetry: ((value: StoredResult) => void) | undefined;
    const getResult = vi.fn<ResearchClient["getResult"]>()
      .mockImplementationOnce(() => {
        if (typeof error === "string") throw error;
        return Promise.reject(error);
      })
      .mockImplementationOnce(() => new Promise((resolve) => { finishRetry = resolve; }));
    await startJob(getResult);
    const runbar = within(screen.getByTestId("research-runbar"));
    fireEvent.click(runbar.getByRole("button", { name: /^Load result$/ }));
    const alert = await screen.findByTestId("research-load-result-error");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toBe(
      `Load result failed: ${error instanceof Error ? error.message : error} — outcome unknown: the command may not have been sent or applied — check state before retrying`,
    );
    expect(runbar.getByTestId("research-load-result-error")).toBe(alert);
    expect(runbar.getByTestId("research-job-id").textContent).toContain("local-load-job");
    expect(runbar.getByTestId("research-job-status").textContent).toContain("Waiting");
    expect((runbar.getByTestId("research-cancel") as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByTestId("research-result")).toBeNull();
    expect(screen.queryByTestId("research-job-error")).toBeNull();

    fireEvent.click(runbar.getByRole("button", { name: /^Load result$/ }));
    await waitFor(() => expect(getResult).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("research-load-result-error")).toBeNull();
    expect(runbar.getByTestId("research-job-id").textContent).toContain("local-load-job");
    expect(getResult.mock.calls).toEqual([["local-load-job"], ["local-load-job"]]);
    await act(async () => { finishRetry?.(result); });
    expect((await screen.findByTestId("research-result")).textContent).toContain("123");
    expect(screen.queryByTestId("research-load-result-error")).toBeNull();
  });

  it("keeps the same job cancellable after a failed load", async () => {
    const client = await startJob(vi.fn().mockRejectedValue(new Error("connection lost")));
    fireEvent.click(screen.getByRole("button", { name: /^Load result$/ }));
    await screen.findByTestId("research-load-result-error");
    fireEvent.click(screen.getByTestId("research-cancel"));
    await waitFor(() => expect(client.cancelJob).toHaveBeenCalledWith("local-load-job"));
    await waitFor(() => expect(screen.queryByTestId("research-job-id")).toBeNull());
  });

  it("stores a successful load and resets the selected bar on reload", async () => {
    const getResult = vi.fn().mockResolvedValue(result);
    await startJob(getResult);
    fireEvent.click(screen.getByRole("button", { name: /^Load result$/ }));
    await screen.findByTestId("research-result");
    fireEvent.click(screen.getByTestId("research-trace-scroll").querySelector("button")!);
    await screen.findByTestId("research-bar-detail");
    fireEvent.click(screen.getByRole("button", { name: /^Load result$/ }));
    await waitFor(() => expect(screen.queryByTestId("research-bar-detail")).toBeNull());
    expect(screen.getByTestId("research-result").textContent).toContain("123");
    expect(screen.queryByTestId("research-load-result-error")).toBeNull();
  });
});
