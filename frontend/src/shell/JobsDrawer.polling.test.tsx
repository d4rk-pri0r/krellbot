import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JobsDrawer, type JobRow } from "./JobsDrawer";

/**
 * Regression coverage for #98: an OPEN Jobs drawer must follow a running
 * Research job to its terminal state on its own — no close/reopen, no
 * manual Refresh, no page reload — while staying honest about failures.
 */

const REFRESH_MS = 2000;

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => {};
  let reject: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function openJobsDrawer(): void {
  fireEvent.click(screen.getByRole("button", { name: /jobs/i }));
}

function refreshJobs(): void {
  fireEvent.click(screen.getByRole("button", { name: /refresh jobs/i }));
}

function closeJobsDrawer(): void {
  fireEvent.click(screen.getByRole("button", { name: /close jobs drawer/i }));
}

function jobTexts(): string[] {
  return screen.getAllByTestId("job-row").map((row) => row.textContent ?? "");
}

function runningThen(): {
  list: () => Promise<JobRow[]>;
  gate: Deferred<JobRow[]>;
} {
  const gate = deferred<JobRow[]>();
  const list = vi
    .fn<() => Promise<JobRow[]>>()
    .mockResolvedValueOnce([
      { id: "job-1", kind: "research.backtest", state: "running" },
    ])
    .mockReturnValueOnce(gate.promise);
  return { list, gate };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** Flush pending promise resolutions without moving the clock (findBy* would hang under faked intervals). */
async function flush(): Promise<void> {
  await advance(0);
}

function rows(): HTMLElement[] {
  return screen.getAllByTestId("job-row");
}

describe("JobsDrawer periodic refresh (#98)", () => {
  it("shows the terminal state on its own after a background refresh (succeeded)", async () => {
    const { list, gate } = runningThen();
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    await flush();
    expect(rows()).toHaveLength(1);
    expect(jobTexts()).toEqual(["job-1 Research backtest (running)"]);

    // Background refresh observes completion; no click drives it.
    gate.resolve([{ id: "job-1", kind: "research.backtest", state: "succeeded" }]);
    await advance(REFRESH_MS);

    expect(jobTexts()).toEqual(["job-1 Research backtest (succeeded)"]);
    expect(screen.queryByTestId("jobs-loading")).toBeNull();
    expect(screen.queryByTestId("jobs-error")).toBeNull();
    expect(screen.queryByTestId("jobs-empty")).toBeNull();
  });

  it("shows the failed terminal state via a background refresh", async () => {
    const gate = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValueOnce([{ id: "job-1", kind: "research.backtest", state: "queued" }])
      .mockReturnValueOnce(gate.promise);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    await flush();
    expect(rows()).toHaveLength(1);

    gate.resolve([{ id: "job-1", kind: "research.backtest", state: "failed" }]);
    await advance(REFRESH_MS);

    expect(jobTexts()).toEqual(["job-1 Research backtest (failed)"]);
    expect(screen.queryByTestId("jobs-error")).toBeNull();
  });

  it("shows the cancelled terminal state via a background refresh", async () => {
    const gate = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValueOnce([{ id: "job-1", kind: "research.backtest", state: "running" }])
      .mockReturnValueOnce(gate.promise);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    await flush();
    expect(rows()).toHaveLength(1);

    gate.resolve([{ id: "job-1", kind: "research.backtest", state: "cancelled" }]);
    await advance(REFRESH_MS);

    expect(jobTexts()).toEqual(["job-1 Research backtest (cancelled)"]);
    expect(screen.queryByTestId("jobs-error")).toBeNull();
  });

  it("does not poll while the drawer is closed", async () => {
    const gate = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValueOnce([{ id: "job-1", kind: "research.backtest", state: "succeeded" }])
      .mockReturnValueOnce(gate.promise);
    const view = render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    await flush();
    expect(rows()).toHaveLength(1);
    closeJobsDrawer();
    expect(screen.queryByTestId("kbot-jobs-dialog")).toBeNull();

    await advance(REFRESH_MS * 3);

    expect(list).toHaveBeenCalledTimes(1);
    view.unmount();
  });

  it("stops polling on unmount", async () => {
    const gate = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValueOnce([{ id: "job-1", kind: "research.backtest", state: "succeeded" }])
      .mockReturnValueOnce(gate.promise);
    const view = render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    await flush();
    expect(rows()).toHaveLength(1);
    view.unmount();

    await advance(REFRESH_MS * 3);

    expect(list).toHaveBeenCalledTimes(1);
  });

  it("keeps an in-flight background read from repopulating state after close and reopen", async () => {
    const stale = deferred<JobRow[]>();
    const fresh = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValueOnce([{ id: "job-1", kind: "research.backtest", state: "running" }])
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    await flush();
    expect(rows()).toHaveLength(1);

    // A periodic read starts and hangs.
    await advance(REFRESH_MS);
    expect(list).toHaveBeenCalledTimes(2);

    closeJobsDrawer();
    stale.resolve([{ id: "job-stale", kind: "research.backtest", state: "succeeded" }]);
    await flush();
    expect(screen.queryByTestId("kbot-jobs-dialog")).toBeNull();

    openJobsDrawer();
    expect(screen.getByTestId("jobs-loading").textContent).toMatch(/loading/i);
    expect(screen.queryByTestId("job-row")).toBeNull();

    fresh.resolve([{ id: "job-fresh", kind: "research.mro.sweep", state: "succeeded" }]);
    await flush();
    expect(jobTexts()).toEqual(["job-fresh Research mro sweep (succeeded)"]);
  });

  it("keeps an in-flight background read from repopulating an unmounted drawer", async () => {
    const stale = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValueOnce([{ id: "job-1", kind: "research.backtest", state: "running" }])
      .mockReturnValueOnce(stale.promise);
    const view = render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    await flush();
    expect(rows()).toHaveLength(1);

    await advance(REFRESH_MS);
    expect(list).toHaveBeenCalledTimes(2);
    view.unmount();

    stale.resolve([{ id: "job-stale", kind: "research.backtest", state: "succeeded" }]);
    await flush();
    expect(screen.queryByTestId("job-row")).toBeNull();
  });

  it("keeps an in-flight background read from repopulating state after a client switch", async () => {
    const stale = deferred<JobRow[]>();
    const listA = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValueOnce([{ id: "job-1", kind: "research.backtest", state: "running" }])
      .mockReturnValueOnce(stale.promise);
    const listB = vi.fn<() => Promise<JobRow[]>>().mockResolvedValue([]);
    const view = render(<JobsDrawer client={{ list: listA }} />);
    openJobsDrawer();
    await flush();
    expect(rows()).toHaveLength(1);

    await advance(REFRESH_MS);
    expect(listA).toHaveBeenCalledTimes(2);

    view.rerender(<JobsDrawer client={{ list: listB }} />);
    // The new client's reads are the only ones that may apply.
    await flush();
    expect(screen.getByTestId("jobs-empty")).not.toBeNull();

    stale.resolve([{ id: "job-stale", kind: "research.backtest", state: "succeeded" }]);
    await flush();
    expect(screen.queryByTestId("job-row")).toBeNull();
    expect(screen.getByTestId("jobs-empty")).not.toBeNull();
  });

  it("never overlaps background reads: one read at a time per interval", async () => {
    const gate = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValueOnce([{ id: "job-1", kind: "research.backtest", state: "running" }])
      .mockReturnValueOnce(gate.promise)
      .mockResolvedValue([{ id: "job-1", kind: "research.backtest", state: "succeeded" }]);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    await flush();
    expect(rows()).toHaveLength(1);

    // The first background read hangs; later ticks must not start another.
    await advance(REFRESH_MS * 5);

    expect(list).toHaveBeenCalledTimes(2);

    gate.resolve([{ id: "job-1", kind: "research.backtest", state: "succeeded" }]);
    await flush();
    expect(jobTexts()).toEqual(["job-1 Research backtest (succeeded)"]);
    // Once free, the next tick may read again.
    await advance(REFRESH_MS);
    expect(list).toHaveBeenCalledTimes(3);
  });

  it("keeps the visible row mounted while a background refresh is pending", async () => {
    const gate = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValueOnce([{ id: "job-1", kind: "research.backtest", state: "running" }])
      .mockReturnValueOnce(gate.promise);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    await flush();
    expect(rows()).toHaveLength(1);

    await advance(REFRESH_MS);
    expect(list).toHaveBeenCalledTimes(2);
    // A pending periodic read must not blank the rows to a loading flash.
    expect(jobTexts()).toEqual(["job-1 Research backtest (running)"]);
    expect(screen.queryByTestId("jobs-loading")).toBeNull();
    expect(screen.queryByTestId("jobs-empty")).toBeNull();
    expect(screen.queryByTestId("jobs-error")).toBeNull();

    gate.resolve([{ id: "job-1", kind: "research.backtest", state: "succeeded" }]);
    await flush();
    expect(jobTexts()).toEqual(["job-1 Research backtest (succeeded)"]);
  });

  it("reports a failed background refresh through the existing error UI and recovers", async () => {
    const gate = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValueOnce([{ id: "job-1", kind: "research.backtest", state: "running" }])
      .mockReturnValueOnce(gate.promise)
      .mockResolvedValueOnce([{ id: "job-1", kind: "research.backtest", state: "succeeded" }]);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    await flush();
    expect(rows()).toHaveLength(1);

    await advance(REFRESH_MS);
    gate.reject(new Error("jobs failed: 503"));
    await flush();

    const alert = screen.getByTestId("jobs-error");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toContain("Could not load jobs — check the workstation is running.");
    expect(alert.textContent).toMatch(/503/);
    expect(screen.queryByTestId("job-row")).toBeNull();
    expect(screen.queryByTestId("jobs-loading")).toBeNull();
    expect(screen.queryByTestId("jobs-empty")).toBeNull();

    // The inline Retry affordance re-invokes the same load path.
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await flush();
    expect(rows()).toHaveLength(1);
    expect(jobTexts()).toEqual(["job-1 Research backtest (succeeded)"]);
    expect(screen.queryByTestId("jobs-error")).toBeNull();
  });

  it("reports a blocked 403 background refresh as the local-only blocked state", async () => {
    const gate = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValueOnce([{ id: "job-1", kind: "research.backtest", state: "running" }])
      .mockReturnValueOnce(gate.promise);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    await flush();
    expect(rows()).toHaveLength(1);

    await advance(REFRESH_MS);
    gate.reject(new Error("jobs failed: 403"));
    await flush();

    const alert = screen.getByTestId("jobs-error");
    expect(alert.textContent).toContain("Jobs blocked — local-only preview.");
    expect(screen.queryByTestId("job-row")).toBeNull();
    expect(screen.queryByTestId("jobs-loading")).toBeNull();
  });

  it("keeps a manual Refresh working alongside the periodic read", async () => {
    const gate = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValueOnce([{ id: "job-1", kind: "research.backtest", state: "running" }])
      .mockReturnValueOnce(gate.promise);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    await flush();
    expect(rows()).toHaveLength(1);

    // A manual refresh supersedes the pending periodic read...
    refreshJobs();
    expect(list).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("jobs-loading").textContent).toMatch(/loading/i);
    // ...and the periodic read does not restart while the manual one hangs.
    await advance(REFRESH_MS * 3);
    expect(list).toHaveBeenCalledTimes(2);

    gate.resolve([{ id: "job-1", kind: "research.backtest", state: "succeeded" }]);
    await flush();
    expect(jobTexts()).toEqual(["job-1 Research backtest (succeeded)"]);
  });

  it("does not restart the poll cycle on a client switch", async () => {
    const listA = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValue([{ id: "job-a", kind: "research.backtest", state: "succeeded" }]);
    const listB = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValue([{ id: "job-b", kind: "research.mro.sweep", state: "queued" }]);
    const view = render(<JobsDrawer client={{ list: listA }} />);
    openJobsDrawer();
    await flush();
    expect(rows()).toHaveLength(1);
    expect(listA).toHaveBeenCalledTimes(1);

    // Switching clients re-reads once through the new client, and must not
    // reset the interval schedule: the next periodic tick stays on the
    // original 2s cadence from open.
    view.rerender(<JobsDrawer client={{ list: listB }} />);
    await flush();
    expect(listB).toHaveBeenCalledTimes(1);
    expect(jobTexts()).toEqual(["job-b Research mro sweep (queued)"]);

    await advance(REFRESH_MS - 1);
    expect(listB).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(listB).toHaveBeenCalledTimes(2);
    expect(jobTexts()).toEqual(["job-b Research mro sweep (queued)"]);
  });
});
