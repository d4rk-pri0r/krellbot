import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JobsDrawer } from "./JobsDrawer";

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

function openJobsDrawer(): void {
  fireEvent.click(screen.getByRole("button", { name: /jobs/i }));
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
    expect((await screen.findByTestId("job-row")).textContent).toContain("job-1 succeeded");
    expect(screen.queryByText("No jobs")).toBeNull();
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
      "job-2 hibernating",
      "job-1 succeeded",
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
  });
});
