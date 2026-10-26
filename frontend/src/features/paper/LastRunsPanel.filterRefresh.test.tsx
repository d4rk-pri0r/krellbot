// Regression coverage for keeping an explicitly selected venue/status
// filter honest across paper-history refreshes. The option sets are
// derived from the loaded records, so a refresh that removes the last
// row matching the selection used to drop the selected value's
// <option> while the predicate kept filtering: the native select then
// read as all/blank while the table said no runs matched, despite real
// other history. The selection must stay visible as an option, stay
// applied, and merge back without duplication when its records return.
//
// SYNTHETIC FIXTURES: every PaperHistory below is fabricated in-memory
// test data standing in for the loopback paper-history wire. No
// backend, session, credentials or live trading is involved.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    last_refusal_code: null,
    mode: "paper",
    status: "active",
    summary: "4 ticks, 0 fills, active",
    recent_fills: [],
    ...overrides,
  };
}

function krakenActive(): PaperRun {
  return syntheticRun();
}

function coinbaseClosed(): PaperRun {
  return syntheticRun({
    venue: "coinbase",
    pair: "BTCUSD",
    pack_id: "mean-revert",
    first_ts_ms: Date.UTC(2026, 9, 6, 9, 0, 0),
    last_ts_ms: Date.UTC(2026, 9, 6, 10, 0, 0),
    status: "closed",
    summary: "2 ticks, 0 fills, closed",
  });
}

function dotusdFailed(): PaperRun {
  return syntheticRun({
    pair: "DOTUSD",
    first_ts_ms: Date.UTC(2026, 9, 5, 8, 0, 0),
    last_ts_ms: Date.UTC(2026, 9, 5, 8, 30, 0),
    status: "failed",
    summary: "1 tick, 0 fills, failed",
  });
}

function history(runs: PaperRun[]): PaperHistory {
  return { schema_version: "1", runs };
}

/** Mount the panel against a scripted listRuns sequence; each read is
 *  either a synthetic history or an Error the read rejects with. Waits
 *  for the first read's table so the panel starts loaded. */
async function mount(reads: Array<PaperHistory | Error>): Promise<ReturnType<typeof vi.fn>> {
  const listRuns = vi.fn();
  for (const read of reads) {
    if (read instanceof Error) {
      listRuns.mockRejectedValueOnce(read);
    } else {
      listRuns.mockResolvedValueOnce(read);
    }
  }
  const client = {
    getStatus: vi.fn(),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    listRuns,
  } as unknown as PaperClient & PaperRunsClient;
  render(<LastRunsPanel client={client} />);
  await waitFor(() => {
    expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
  });
  return listRuns;
}

const venueSelect = () =>
  screen.getByRole("combobox", { name: "Filter runs by venue" }) as HTMLSelectElement;
const statusSelect = () =>
  screen.getByRole("combobox", { name: "Filter runs by status" }) as HTMLSelectElement;
const queryInput = () =>
  screen.getByRole("textbox", { name: "Search runs by pack, pair or summary" }) as HTMLInputElement;
const optionValues = (control: HTMLElement) =>
  within(control).getAllByRole("option").map((node) => (node as HTMLOptionElement).value);
const runRows = () => screen.queryAllByRole("row", { name: /^Open run detail/ });
const countChip = () => screen.getByTestId("paper-last-runs-count");
const change = (control: HTMLElement, value: string) =>
  fireEvent.change(control, { target: { value } });
const refresh = () => fireEvent.click(screen.getByTestId("paper-last-runs-refresh"));

