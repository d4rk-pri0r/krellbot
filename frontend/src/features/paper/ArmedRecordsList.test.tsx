import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ArmedRecordsList } from "./ArmedRecordsList";
import type {
  PaperArmedClient,
  PaperArmedRecord,
  PaperArmedView,
} from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function viewOf(records: PaperArmedRecord[]): PaperArmedView {
  return {
    schema_version: "1",
    armed: records.length > 0,
    records,
  };
}

function record(extra: Partial<PaperArmedRecord> = {}): PaperArmedRecord {
  return {
    venue: "kraken",
    pair: "SUIUSD",
    mode: "paper",
    pack_id: "trend-follow",
    entries_paused: false,
    ...extra,
  };
}

function makeClient(
  listArmed: PaperArmedClient["listArmed"],
): PaperArmedClient {
  return { listArmed };
}

describe("ArmedRecordsList loading / empty / rows", () => {
  it("renders the truthful loading state before listArmed resolves", () => {
    const client = makeClient(
      vi.fn(() => new Promise<PaperArmedView>(() => undefined)),
    );
    render(<ArmedRecordsList client={client} />);
    expect(screen.getByTestId("paper-armed-loading")).toBeDefined();
    // No empty-list claim while the list is unknown.
    expect(screen.queryByTestId("paper-armed-empty")).toBeNull();
    expect(screen.queryAllByTestId("paper-armed-row")).toHaveLength(0);
  });

  it("renders 'No packs armed' after a confirmed armed=false body", async () => {
    const client = makeClient(vi.fn().mockResolvedValue(viewOf([])));
    render(<ArmedRecordsList client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-armed-empty")).toBeDefined();
    });
    expect(screen.getByTestId("paper-armed-empty").textContent).toMatch(
      /No packs armed/,
    );
    expect(screen.queryAllByTestId("paper-armed-row")).toHaveLength(0);
  });

  it("renders one row per armed record with venue, pair, mode, pack, entries", async () => {
    const client = makeClient(
      vi.fn().mockResolvedValue(
        viewOf([
          record(),
          record({
            venue: "coinbase",
            pair: "BTC-USD",
            pack_id: "mean-revert",
            entries_paused: true,
          }),
        ]),
      ),
    );
    render(<ArmedRecordsList client={client} />);
    const rows = await screen.findAllByTestId("paper-armed-row");
    expect(rows).toHaveLength(2);
    const [first, second] = rows;
    expect(first.textContent).toContain("kraken");
    expect(first.textContent).toContain("SUIUSD");
    expect(first.textContent).toContain("paper");
    expect(first.textContent).toContain("trend-follow");
    expect(first.textContent).toMatch(/Entries active/);
    expect(second.textContent).toContain("coinbase");
    expect(second.textContent).toMatch(/Entries paused/);
  });

  it("renders an unavailable state, not an empty claim, when listArmed rejects", async () => {
    const client = makeClient(
      vi.fn().mockRejectedValue(new Error("paper armed list failed: 403")),
    );
    render(<ArmedRecordsList client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-armed-unavailable")).toBeDefined();
    });
    expect(screen.queryByTestId("paper-armed-empty")).toBeNull();
    // The refusal code from the thrown error is surfaced truthfully.
    expect(screen.getByTestId("paper-armed-error").textContent).toMatch(/403/);
  });

  it("renders the unavailable state for a legacy client without listArmed", async () => {
    // The shell may mount the panel with a client that only implements
    // PaperClient; the panel must degrade honestly instead of crashing.
    const legacy = {} as unknown as PaperArmedClient;
    render(<ArmedRecordsList client={legacy} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-armed-unavailable")).toBeDefined();
    });
    expect(screen.queryByTestId("paper-armed-empty")).toBeNull();
  });
});

