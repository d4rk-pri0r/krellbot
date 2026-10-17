import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LastRunsPanel } from "./LastRunsPanel";
import type { PaperClient, PaperHistory, PaperRunsClient } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

beforeEach(() => {
  vi.spyOn(Storage.prototype, "setItem");
});

function makeHistory(overrides: Partial<PaperHistory> = {}): PaperHistory {
  return {
    schema_version: "1",
    runs: [
      {
        venue: "kraken",
        pair: "SUIUSD",
        pack_id: "trend-follow",
        pack_version: "1",
        first_ts_ms: Date.UTC(2026, 9, 7, 10, 0, 0),
        last_ts_ms: Date.UTC(2026, 9, 7, 11, 0, 0),
        ticks_total: 4,
        last_refusal_code: "store_full",
        mode: "paper",
        status: "closed",
        summary: "4 ticks, 1 fill, last refusal store_full, closed",
        recent_fills: [
          { coid: "coid-entry-1", side: "buy", ts_ms: 1_000 },
        ],
      },
      {
        venue: "kraken",
        pair: "DOTUSD",
        pack_id: "trend-follow",
        first_ts_ms: Date.UTC(2026, 9, 6, 10, 0, 0),
        last_ts_ms: Date.UTC(2026, 9, 6, 10, 30, 0),
        ticks_total: 1,
        last_refusal_code: null,
        mode: "paper",
        status: "closed",
        summary: "1 tick, 0 fills, no refusal, closed",
        recent_fills: [],
      },
    ],
    ...overrides,
  };
}

function makeClient(
  history: PaperHistory = makeHistory(),
): PaperClient & PaperRunsClient {
  const client = {
    getStatus: vi.fn(),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    listRuns: vi.fn().mockResolvedValue(history),
  } as unknown as PaperClient & PaperRunsClient;
  return client;
}

describe("LastRunsPanel — read-only Last runs table", () => {
  it("loads runs once on mount and renders venue/pair/started/ended/fills/refusal/summary", async () => {
    const client = makeClient();
    render(<LastRunsPanel client={client} />);

    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
    });
    expect(client.listRuns).toHaveBeenCalledTimes(1);

    expect(screen.getAllByText("kraken").length).toBe(2);
    expect(screen.getAllByText("SUIUSD").length).toBeGreaterThan(0);
    expect(screen.getAllByText("DOTUSD").length).toBeGreaterThan(0);
    expect(screen.getByTestId("paper-last-runs-fills-kraken-SUIUSD").textContent).toBe("1");
    expect(screen.getByTestId("paper-last-runs-fills-kraken-DOTUSD").textContent).toBe("0");
    expect(screen.getByText("store_full")).toBeDefined();
    expect(screen.getByText("none")).toBeDefined();
    expect(
      screen.getByText("4 ticks, 1 fill, last refusal store_full, closed"),
    ).toBeDefined();
    expect(
      screen.getByText("1 tick, 0 fills, no refusal, closed"),
    ).toBeDefined();
  });

  it("renders started and ended timestamps per row", async () => {
    const client = makeClient();
    render(<LastRunsPanel client={client} />);

    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
    });
    expect(
      screen.getAllByText("2026-10-07T10:00:00.000Z").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("2026-10-07T11:00:00.000Z").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("2026-10-06T10:30:00.000Z").length,
    ).toBeGreaterThan(0);
  });

  it("shows the empty state when there are no runs", async () => {
    const client = makeClient(makeHistory({ runs: [] }));
    render(<LastRunsPanel client={client} />);

    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-empty")).toBeDefined();
    });
    expect(screen.queryByTestId("paper-last-runs-table")).toBeNull();
  });

  it("shows the error state and no table when the first load fails", async () => {
    const client = makeClient();
    (client.listRuns as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("paper history refused: session required"),
    );
    render(<LastRunsPanel client={client} />);

    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-error")).toBeDefined();
    });
    expect(
      screen.getByText("paper history refused: session required"),
    ).toBeDefined();
    expect(screen.queryByTestId("paper-last-runs-table")).toBeNull();
    expect(screen.getByTestId("paper-last-runs-empty")).toBeDefined();
  });

  it("refresh re-reads the history and renders the fresh rows", async () => {
    const first = makeHistory();
    const client = makeClient(first);
    (client.listRuns as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(
        makeHistory({
          runs: [
            {
              venue: "kraken",
              pair: "SUIUSD",
              pack_id: "trend-follow",
              first_ts_ms: 1,
              last_ts_ms: 2,
              ticks_total: 9,
              last_refusal_code: null,
              mode: "paper",
              status: "active",
              summary: "9 ticks, 0 fills, no refusal, active",
              recent_fills: [],
            },
          ],
        }),
      );
    render(<LastRunsPanel client={client} />);
    await waitFor(() => {
      expect(screen.getByText("4 ticks, 1 fill, last refusal store_full, closed")).toBeDefined();
    });

    fireEvent.click(screen.getByTestId("paper-last-runs-refresh"));

    await waitFor(() => {
      expect(screen.getByText("9 ticks, 0 fills, no refusal, active")).toBeDefined();
    });
    expect(client.listRuns).toHaveBeenCalledTimes(2);
    expect(
      screen.queryByText("4 ticks, 1 fill, last refusal store_full, closed"),
    ).toBeNull();
  });

  it("keeps the last good table when a refresh fails", async () => {
    const first = makeHistory();
    const client = makeClient(first);
    (client.listRuns as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(first)
      .mockRejectedValueOnce(new Error("paper history refused: csrf required"));
    render(<LastRunsPanel client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
    });

    fireEvent.click(screen.getByTestId("paper-last-runs-refresh"));

    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-error")).toBeDefined();
    });
    expect(
      screen.getByText("paper history refused: csrf required"),
    ).toBeDefined();
    expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
  });

  it("clicking a row shows the run summary detail; closing hides it", async () => {
    const client = makeClient();
    render(<LastRunsPanel client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
    });
    expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();

    fireEvent.click(screen.getByTestId("paper-last-runs-row-kraken-SUIUSD"));

    expect(screen.getByTestId("paper-last-runs-detail")).toBeDefined();
    expect(
      screen.getByTestId("paper-last-runs-detail-summary").textContent,
    ).toBe("4 ticks, 1 fill, last refusal store_full, closed");

    fireEvent.click(screen.getByTestId("paper-last-runs-detail-close"));
    expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();
  });

  it("offers no editing, arming, or start control beyond refresh", async () => {
    const client = makeClient();
    render(<LastRunsPanel client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
    });

    const buttons = screen.getAllByRole("button").map((node) => node.textContent);
    expect(buttons).toEqual(["Refresh"]);
    expect(client.pauseEntries).not.toHaveBeenCalled();
    expect(client.resumeEntries).not.toHaveBeenCalled();
    expect(client.disarm).not.toHaveBeenCalled();
    expect(client.getStatus).not.toHaveBeenCalled();
  });

  it("renders the loading state before the first history resolves", () => {
    const client = makeClient();
    (client.listRuns as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise<PaperHistory>(() => {}),
    );
    render(<LastRunsPanel client={client} />);
    expect(screen.getByTestId("paper-last-runs-loading")).toBeDefined();
    expect(screen.queryByTestId("paper-last-runs-table")).toBeNull();
  });
});
