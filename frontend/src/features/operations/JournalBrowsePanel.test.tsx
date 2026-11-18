import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JournalBrowsePanel } from "./JournalBrowsePanel";
import type { JournalRecordRow, OperationsClient } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const here = dirname(fileURLToPath(import.meta.url));
const EMPTY_TEXT = "No journal records for this filter.";
const LOADING_TEXT = "Loading journal…";

function record(over: Partial<JournalRecordRow> = {}): JournalRecordRow {
  return {
    ts: 1_700_000_000,
    kind: "tick",
    venue: "kraken",
    pack: "sma_cross",
    bar_ts: 1_700_000_000,
    detail: { pair: "SUIUSD", reason: "no_signal" },
    ...over,
  };
}

function makeClient(
  over: Partial<Pick<OperationsClient, "listJournal">> = {},
): OperationsClient {
  return {
    getOperations: vi.fn(),
    promote: vi.fn(),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    engageKill: vi.fn(),
    releaseKill: vi.fn(),
    ackAlert: vi.fn(),
    ...over,
  };
}

describe("JournalBrowsePanel", () => {
  it("shows loading while the first list request is in flight", async () => {
    let release: ((rows: JournalRecordRow[]) => void) | undefined;
    const client = makeClient({
      listJournal: vi.fn().mockImplementation(
        () =>
          new Promise<JournalRecordRow[]>((resolvePromise) => {
            release = resolvePromise;
          }),
      ),
    });
    render(<JournalBrowsePanel client={client} />);
    expect(screen.getByTestId("ops-journal-loading").textContent).toBe(LOADING_TEXT);
    expect((screen.getByTestId("ops-journal-refresh") as HTMLButtonElement).disabled).toBe(true);
    release?.([]);
    await waitFor(() => expect(screen.queryByTestId("ops-journal-loading")).toBeNull());
  });

  it("says plainly when the filter yields no records", async () => {
    const client = makeClient({
      listJournal: vi.fn().mockResolvedValue([]),
    });
    render(<JournalBrowsePanel client={client} />);
    expect(await screen.findByTestId("ops-journal-empty").then((n) => n.textContent)).toBe(
      EMPTY_TEXT,
    );
  });

  it("lists time, kind, venue, pack, and detail for each record (newest first)", async () => {
    const client = makeClient({
      listJournal: vi.fn().mockResolvedValue([
        record({ ts: 1_700_000_000, kind: "tick", pack: "older" }),
        record({
          ts: 1_700_000_100,
          kind: "supervision",
          pack: "-",
          detail: { event: "wake_gap" },
        }),
      ]),
    });
    render(<JournalBrowsePanel client={client} />);
    const first = await screen.findByTestId("ops-journal-row-0");
    expect(first.textContent).toContain("supervision");
    expect(first.textContent).toContain("wake_gap");
    const second = screen.getByTestId("ops-journal-row-1");
    expect(second.textContent).toContain("tick");
    expect(second.textContent).toContain("older");
  });

  it("requests CLI-parity filters when the Show control changes", async () => {
    const listJournal = vi.fn().mockResolvedValue([]);
    const client = makeClient({ listJournal });
    render(<JournalBrowsePanel client={client} />);
    await screen.findByTestId("ops-journal-empty");
    expect(listJournal).toHaveBeenLastCalledWith({ tail: 5 });

    fireEvent.change(screen.getByTestId("ops-journal-filter"), { target: { value: "since-24h" } });
    await waitFor(() => expect(listJournal).toHaveBeenLastCalledWith({ since: "24h" }));

    fireEvent.change(screen.getByTestId("ops-journal-filter"), { target: { value: "tail-20" } });
    await waitFor(() => expect(listJournal).toHaveBeenLastCalledWith({ tail: 20 }));

    fireEvent.change(screen.getByTestId("ops-journal-filter"), { target: { value: "since-14d" } });
    await waitFor(() => expect(listJournal).toHaveBeenLastCalledWith({ since: "14d" }));
  });

  it("requests mode=paper|live when the Mode control changes", async () => {
    const listJournal = vi.fn().mockResolvedValue([]);
    const client = makeClient({ listJournal });
    render(<JournalBrowsePanel client={client} />);
    await screen.findByTestId("ops-journal-empty");
    expect(listJournal).toHaveBeenLastCalledWith({ tail: 5 });

    fireEvent.change(screen.getByTestId("ops-journal-mode"), { target: { value: "live" } });
    await waitFor(() => expect(listJournal).toHaveBeenLastCalledWith({ tail: 5, mode: "live" }));

    fireEvent.change(screen.getByTestId("ops-journal-mode"), { target: { value: "paper" } });
    await waitFor(() => expect(listJournal).toHaveBeenLastCalledWith({ tail: 5, mode: "paper" }));

    fireEvent.change(screen.getByTestId("ops-journal-mode"), { target: { value: "all" } });
    await waitFor(() => expect(listJournal).toHaveBeenLastCalledWith({ tail: 5 }));
  });

  it("renders readable live refuse and fill rows with a Mode column", async () => {
    const client = makeClient({
      listJournal: vi.fn().mockResolvedValue([
        record({
          ts: 1_700_000_000,
          mode: "live",
          summary: "live refused: paper_only_release (SUIUSD)",
          detail: {
            pair: "SUIUSD",
            reason: "live_refused",
            code: "paper_only_release",
          },
        }),
        record({
          ts: 1_700_000_100,
          mode: "live",
          summary: "kraken SUIUSD sma_cross (live): bought 1, protective stop resting",
          detail: {
            pair: "SUIUSD",
            mode: "live",
            reason: "entry",
            entry_qty: "1",
            exit_qty: "0",
            stop_qty: "0",
          },
        }),
      ]),
    });
    render(<JournalBrowsePanel client={client} />);
    const first = await screen.findByTestId("ops-journal-row-0");
    expect(first.textContent).toContain("bought 1");
    expect(screen.getByTestId("ops-journal-mode-cell-0").textContent).toBe("live");
    const second = screen.getByTestId("ops-journal-row-1");
    expect(second.textContent).toContain("live refused: paper_only_release");
    expect(second.textContent).not.toContain('"reason":"live_refused"');
  });

  it("surfaces a load failure with retry that reloads the list", async () => {
    const listJournal = vi
      .fn()
      .mockRejectedValueOnce(new Error("503"))
      .mockResolvedValueOnce([record()]);
    const client = makeClient({ listJournal });
    render(<JournalBrowsePanel client={client} />);
    expect(await screen.findByTestId("ops-journal-error").then((n) => n.textContent)).toContain(
      "503",
    );
    fireEvent.click(screen.getByTestId("ops-journal-retry"));
    expect(await screen.findByTestId("ops-journal-row-0").then((n) => n.textContent)).toContain(
      "tick",
    );
  });

  it("imports the Signal stylesheet from JournalBrowsePanel.tsx", () => {
    const source = readFileSync(resolve(here, "JournalBrowsePanel.tsx"), "utf8");
    expect(source).toMatch(/import\s+"\.\/JournalBrowsePanel\.signal\.css"/);
  });
});