describe("ArmedRecordsList refresh", () => {
  it("refresh refetches and replaces the visible rows", async () => {
    const listArmed = vi
      .fn<PaperArmedClient["listArmed"]>()
      .mockResolvedValueOnce(viewOf([record()]))
      .mockResolvedValueOnce(
        viewOf([
          record(),
          record({
            venue: "coinbase",
            pair: "BTC-USD",
            pack_id: "mean-revert",
            entries_paused: true,
          }),
        ]),
      );
    render(<ArmedRecordsList client={makeClient(listArmed)} />);
    await waitFor(() => {
      expect(screen.getAllByTestId("paper-armed-row")).toHaveLength(1);
    });
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => {
      expect(screen.getAllByTestId("paper-armed-row")).toHaveLength(2);
    });
    expect(listArmed).toHaveBeenCalledTimes(2);
  });

  it("keeps the last good rows and surfaces the refusal when a refresh fails", async () => {
    const listArmed = vi
      .fn<PaperArmedClient["listArmed"]>()
      .mockResolvedValueOnce(viewOf([record()]))
      .mockRejectedValueOnce(new Error("paper armed list failed: 503"));
    render(<ArmedRecordsList client={makeClient(listArmed)} />);
    await waitFor(() => {
      expect(screen.getAllByTestId("paper-armed-row")).toHaveLength(1);
    });
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => {
      expect(listArmed).toHaveBeenCalledTimes(2);
    });
    // Rows stay visible (last known list) and the failure is named.
    expect(screen.getAllByTestId("paper-armed-row")).toHaveLength(1);
    expect(screen.getByTestId("paper-armed-refresh-error").textContent).toMatch(
      /503/,
    );
    expect(screen.queryByTestId("paper-armed-empty")).toBeNull();
  });

  it("disables the refresh button while a request is in flight", async () => {
    let release: ((value: PaperArmedView) => void) | null = null;
    const listArmed = vi.fn().mockImplementation(
      () =>
        new Promise<PaperArmedView>((resolve) => {
          release = resolve;
        }),
    );
    render(<ArmedRecordsList client={makeClient(listArmed)} />);
    // Initial load is pending: the button is disabled by the initial
    // in-flight guard.
    let refreshButton = screen.getByRole("button", { name: /refresh/i });
    expect((refreshButton as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(refreshButton);
    await waitFor(() => {
      expect(listArmed).toHaveBeenCalledTimes(2);
    });
    refreshButton = screen.getByRole("button", { name: /refresh/i });
    expect((refreshButton as HTMLButtonElement).disabled).toBe(true);
    expect(refreshButton.textContent).toMatch(/Refreshing/);

    await act(async () => {
      release?.(viewOf([]));
    });
    refreshButton = screen.getByRole("button", { name: /refresh/i });
    expect((refreshButton as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByTestId("paper-armed-empty").textContent).toMatch(
      /No packs armed/,
    );
  });
});

describe("ArmedRecordsList click-to-detail", () => {
  it("shows the same closed row data inline when a row is clicked", async () => {
    const client = makeClient(
      vi.fn().mockResolvedValue(viewOf([record({ entries_paused: true })])),
    );
    render(<ArmedRecordsList client={client} />);
    const row = await screen.findAllByTestId("paper-armed-row");
    expect(screen.queryByTestId("paper-armed-detail")).toBeNull();
    fireEvent.click(row[0]);
    const detail = await screen.findByTestId("paper-armed-detail");
    expect(detail.textContent).toContain("kraken");
    expect(detail.textContent).toContain("SUIUSD");
    expect(detail.textContent).toContain("paper");
    expect(detail.textContent).toContain("trend-follow");
    expect(detail.textContent).toMatch(/Entries paused/);
    // Detail shows only the closed field set.
    expect(Object.keys(detail.dataset ?? {})).toEqual(
      expect.arrayContaining([]),
    );
  });

  it("collapses the detail when the same row is clicked again", async () => {
    const client = makeClient(vi.fn().mockResolvedValue(viewOf([record()])));
    render(<ArmedRecordsList client={client} />);
    const row = await screen.findAllByTestId("paper-armed-row");
    fireEvent.click(row[0]);
    expect(await screen.findByTestId("paper-armed-detail")).toBeDefined();
    fireEvent.click(row[0]);
    await waitFor(() => {
      expect(screen.queryByTestId("paper-armed-detail")).toBeNull();
    });
  });

  it("drops the detail when a refresh removes the selected row", async () => {
    const listArmed = vi
      .fn<PaperArmedClient["listArmed"]>()
      .mockResolvedValueOnce(viewOf([record()]))
      .mockResolvedValueOnce(viewOf([]));
    render(<ArmedRecordsList client={makeClient(listArmed)} />);
    const row = await screen.findAllByTestId("paper-armed-row");
    fireEvent.click(row[0]);
    expect(await screen.findByTestId("paper-armed-detail")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => {
      expect(screen.getByTestId("paper-armed-empty")).toBeDefined();
    });
    expect(screen.queryByTestId("paper-armed-detail")).toBeNull();
  });
});
