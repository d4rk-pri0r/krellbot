// Pin the zone so the "Time (ISO local)" column assertions are deterministic
// regardless of the host running the suite.
process.env.TZ = "UTC";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LastRunsPanel } from "./LastRunsPanel";
import type { PaperClient, PaperHistory, PaperRunFill, PaperRunsClient } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const FILL_A: PaperRunFill = { coid: "coid-entry-1", side: "buy", ts_ms: Date.UTC(2026, 9, 7, 9, 30, 5) };
const FILL_B: PaperRunFill = { coid: "coid-exit-2", side: "sell", ts_ms: Date.UTC(2026, 9, 7, 10, 15, 0) };

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
        summary: "4 ticks, 2 fills, last refusal store_full, closed",
        recent_fills: [FILL_A, FILL_B],
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
  return {
    getStatus: vi.fn(),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    listRuns: vi.fn().mockResolvedValue(history),
  } as unknown as PaperClient & PaperRunsClient;
}

async function renderPanel(client: PaperClient & PaperRunsClient): Promise<void> {
  render(<LastRunsPanel client={client} />);
  await waitFor(() => {
    expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
  });
}

describe("LastRunsPanel — detail fills table", () => {
  it("clicking a row with fills reveals one fill row per recent_fill (Time/Pair/Side/Coid)", async () => {
    await renderPanel(makeClient());

    expect(screen.queryByTestId("paper-last-runs-fills-table")).toBeNull();
    fireEvent.click(screen.getByTestId("paper-last-runs-row-kraken-SUIUSD"));

    const table = screen.getByTestId("paper-last-runs-fills-table");
    const headerCells = Array.from(table.querySelectorAll("thead th")).map(
      (cell) => cell.textContent,
    );
    expect(headerCells).toEqual(["Time", "Pair", "Side", "Coid"]);

    const bodyRows = table.querySelectorAll("tbody tr");
    expect(bodyRows.length).toBe(2);
  });

  it("renders fill coid/side verbatim, the run-level pair, and ISO-local time per fill row", async () => {
    await renderPanel(makeClient());

    fireEvent.click(screen.getByTestId("paper-last-runs-row-kraken-SUIUSD"));

    const rows = Array.from(
      screen
        .getByTestId("paper-last-runs-fills-table")
        .querySelectorAll("tbody tr"),
    );
    const cells = rows.map((row) =>
      Array.from(row.querySelectorAll("td")).map((cell) => cell.textContent),
    );

    expect(cells).toEqual([
      ["2026-10-07T09:30:05", "SUIUSD", "buy", "coid-entry-1"],
      ["2026-10-07T10:15:00", "SUIUSD", "sell", "coid-exit-2"],
    ]);
    expect(screen.getByText("coid-entry-1")).toBeDefined();
    expect(screen.getByText("sell")).toBeDefined();
  });

  it("clicking a row whose recent_fills is empty shows the placeholder, not an empty table", async () => {
    await renderPanel(makeClient());

    fireEvent.click(screen.getByTestId("paper-last-runs-row-kraken-DOTUSD"));

    expect(screen.getByText("no fills in this run")).toBeDefined();
    expect(screen.queryByTestId("paper-last-runs-fills-table")).toBeNull();
    expect(
      screen.getByTestId("paper-last-runs-detail-summary").textContent,
    ).toBe("1 tick, 0 fills, no refusal, closed");
  });

  it("closing the detail panel hides the summary and the fills together", async () => {
    await renderPanel(makeClient());

    fireEvent.click(screen.getByTestId("paper-last-runs-row-kraken-SUIUSD"));
    expect(screen.getByTestId("paper-last-runs-fills-table")).toBeDefined();
    expect(screen.getByTestId("paper-last-runs-detail-summary")).toBeDefined();

    fireEvent.click(screen.getByTestId("paper-last-runs-detail-close"));

    expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();
    expect(screen.queryByTestId("paper-last-runs-fills-table")).toBeNull();
    expect(screen.queryByTestId("paper-last-runs-detail-summary")).toBeNull();
    expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
  });

  it("still shows the Fills column count matching run.recent_fills.length (regression guard)", async () => {
    const history = makeHistory();
    await renderPanel(makeClient(history));

    for (const run of history.runs) {
      expect(
        screen.getByTestId(`paper-last-runs-fills-${run.venue}-${run.pair}`)
          .textContent,
      ).toBe(String(run.recent_fills.length));
    }
  });
});