describe("LastRunsPanel — filter selections vs history refresh", () => {
  it("keeps a selected venue applied and selectable when refresh removes its last run", async () => {
    const listRuns = await mount([
      history([krakenActive(), coinbaseClosed()]),
      history([coinbaseClosed()]),
    ]);
    change(venueSelect(), "kraken");
    expect(runRows()).toHaveLength(1);

    refresh();
    await waitFor(() => {
      expect(countChip().textContent).toBe("1 run");
    });

    // Real other history exists; the old filter still applies, so the
    // truthful table state is "no matches", never a silent switch to all.
    expect(runRows()).toHaveLength(0);
    expect(screen.getByTestId("paper-last-runs-filter-empty").textContent).toBe(
      "No runs match the current filters.",
    );
    expect(screen.queryByTestId("paper-last-runs-empty")).toBeNull();
    expect(venueSelect().value).toBe("kraken");
    expect(optionValues(venueSelect())).toEqual(["", "coinbase", "kraken"]);
    expect(listRuns).toHaveBeenCalledTimes(2);
  });

  it("keeps a selected status applied and selectable when refresh removes its last run", async () => {
    const listRuns = await mount([
      history([krakenActive(), coinbaseClosed()]),
      history([coinbaseClosed()]),
    ]);
    change(statusSelect(), "active");
    expect(runRows()).toHaveLength(1);

    refresh();
    await waitFor(() => {
      expect(countChip().textContent).toBe("1 run");
    });

    expect(runRows()).toHaveLength(0);
    expect(screen.getByTestId("paper-last-runs-filter-empty").textContent).toBe(
      "No runs match the current filters.",
    );
    expect(statusSelect().value).toBe("active");
    expect(optionValues(statusSelect())).toEqual(["", "closed", "active"]);
    expect(listRuns).toHaveBeenCalledTimes(2);
  });

  it("preserves venue and status selections together when refresh removes both", async () => {
    await mount([
      history([krakenActive(), coinbaseClosed()]),
      history([coinbaseClosed()]),
    ]);
    change(venueSelect(), "kraken");
    change(statusSelect(), "active");
    expect(runRows()).toHaveLength(1);

    refresh();
    await waitFor(() => {
      expect(countChip().textContent).toBe("1 run");
    });

    expect(runRows()).toHaveLength(0);
    expect(screen.getByTestId("paper-last-runs-filter-empty")).toBeDefined();
    expect(venueSelect().value).toBe("kraken");
    expect(statusSelect().value).toBe("active");
    expect(optionValues(venueSelect())).toEqual(["", "coinbase", "kraken"]);
    expect(optionValues(statusSelect())).toEqual(["", "closed", "active"]);
  });

  it("leaves an unselected filter at all with no phantom options across refresh", async () => {
    await mount([
      history([krakenActive(), coinbaseClosed()]),
      history([krakenActive(), coinbaseClosed(), dotusdFailed()]),
    ]);
    expect(venueSelect().value).toBe("");
    expect(statusSelect().value).toBe("");

    refresh();
    await waitFor(() => {
      expect(countChip().textContent).toBe("3 runs");
    });

    expect(venueSelect().value).toBe("");
    expect(statusSelect().value).toBe("");
    expect(optionValues(venueSelect())).toEqual(["", "kraken", "coinbase"]);
    expect(optionValues(statusSelect())).toEqual(["", "active", "closed", "failed"]);
    expect(runRows()).toHaveLength(3);
  });

  it("merges the preserved selection back without duplication when its runs return", async () => {
    await mount([
      history([krakenActive(), coinbaseClosed()]),
      history([coinbaseClosed()]),
      history([coinbaseClosed(), krakenActive()]),
    ]);
    change(venueSelect(), "kraken");

    refresh();
    await waitFor(() => {
      expect(countChip().textContent).toBe("1 run");
    });
    expect(optionValues(venueSelect())).toEqual(["", "coinbase", "kraken"]);

    refresh();
    await waitFor(() => {
      expect(countChip().textContent).toBe("2 runs");
    });

    expect(optionValues(venueSelect())).toEqual(["", "coinbase", "kraken"]);
    expect(optionValues(venueSelect()).filter((value) => value === "kraken")).toHaveLength(1);
    expect(venueSelect().value).toBe("kraken");
    expect(runRows()).toHaveLength(1);
    expect(screen.queryByTestId("paper-last-runs-filter-empty")).toBeNull();
  });

  it("preserves the search query across a refresh that drops the filtered rows", async () => {
    await mount([
      history([krakenActive(), coinbaseClosed()]),
      history([coinbaseClosed()]),
    ]);
    change(queryInput(), "active");
    expect(runRows()).toHaveLength(1);

    refresh();
    await waitFor(() => {
      expect(countChip().textContent).toBe("1 run");
    });

    expect(queryInput().value).toBe("active");
    expect(runRows()).toHaveLength(0);
    expect(screen.getByTestId("paper-last-runs-filter-empty").textContent).toBe(
      "No runs match the current filters.",
    );
  });

  it("recovers via explicit Clear filters, revealing real rows without a new read", async () => {
    const listRuns = await mount([
      history([krakenActive(), coinbaseClosed()]),
      history([coinbaseClosed()]),
    ]);
    change(venueSelect(), "kraken");
    change(statusSelect(), "active");
    change(queryInput(), "active");
    expect(runRows()).toHaveLength(1);

    refresh();
    await waitFor(() => {
      expect(countChip().textContent).toBe("1 run");
    });
    expect(runRows()).toHaveLength(0);

    fireEvent.click(screen.getByTestId("paper-last-runs-filter-clear"));

    expect(runRows()).toHaveLength(1);
    expect(screen.getByTestId("paper-last-runs-row-coinbase-BTCUSD")).toBeDefined();
    expect(screen.queryByTestId("paper-last-runs-filter-empty")).toBeNull();
    expect(screen.queryByTestId("paper-last-runs-filter-clear")).toBeNull();
    expect(venueSelect().value).toBe("");
    expect(statusSelect().value).toBe("");
    expect(queryInput().value).toBe("");
    // Clearing is local: it re-reveals loaded rows and never re-fetches.
    expect(listRuns).toHaveBeenCalledTimes(2);
  });

  it("keeps last-good rows, options and selection and shows the error when a refresh fails", async () => {
    const listRuns = await mount([
      history([krakenActive(), coinbaseClosed()]),
      new Error("paper history refused: csrf required"),
    ]);
    change(venueSelect(), "kraken");
    expect(runRows()).toHaveLength(1);

    refresh();
    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-error").textContent).toBe(
        "paper history refused: csrf required",
      );
    });

    // The failed read leaves the last-good data, options and selection.
    expect(runRows()).toHaveLength(1);
    expect(screen.getByTestId("paper-last-runs-row-kraken-SUIUSD")).toBeDefined();
    expect(screen.queryByTestId("paper-last-runs-filter-empty")).toBeNull();
    expect(venueSelect().value).toBe("kraken");
    expect(optionValues(venueSelect())).toEqual(["", "kraken", "coinbase"]);
    expect(listRuns).toHaveBeenCalledTimes(2);
  });

  it("keeps the selection through a refresh to empty history and a later recovery", async () => {
    await mount([
      history([krakenActive(), coinbaseClosed()]),
      history([]),
      history([krakenActive()]),
    ]);
    change(venueSelect(), "kraken");

    refresh();
    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-empty").textContent).toBe("No paper runs yet");
    });
    expect(screen.queryByTestId("paper-last-runs-table")).toBeNull();
    expect(screen.queryByTestId("paper-last-runs-filter-empty")).toBeNull();
    expect(venueSelect().value).toBe("kraken");
    expect(optionValues(venueSelect())).toEqual(["", "kraken"]);

    refresh();
    await waitFor(() => {
      expect(countChip().textContent).toBe("1 run");
    });
    expect(screen.queryByTestId("paper-last-runs-empty")).toBeNull();
    expect(runRows()).toHaveLength(1);
    expect(optionValues(venueSelect()).filter((value) => value === "kraken")).toHaveLength(1);
  });

  it("still reconciles the selected run detail by identity across refresh with a filter held", async () => {
    await mount([
      history([krakenActive(), coinbaseClosed()]),
      history([
        syntheticRun({
          last_ts_ms: Date.UTC(2026, 9, 7, 12, 0, 0),
          ticks_total: 9,
          summary: "9 ticks, 0 fills, active",
        }),
        coinbaseClosed(),
      ]),
    ]);
    change(venueSelect(), "kraken");
    fireEvent.click(screen.getByTestId("paper-last-runs-row-kraken-SUIUSD"));
    expect(screen.getByTestId("paper-last-runs-detail-summary").textContent).toBe(
      "4 ticks, 0 fills, active",
    );

    refresh();
    await waitFor(() => {
      expect(screen.getAllByText("9 ticks, 0 fills, active").length).toBeGreaterThan(0);
    });

    expect(screen.getByTestId("paper-last-runs-detail-summary").textContent).toBe(
      "9 ticks, 0 fills, active",
    );
    expect(screen.getByTestId("paper-last-runs-row-kraken-SUIUSD").getAttribute("aria-expanded")).toBe(
      "true",
    );
    expect(venueSelect().value).toBe("kraken");
  });
});
