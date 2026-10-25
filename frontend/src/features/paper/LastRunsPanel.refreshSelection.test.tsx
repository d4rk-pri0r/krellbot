// Regression coverage for reconciling the selected paper run with each
// successful history refresh, keyed by the stable row identity the table
// already uses: venue, pair, pack_id, first_ts_ms.
//
// SYNTHETIC FIXTURES: every PaperHistory below is fabricated in-memory test
// data standing in for the loopback paper-history wire. No backend, session,
// credentials or live trading is involved.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LastRunsPanel } from "./LastRunsPanel";
import type { PaperClient, PaperHistory, PaperRun, PaperRunsClient } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function syntheticRun(overrides: Partial<PaperRun> = {}): PaperRun {
  return {
    venue: "kraken",
    pair: "SUIUSD",
    pack_id: "trend-follow",
    first_ts_ms: Date.UTC(2026, 9, 7, 10, 0, 0),
    last_ts_ms: Date.UTC(2026, 9, 7, 11, 0, 0),
    ticks_total: 4,
    last_refusal_code: "store_full",
    mode: "paper",
    status: "closed",
    summary: "4 ticks, 1 fill, last refusal store_full, closed",
    recent_fills: [
      { coid: "synthetic-coid-entry-1", side: "buy", ts_ms: 1_000 },
    ],
    ...overrides,
  };
}

function syntheticHistory(runs: PaperRun[]): PaperHistory {
  return { schema_version: "1", runs };
}

function makeClient(first: PaperHistory): {
  client: PaperClient & PaperRunsClient;
  listRuns: ReturnType<typeof vi.fn>;
} {
  const listRuns = vi.fn().mockResolvedValue(first);
  const client = {
    getStatus: vi.fn(),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    listRuns,
  } as unknown as PaperClient & PaperRunsClient;
  return { client, listRuns };
}

