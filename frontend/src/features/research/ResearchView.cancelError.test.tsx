import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResearchView, type ResearchClient } from "./ResearchView";

afterEach(cleanup);

async function startJob(cancelJob: ResearchClient["cancelJob"]): Promise<void> {
  // Keep polling pending so cancellation races are controlled, not timer-dependent.
  const client: ResearchClient = {
    submitRun: vi.fn().mockResolvedValue({ id: "local-cancel-job", state: "running" }),
    cancelJob,
    getJob: () => new Promise(() => {}),
    getResult: vi.fn().mockResolvedValue(null),
    getResultDownload: vi.fn(),
  };
  render(<ResearchView client={client} />);
  for (const [label, value] of [
    [/dataset path/i, "LOCAL-CANCEL-FIXTURE.csv"],
    [/fee basis points/i, "40"],
    [/^from$/i, "0"],
    [/^to$/i, "1000"],
  ] as const) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  fireEvent.click(screen.getByRole("button", { name: /^Run$/ }));
  await screen.findByTestId("research-job-id");
}

describe("Research Cancel outcome honesty", () => {
  it.each([
    new TypeError("Failed to fetch"),
    new Error("request failed: 403"),
    new Error("request failed: 503"),
    "unexpected cancellation exception",
  ])("shows the actual failure and permits retry for %s", async (error) => {
    let finishRetry: (() => void) | undefined;
    const cancelJob = vi.fn<ResearchClient["cancelJob"]>()
      .mockImplementationOnce(() => {
        if (typeof error === "string") throw error;
        return Promise.reject(error);
      })
      .mockImplementationOnce(() => new Promise<void>((resolve) => { finishRetry = resolve; }));
    await startJob(cancelJob);
    const runbar = within(screen.getByTestId("research-runbar"));
    fireEvent.click(runbar.getByRole("button", { name: /^Cancel$/ }));
    const alert = await screen.findByTestId("research-cancel-error");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toBe(
      `Cancel job failed: ${error instanceof Error ? error.message : error} — outcome unknown: the command may not have been sent or applied — check state before retrying`,
    );
    expect(runbar.getByTestId("research-cancel-error")).toBe(alert);
    expect(runbar.getByTestId("research-job-id").textContent).toContain("local-cancel-job");
    expect(runbar.getByTestId("research-job-status").textContent).toContain("Waiting");
    expect(screen.queryByTestId("research-job-error")).toBeNull();
    expect(runbar.getByTestId("research-cancel")).toBe(runbar.getByRole("button", { name: /^Cancel$/ }));

    fireEvent.click(runbar.getByRole("button", { name: /^Cancel$/ }));
    await waitFor(() => expect(cancelJob).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("research-cancel-error")).toBeNull();
    expect(runbar.getByTestId("research-job-id").textContent).toContain("local-cancel-job");
    expect(cancelJob.mock.calls).toEqual([["local-cancel-job"], ["local-cancel-job"]]);
    await act(async () => { finishRetry?.(); });
    await waitFor(() => expect(screen.queryByTestId("research-job-id")).toBeNull());
    expect(screen.queryByRole("button", { name: /^Cancel$/ })).toBeNull();
    expect(screen.queryByTestId("research-cancel-error")).toBeNull();
  });

  it("clears the job id and Cancel control on first-attempt success", async () => {
    const cancelJob = vi.fn().mockResolvedValue(undefined);
    await startJob(cancelJob);
    fireEvent.click(screen.getByRole("button", { name: /^Cancel$/ }));
    await waitFor(() => expect(screen.queryByTestId("research-job-id")).toBeNull());
    expect(cancelJob).toHaveBeenCalledWith("local-cancel-job");
    expect(screen.queryByTestId("research-cancel-error")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Cancel$/ })).toBeNull();
  });
});
