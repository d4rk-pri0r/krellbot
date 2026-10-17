import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JobsDrawer, type JobRow } from "./JobsDrawer";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function stubJobsFetch(body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  });
}

function stubBrokenJsonFetch() {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () => Promise.reject(new SyntaxError("Unexpected end of JSON input")),
  });
}

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

function jobTexts(): string[] {
  return screen.getAllByTestId("job-row").map((row) => row.textContent ?? "");
}

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function resolveRows(gate: Deferred<JobRow[]>, rows: JobRow[]): Promise<void> {
  await act(async () => {
    gate.resolve(rows);
  });
}

async function rejectRequest(gate: Deferred<JobRow[]>, reason: unknown): Promise<void> {
  await act(async () => {
    gate.reject(reason);
  });
}

describe("JobsDrawer", () => {
  it("shows a job returned by the client", async () => {
    render(
      <JobsDrawer
        client={{
          list: vi.fn().mockResolvedValue([
            { id: "job-1", kind: "research.backtest", state: "succeeded" },
          ]),
        }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /jobs/i }));
    expect((await screen.findByTestId("job-row")).textContent).toContain("job-1 Research backtest (succeeded)");
    expect(screen.queryByText("No jobs")).toBeNull();
  });

  it("does not claim a snapshot while the jobs request is unsettled", async () => {
    let resolveList: (rows: JobRow[]) => void = () => {};
    const list = vi.fn().mockReturnValue(
      new Promise<JobRow[]>((resolve) => {
        resolveList = resolve;
      }),
    );
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    expect(list).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("jobs-loading").textContent).toMatch(/loading/i);
    expect(screen.queryByText("No jobs")).toBeNull();
    expect(screen.queryByTestId("job-row")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    resolveList([{ id: "job-1", kind: "research.backtest", state: "succeeded" }]);
    expect((await screen.findByTestId("job-row")).textContent).toContain(
      "job-1 Research backtest (succeeded)",
    );
    expect(screen.queryByTestId("jobs-loading")).toBeNull();
  });

  it("labels each job's kind in backend order", async () => {
    vi.stubGlobal(
      "fetch",
      stubJobsFetch({
        jobs: [
          { id: "job-7", kind: "research.mro.sweep", state: "queued" },
          { id: "job-2", kind: "housekeeping.compact", state: "hibernating" },
        ],
      }),
    );
    render(<JobsDrawer />);
    openJobsDrawer();
    const rows = await screen.findAllByTestId("job-row");
    expect(rows.map((row) => row.textContent)).toEqual([
      "job-7 Research mro sweep (queued)",
      "job-2 Housekeeping compact (hibernating)",
    ]);
  });

  it("keeps a valid empty jobs response empty", async () => {
    vi.stubGlobal("fetch", stubJobsFetch({ jobs: [] }));
    render(<JobsDrawer />);
    openJobsDrawer();
    expect(await screen.findByText("No jobs")).not.toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("reports malformed jobs envelopes as unavailable", async () => {
    const envelopes: unknown[] = [
      {},
      { jobs: "nope" },
      { jobs: null },
      ["not", "an", "envelope"],
      "nope",
      null,
    ];
    for (const envelope of envelopes) {
      cleanup();
      vi.stubGlobal("fetch", stubJobsFetch(envelope));
      render(<JobsDrawer />);
      openJobsDrawer();
      expect(await screen.findByRole("alert")).not.toBeNull();
      expect(screen.queryByText("No jobs")).toBeNull();
      expect(screen.queryByTestId("job-row")).toBeNull();
    }
    cleanup();
    vi.stubGlobal("fetch", stubBrokenJsonFetch());
    render(<JobsDrawer />);
    openJobsDrawer();
    expect(await screen.findByRole("alert")).not.toBeNull();
    expect(screen.queryByText("No jobs")).toBeNull();
  });

  it("rejects malformed job rows without returning a partial snapshot", async () => {
    const snapshots: unknown[] = [
      { jobs: [{ id: "job-1", kind: "research.backtest", state: "succeeded" }, null] },
      { jobs: [{ id: "", kind: "research.backtest", state: "succeeded" }] },
      { jobs: [{ id: "job-1", kind: "research.backtest", state: "   " }] },
      { jobs: [{ id: "job-1", kind: 7, state: "succeeded" }] },
      { jobs: [{ id: "job-1", state: "succeeded" }] },
      { jobs: ["not-a-row"] },
    ];
    for (const snapshot of snapshots) {
      cleanup();
      vi.stubGlobal("fetch", stubJobsFetch(snapshot));
      render(<JobsDrawer />);
      openJobsDrawer();
      expect(await screen.findByRole("alert")).not.toBeNull();
      expect(screen.queryByText("No jobs")).toBeNull();
      expect(screen.queryByTestId("job-row")).toBeNull();
    }
  });

  it("preserves valid backend row order and unknown states", async () => {
    vi.stubGlobal(
      "fetch",
      stubJobsFetch({
        jobs: [
          { id: "job-2", kind: "research.backtest", state: "hibernating" },
          { id: "job-1", kind: "research.backtest", state: "succeeded" },
        ],
      }),
    );
    render(<JobsDrawer />);
    openJobsDrawer();
    const rows = await screen.findAllByTestId("job-row");
    expect(rows.map((row) => row.textContent)).toEqual([
      "job-2 Research backtest (hibernating)",
      "job-1 Research backtest (succeeded)",
    ]);
  });

  it("preserves the jobs GET and CSRF request contract", async () => {
    const fetchMock = stubJobsFetch({ jobs: [] });
    vi.stubGlobal("fetch", fetchMock);
    render(<JobsDrawer />);
    openJobsDrawer();
    await screen.findByText("No jobs");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs", {
      method: "GET",
      credentials: "include",
      headers: { "X-Krellbot-CSRF": expect.any(String) },
    });
    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(Object.keys(headers)).toEqual(["X-Krellbot-CSRF"]);
    expect(headers["X-Krellbot-CSRF"]).toBe("");
  });

  it("refreshes with a fresh authenticated GET when asked and replaces the rows", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ jobs: [{ id: "job-1", kind: "research.backtest", state: "succeeded" }] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            jobs: [
              { id: "job-3", kind: "housekeeping.compact", state: "running" },
              { id: "job-1", kind: "research.backtest", state: "succeeded" },
            ],
          }),
      });
    vi.stubGlobal("fetch", fetchMock);
    render(<JobsDrawer />);
    openJobsDrawer();
    expect(await screen.findAllByTestId("job-row")).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    refreshJobs();
    expect(await screen.findAllByTestId("job-row")).toHaveLength(2);
    expect(jobTexts()).toEqual([
      "job-3 Housekeeping compact (running)",
      "job-1 Research backtest (succeeded)",
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/v1/jobs", {
      method: "GET",
      credentials: "include",
      headers: { "X-Krellbot-CSRF": expect.any(String) },
    });
    expect(screen.queryByText("No jobs")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("does not fetch while the drawer is closed and only fetches on user action", async () => {
    const fetchMock = stubJobsFetch({ jobs: [] });
    vi.stubGlobal("fetch", fetchMock);
    render(<JobsDrawer />);
    expect(screen.queryByRole("dialog")).toBeNull();
    await settle();
    expect(fetchMock).not.toHaveBeenCalled();
    openJobsDrawer();
    await screen.findByText("No jobs");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /close jobs drawer/i }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await settle();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 40));
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows a reopened drawer as a pending snapshot without stale rows", async () => {
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValueOnce([{ id: "job-1", kind: "research.backtest", state: "succeeded" }])
      .mockReturnValueOnce(deferred<JobRow[]>().promise);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    expect(await screen.findAllByTestId("job-row")).toHaveLength(1);
    expect(screen.queryByTestId("jobs-loading")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /close jobs drawer/i }));
    openJobsDrawer();
    expect(screen.queryByTestId("job-row")).toBeNull();
    expect(screen.getByTestId("jobs-loading").textContent).toMatch(/loading/i);
    expect(screen.queryByText("No jobs")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(list).toHaveBeenCalledTimes(2);
  });

  it("clears prior rows while a refresh is in flight", async () => {
    const gate = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValueOnce([{ id: "job-1", kind: "research.backtest", state: "succeeded" }])
      .mockReturnValueOnce(gate.promise);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    expect(await screen.findAllByTestId("job-row")).toHaveLength(1);
    refreshJobs();
    expect(screen.queryByTestId("job-row")).toBeNull();
    expect(screen.getByTestId("jobs-loading").textContent).toMatch(/loading/i);
    expect(screen.queryByText("No jobs")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    await resolveRows(gate, [{ id: "job-2", kind: "research.mro.sweep", state: "queued" }]);
    expect(jobTexts()).toEqual(["job-2 Research mro sweep (queued)"]);
    expect(screen.queryByTestId("jobs-loading")).toBeNull();
  });

  it("lets a newer request supersede an older success", async () => {
    const older = deferred<JobRow[]>();
    const newer = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    refreshJobs();
    expect(screen.getByTestId("jobs-loading").textContent).toMatch(/loading/i);
    await resolveRows(newer, [{ id: "job-new", kind: "research.mro.sweep", state: "queued" }]);
    expect(jobTexts()).toEqual(["job-new Research mro sweep (queued)"]);
    await resolveRows(older, [{ id: "job-old", kind: "research.backtest", state: "succeeded" }]);
    expect(jobTexts()).toEqual(["job-new Research mro sweep (queued)"]);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByTestId("jobs-loading")).toBeNull();
  });

  it("lets a newer request supersede an older failure", async () => {
    const older = deferred<JobRow[]>();
    const newer = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    refreshJobs();
    await resolveRows(newer, [{ id: "job-new", kind: "research.backtest", state: "succeeded" }]);
    expect(jobTexts()).toEqual(["job-new Research backtest (succeeded)"]);
    await rejectRequest(older, new Error("network reset"));
    expect(jobTexts()).toEqual(["job-new Research backtest (succeeded)"]);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByTestId("jobs-loading")).toBeNull();
    expect(screen.queryByText("No jobs")).toBeNull();
  });

  it("keeps a late older success from clobbering a newer failure", async () => {
    const older = deferred<JobRow[]>();
    const newer = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    refreshJobs();
    await rejectRequest(newer, new Error("session expired"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/unavailable/i);
    expect(screen.queryByText("No jobs")).toBeNull();
    expect(screen.queryByTestId("job-row")).toBeNull();
    expect(screen.queryByTestId("jobs-loading")).toBeNull();
    await resolveRows(older, [{ id: "job-old", kind: "research.backtest", state: "succeeded" }]);
    expect(screen.queryByTestId("job-row")).toBeNull();
    expect(screen.queryByRole("alert")).not.toBeNull();
    expect(screen.getByRole("alert").textContent).toMatch(/unavailable/i);
  });

  it("reports a failed refresh as unavailable and recovers with an explicit retry", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ jobs: [{ id: "job-1", kind: "research.backtest", state: "succeeded" }] }),
      })
      .mockResolvedValueOnce({ ok: false, status: 503 })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ jobs: [{ id: "job-2", kind: "research.mro.sweep", state: "queued" }] }),
      });
    vi.stubGlobal("fetch", fetchMock);
    render(<JobsDrawer />);
    openJobsDrawer();
    expect(await screen.findAllByTestId("job-row")).toHaveLength(1);
    refreshJobs();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/unavailable/i);
    expect(alert.textContent).toMatch(/503/);
    expect(screen.queryByText("No jobs")).toBeNull();
    expect(screen.queryByTestId("job-row")).toBeNull();
    expect(screen.queryByTestId("jobs-loading")).toBeNull();
    refreshJobs();
    expect(await screen.findAllByTestId("job-row")).toHaveLength(1);
    expect(jobTexts()).toEqual(["job-2 Research mro sweep (queued)"]);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("ignores the Jobs trigger while the drawer is already open", async () => {
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValue([{ id: "job-1", kind: "research.backtest", state: "succeeded" }]);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    expect(await screen.findAllByTestId("job-row")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Jobs" }));
    expect(jobTexts()).toEqual(["job-1 Research backtest (succeeded)"]);
    expect(screen.queryByTestId("jobs-loading")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(list).toHaveBeenCalledTimes(1);
  });

  it("never updates the next opening from a request started before closing", async () => {
    const stale = deferred<JobRow[]>();
    const fresh = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise);
    const view = render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    expect(screen.getByTestId("jobs-loading").textContent).toMatch(/loading/i);
    fireEvent.click(screen.getByRole("button", { name: /close jobs drawer/i }));
    await resolveRows(stale, [{ id: "job-stale", kind: "research.backtest", state: "succeeded" }]);
    openJobsDrawer();
    expect(screen.getByTestId("jobs-loading").textContent).toMatch(/loading/i);
    expect(screen.queryByTestId("job-row")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    await resolveRows(fresh, [{ id: "job-fresh", kind: "research.mro.sweep", state: "queued" }]);
    expect(jobTexts()).toEqual(["job-fresh Research mro sweep (queued)"]);
    view.unmount();
    await settle();
    expect(screen.queryByTestId("job-row")).toBeNull();
  });
});