type Deferred<T> = {
  promise: Promise<T>;
  resolve(value: T): void;
  reject(err: unknown): void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (err: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function renderLoaded(client: PaperClient & PaperRunsClient): Promise<void> {
  render(<LastRunsPanel client={client} />);
  await waitFor(() => {
    expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
  });
}

const SUIUSD_ROW = "paper-last-runs-row-kraken-SUIUSD";

function rowIsSelected(): boolean {
  return screen
    .getByTestId(SUIUSD_ROW)
    .classList.contains("kbot-paper-runs__row--selected");
}

describe("LastRunsPanel — selected run vs history refresh", () => {
  it("re-selects the same identity's new returned object: fresh detail, fills and row semantics", async () => {
    const before = syntheticHistory([
      syntheticRun(),
      syntheticRun({
        pair: "DOTUSD",
        first_ts_ms: Date.UTC(2026, 9, 6, 10, 0, 0),
        last_ts_ms: Date.UTC(2026, 9, 6, 10, 30, 0),
        ticks_total: 1,
        last_refusal_code: null,
        summary: "1 tick, 0 fills, no refusal, closed",
        recent_fills: [],
      }),
    ]);
    const after = syntheticHistory([
      syntheticRun({
        last_ts_ms: Date.UTC(2026, 9, 7, 12, 0, 0),
        ticks_total: 9,
        last_refusal_code: null,
        status: "active",
        summary: "9 ticks, 2 fills, no refusal, active",
        recent_fills: [
          { coid: "synthetic-coid-entry-1", side: "buy", ts_ms: 1_000 },
          { coid: "synthetic-coid-exit-2", side: "sell", ts_ms: 2_000 },
        ],
      }),
      syntheticRun({
        pair: "DOTUSD",
        first_ts_ms: Date.UTC(2026, 9, 6, 10, 0, 0),
        last_ts_ms: Date.UTC(2026, 9, 6, 10, 30, 0),
        ticks_total: 1,
        last_refusal_code: null,
        summary: "1 tick, 0 fills, no refusal, closed",
        recent_fills: [],
      }),
    ]);
    const { client } = makeClient(before);
    (client.listRuns as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(before)
      .mockResolvedValueOnce(after);
    await renderLoaded(client);

    fireEvent.click(screen.getByTestId(SUIUSD_ROW));
    expect(screen.getByTestId("paper-last-runs-detail-summary").textContent).toBe(
      "4 ticks, 1 fill, last refusal store_full, closed",
    );

    fireEvent.click(screen.getByTestId("paper-last-runs-refresh"));

    await waitFor(() => {
      expect(screen.getAllByText("9 ticks, 2 fills, no refusal, active").length).toBeGreaterThan(0);
    });
    // The refreshed row keeps its open-detail semantics (no stale reference).
    expect(screen.getByTestId(SUIUSD_ROW).getAttribute("aria-expanded")).toBe("true");
    expect(rowIsSelected()).toBe(true);
    // The detail shows the actual returned object, not the pre-refresh one.
    expect(screen.getByTestId("paper-last-runs-detail-summary").textContent).toBe(
      "9 ticks, 2 fills, no refusal, active",
    );
    const fillRows = screen
      .getByTestId("paper-last-runs-fills-table")
      .querySelectorAll("tbody tr");
    expect(fillRows.length).toBe(2);
    expect(screen.getByText("synthetic-coid-exit-2")).toBeDefined();
  });

  it("closes the obsolete detail when a successful refresh omits the selected run", async () => {
    const before = syntheticHistory([
      syntheticRun(),
      syntheticRun({
        pair: "DOTUSD",
        first_ts_ms: Date.UTC(2026, 9, 6, 10, 0, 0),
        last_ts_ms: Date.UTC(2026, 9, 6, 10, 30, 0),
        ticks_total: 1,
        last_refusal_code: null,
        summary: "1 tick, 0 fills, no refusal, closed",
        recent_fills: [],
      }),
    ]);
    const after = syntheticHistory([
      syntheticRun({
        pair: "DOTUSD",
        first_ts_ms: Date.UTC(2026, 9, 6, 10, 0, 0),
        last_ts_ms: Date.UTC(2026, 9, 6, 10, 30, 0),
        ticks_total: 1,
        last_refusal_code: null,
        summary: "1 tick, 0 fills, no refusal, closed",
        recent_fills: [],
      }),
    ]);
    const { client } = makeClient(before);
    (client.listRuns as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(before)
      .mockResolvedValueOnce(after);
    await renderLoaded(client);

    fireEvent.click(screen.getByTestId(SUIUSD_ROW));
    expect(screen.getByTestId("paper-last-runs-detail")).toBeDefined();

    fireEvent.click(screen.getByTestId("paper-last-runs-refresh"));

    await waitFor(() => {
      expect(screen.queryByTestId(SUIUSD_ROW)).toBeNull();
    });
    expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();
    expect(screen.queryByTestId("paper-last-runs-detail-summary")).toBeNull();
    expect(screen.getByTestId("paper-last-runs-row-kraken-DOTUSD")).toBeDefined();
    expect(
      screen
        .getByTestId("paper-last-runs-row-kraken-DOTUSD")
        .getAttribute("aria-expanded"),
    ).toBe("false");
  });

  it("closes the detail when a successful refresh returns an empty run list", async () => {
    const before = syntheticHistory([syntheticRun()]);
    const { client } = makeClient(before);
    (client.listRuns as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(before)
      .mockResolvedValueOnce(syntheticHistory([]));
    await renderLoaded(client);

    fireEvent.click(screen.getByTestId(SUIUSD_ROW));
    expect(screen.getByTestId("paper-last-runs-detail")).toBeDefined();

    fireEvent.click(screen.getByTestId("paper-last-runs-refresh"));

    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-empty")).toBeDefined();
    });
    expect(screen.queryByTestId("paper-last-runs-table")).toBeNull();
    expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();
  });

  it("a failed refresh retains the last good table and open detail and exposes its error", async () => {
    const before = syntheticHistory([syntheticRun()]);
    const { client } = makeClient(before);
    (client.listRuns as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(before)
      .mockRejectedValueOnce(new Error("paper history refused: csrf required"));
    await renderLoaded(client);

    fireEvent.click(screen.getByTestId(SUIUSD_ROW));
    expect(screen.getByTestId("paper-last-runs-detail")).toBeDefined();

    fireEvent.click(screen.getByTestId("paper-last-runs-refresh"));

    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-error")).toBeDefined();
    });
    expect(screen.getByTestId("paper-last-runs-error").textContent).toBe(
      "paper history refused: csrf required",
    );
    expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
    expect(screen.getByTestId("paper-last-runs-detail")).toBeDefined();
    expect(screen.getByTestId("paper-last-runs-detail-summary").textContent).toBe(
      "4 ticks, 1 fill, last refusal store_full, closed",
    );
    expect(screen.getByTestId(SUIUSD_ROW).getAttribute("aria-expanded")).toBe("true");
  });

  it("reconciles a selection made while a refresh is pending", async () => {
    const before = syntheticHistory([syntheticRun()]);
    const pending = deferred<PaperHistory>();
    const { client } = makeClient(before);
    (client.listRuns as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(before)
      .mockReturnValueOnce(pending.promise);
    await renderLoaded(client);

    fireEvent.click(screen.getByTestId("paper-last-runs-refresh"));
    // Fresh selection while the refresh is still in flight.
    fireEvent.click(screen.getByTestId(SUIUSD_ROW));
    expect(screen.getByTestId("paper-last-runs-detail-summary").textContent).toBe(
      "4 ticks, 1 fill, last refusal store_full, closed",
    );

    pending.resolve(
      syntheticHistory([
        syntheticRun({
          ticks_total: 7,
          status: "active",
          summary: "7 ticks, 1 fill, no refusal, active",
          recent_fills: [
            { coid: "synthetic-coid-entry-9", side: "buy", ts_ms: 9_000 },
          ],
        }),
      ]),
    );

    await waitFor(() => {
      expect(screen.getAllByText("7 ticks, 1 fill, no refusal, active").length).toBeGreaterThan(0);
    });
    expect(screen.getByTestId(SUIUSD_ROW).getAttribute("aria-expanded")).toBe("true");
    expect(rowIsSelected()).toBe(true);
    expect(screen.getByTestId("paper-last-runs-detail-summary").textContent).toBe(
      "7 ticks, 1 fill, no refusal, active",
    );
    expect(screen.getByText("synthetic-coid-entry-9")).toBeDefined();
  });

  it("keeps a detail closed during a pending refresh closed after it succeeds (no auto-selection)", async () => {
    const before = syntheticHistory([syntheticRun()]);
    const pending = deferred<PaperHistory>();
    const { client } = makeClient(before);
    (client.listRuns as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(before)
      .mockReturnValueOnce(pending.promise);
    await renderLoaded(client);

    fireEvent.click(screen.getByTestId("paper-last-runs-refresh"));
    fireEvent.click(screen.getByTestId(SUIUSD_ROW));
    fireEvent.click(screen.getByTestId("paper-last-runs-detail-close"));
    expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();

    pending.resolve(
      syntheticHistory([
        syntheticRun({ ticks_total: 5, summary: "5 ticks, 1 fill, no refusal, closed" }),
      ]),
    );

    await waitFor(() => {
      expect(screen.getByText("5 ticks, 1 fill, no refusal, closed")).toBeDefined();
    });
    expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();
    expect(screen.getByTestId(SUIUSD_ROW).getAttribute("aria-expanded")).toBe("false");
  });

  it("treats local filtering as hiding, not deleting: a filtered-away selection survives refresh", async () => {
    const before = syntheticHistory([
      syntheticRun({ pack_id: "alpha-pack" }),
      syntheticRun({
        pair: "DOTUSD",
        pack_id: "delta-pack",
        first_ts_ms: Date.UTC(2026, 9, 6, 10, 0, 0),
        last_ts_ms: Date.UTC(2026, 9, 6, 10, 30, 0),
        ticks_total: 1,
        last_refusal_code: null,
        summary: "1 tick, 0 fills, no refusal, closed",
        recent_fills: [],
      }),
    ]);
    const after = syntheticHistory([
      syntheticRun({
        pack_id: "alpha-pack",
        ticks_total: 6,
        summary: "6 ticks, 1 fill, no refusal, closed",
      }),
      syntheticRun({
        pair: "DOTUSD",
        pack_id: "delta-pack",
        first_ts_ms: Date.UTC(2026, 9, 6, 10, 0, 0),
        last_ts_ms: Date.UTC(2026, 9, 6, 10, 30, 0),
        ticks_total: 1,
        last_refusal_code: null,
        summary: "1 tick, 0 fills, no refusal, closed",
        recent_fills: [],
      }),
    ]);
    const { client } = makeClient(before);
    (client.listRuns as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(before)
      .mockResolvedValueOnce(after);
    await renderLoaded(client);

    fireEvent.click(screen.getByTestId(SUIUSD_ROW));
    // Filter the selected row away locally; that is not deletion.
    fireEvent.change(
      screen.getByRole("textbox", { name: "Search runs by pack, pair or summary" }),
      { target: { value: "delta" } },
    );
    expect(screen.queryByTestId(SUIUSD_ROW)).toBeNull();
    expect(screen.getByTestId("paper-last-runs-detail")).toBeDefined();

    fireEvent.click(screen.getByTestId("paper-last-runs-refresh"));

    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-count").textContent).toBe("2 runs");
    });
    // The selected run still exists underneath the filter: its detail tracks
    // the refreshed object and does not close.
    expect(screen.getByTestId("paper-last-runs-detail-summary").textContent).toBe(
      "6 ticks, 1 fill, no refusal, closed",
    );

    fireEvent.click(screen.getByTestId("paper-last-runs-filter-clear"));
    expect(screen.getByTestId(SUIUSD_ROW).getAttribute("aria-expanded")).toBe("true");
    expect(rowIsSelected()).toBe(true);
  });

  it("reconciles distinct identities that share venue and pair independently", async () => {
    const early = syntheticRun({
      first_ts_ms: Date.UTC(2026, 9, 7, 10, 0, 0),
      summary: "early run, closed",
      recent_fills: [],
    });
    const late = syntheticRun({
      first_ts_ms: Date.UTC(2026, 9, 7, 12, 0, 0),
      last_ts_ms: Date.UTC(2026, 9, 7, 13, 0, 0),
      summary: "late run, closed",
      recent_fills: [],
    });
    const before = syntheticHistory([early, late]);
    const after = syntheticHistory([
      syntheticRun({
        first_ts_ms: early.first_ts_ms,
        summary: "early run refreshed, closed",
        recent_fills: [],
      }),
      syntheticRun({
        first_ts_ms: late.first_ts_ms,
        last_ts_ms: Date.UTC(2026, 9, 7, 13, 0, 0),
        summary: "late run refreshed, closed",
        recent_fills: [],
      }),
    ]);
    const { client } = makeClient(before);
    (client.listRuns as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(before)
      .mockResolvedValueOnce(after);
    await renderLoaded(client);

    const rowsBefore = screen.getAllByRole("row", {
      name: "Open run detail for kraken SUIUSD",
    });
    expect(rowsBefore.length).toBe(2);
    fireEvent.click(rowsBefore[1]!);
    expect(screen.getByTestId("paper-last-runs-detail-summary").textContent).toBe(
      "late run, closed",
    );

    fireEvent.click(screen.getByTestId("paper-last-runs-refresh"));

    await waitFor(() => {
      expect(screen.getAllByText("late run refreshed, closed").length).toBeGreaterThan(0);
    });
    const rowsAfter = screen.getAllByRole("row", {
      name: "Open run detail for kraken SUIUSD",
    });
    expect(rowsAfter[1]!.getAttribute("aria-expanded")).toBe("true");
    expect(
      rowsAfter[1]!.classList.contains("kbot-paper-runs__row--selected"),
    ).toBe(true);
    expect(rowsAfter[0]!.getAttribute("aria-expanded")).toBe("false");
    expect(
      rowsAfter[0]!.classList.contains("kbot-paper-runs__row--selected"),
    ).toBe(false);
    expect(screen.getByTestId("paper-last-runs-detail-summary").textContent).toBe(
      "late run refreshed, closed",
    );
  });
});
