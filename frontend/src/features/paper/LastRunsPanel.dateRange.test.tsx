// Pin the zone so the local-time assertions for the fills table are
// deterministic regardless of the host running the suite (same approach
// as LastRunsPanel.signal.test.tsx).
process.env.TZ = "UTC";

/**
 * LastRunsPanel — out-of-Date-range timestamp fault containment (issue291).
 *
 * A finite-but-out-of-`Date`-range epoch-millis value on the paper-history
 * wire used to make `formatTime` throw `RangeError: Invalid time value`
 * during the row render, crashing the ENTIRE runs table and hiding the
 * neighboring healthy runs. These tests reproduce that fault through the
 * REAL production adapter path — `createHttpClient().listRuns()` against
 * stubbed standard JSON HTTP responses, exactly the shapes
 * `/api/v1/paper/history` serves — plus the mounted LastRunsPanel in
 * React/JSDOM.
 *
 * Coordinator contract under test:
 *
 *  - formatting any run first_ts_ms/last_ts_ms never throws, whatever the
 *    wire put in the field: positive/negative out-of-range finite values,
 *    NaN/Infinity (injected typed controls — JSON cannot carry them past
 *    the adapter's finite check), missing and zero;
 *  - an unavailable/invalid timestamp renders the panel's existing em dash
 *    "—", never a fabricated epoch/current date, and the invalid row keeps
 *    its actual identity/summary/status — records are not dropped;
 *  - healthy finite timestamps keep rendering their exact UTC `toISOString`
 *    bytes, including the Date valid boundaries ±8,640,000,000,000,000 ms;
 *  - the fills table's separate local-time path is unchanged;
 *  - row detail, filters and refresh stay usable with invalid rows present.
 *
 * Transport note: the HTTP adapter is real, but every response here is a
 * synthetic fixture standing in for the loopback paper API. No real
 * venue/engine state, keys, orders or fills are exercised or implied.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LastRunsPanel } from "./LastRunsPanel";
import { createHttpClient } from "./client";
import type { PaperClient, PaperHistory, PaperRunsClient } from "./client";

const EMDASH = "—";
const HEALTHY_MS = 1_730_000_000_000;
const HEALTHY_ISO = "2024-10-27T03:33:20.000Z";
const OVER_RANGE = 10_000_000_000_000_000;
const MAX_DATE_MS = 8_640_000_000_000_000;
const MAX_DATE_ISO = "+275760-09-13T00:00:00.000Z";
const MIN_DATE_MS = -8_640_000_000_000_000;
const MIN_DATE_ISO = "-271821-04-20T00:00:00.000Z";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** Standard JSON HTTP response envelope, same shape client.test.ts stubs. */
function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

type WireRun = Record<string, unknown>;

function wireRun(overrides: WireRun = {}): WireRun {
  return {
    venue: "kraken",
    pair: "SUIUSD",
    pack_id: "trend-follow",
    first_ts_ms: HEALTHY_MS,
    last_ts_ms: HEALTHY_MS + 1,
    ticks_total: 4,
    last_refusal_code: null,
    mode: "paper",
    status: "closed",
    summary: "4 ticks, 0 fills, no refusal, closed",
    recent_fills: [],
    ...overrides,
  };
}

/** Mixed history as the loopback API would serve it: healthy rows beside
 *  rows whose first/last stamp is independently out of range, missing or
 *  zero, and rows sitting exactly on the Date valid boundaries. */
function mixedWireHistory(): Record<string, unknown> {
  return {
    schema_version: "1",
    runs: [
      wireRun({
        pair: "BADFST",
        first_ts_ms: OVER_RANGE,
        last_ts_ms: 1_730_000_000_123,
        status: "closed",
        summary: "bad first stamp, healthy last, closed",
      }),
      wireRun({
        pair: "BADLST",
        first_ts_ms: 1_730_000_000_456,
        last_ts_ms: -OVER_RANGE,
        status: "failed",
        summary: "healthy first stamp, bad last, failed",
      }),
      wireRun({
        pair: "NGBDY",
        first_ts_ms: HEALTHY_MS,
        last_ts_ms: 1_730_000_009_999,
        status: "closed",
        summary: "healthy neighbor run, closed",
      }),
      wireRun({
        pair: "ZEROS",
        first_ts_ms: 0,
        last_ts_ms: 0,
        status: "closed",
        summary: "zero stamps, closed",
      }),
      wireRun({
        pair: "MISSING",
        first_ts_ms: undefined,
        last_ts_ms: undefined,
        status: "closed",
        summary: "stamps missing entirely, closed",
      }),
      wireRun({
        pair: "MAXEDG",
        first_ts_ms: MAX_DATE_MS,
        last_ts_ms: MAX_DATE_MS,
        status: "closed",
        summary: "max valid Date boundary, closed",
      }),
      wireRun({
        pair: "MINEDG",
        first_ts_ms: MIN_DATE_MS,
        last_ts_ms: MIN_DATE_MS,
        status: "closed",
        summary: "min valid Date boundary, closed",
      }),
      wireRun({
        pair: "OVEREDG",
        first_ts_ms: MAX_DATE_MS + 1,
        last_ts_ms: MIN_DATE_MS - 1,
        status: "closed",
        summary: "one past both Date boundaries, closed",
      }),
    ],
  };
}

function httpPanelClient(history: Record<string, unknown> = mixedWireHistory()): {
  client: PaperClient & PaperRunsClient;
  fetchMock: ReturnType<typeof vi.fn>;
} {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse(history));
  vi.stubGlobal("fetch", fetchMock);
  return { client: createHttpClient(), fetchMock };
}

function startedCell(rowTestId: string): string {
  const row = screen.getByTestId(rowTestId) as HTMLTableRowElement;
  return row.cells[2].textContent ?? "";
}

function endedCell(rowTestId: string): string {
  const row = screen.getByTestId(rowTestId) as HTMLTableRowElement;
  return row.cells[3].textContent ?? "";
}

describe("LastRunsPanel — out-of-Date-range timestamp containment", () => {
  it("renders the whole mixed history through the real HTTP adapter instead of crashing on out-of-range stamps", async () => {
    const { client } = httpPanelClient();
    render(<LastRunsPanel client={client} />);

    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
    });

    // The invalid rows survive with the existing em dash, never a
    // fabricated epoch or today's date.
    expect(startedCell("paper-last-runs-row-kraken-BADFST")).toBe(EMDASH);
    expect(endedCell("paper-last-runs-row-kraken-BADFST")).toBe(
      "2024-10-27T03:33:20.123Z",
    );
    expect(startedCell("paper-last-runs-row-kraken-BADLST")).toBe(
      "2024-10-27T03:33:20.456Z",
    );
    expect(endedCell("paper-last-runs-row-kraken-BADLST")).toBe(EMDASH);
    expect(startedCell("paper-last-runs-row-kraken-OVEREDG")).toBe(EMDASH);
    expect(endedCell("paper-last-runs-row-kraken-OVEREDG")).toBe(EMDASH);
    expect(startedCell("paper-last-runs-row-kraken-ZEROS")).toBe(EMDASH);
    expect(endedCell("paper-last-runs-row-kraken-ZEROS")).toBe(EMDASH);
    expect(startedCell("paper-last-runs-row-kraken-MISSING")).toBe(EMDASH);
    expect(endedCell("paper-last-runs-row-kraken-MISSING")).toBe(EMDASH);

    // Healthy neighbors keep their exact UTC toISOString bytes and stay
    // visible next to the faulting rows.
    expect(startedCell("paper-last-runs-row-kraken-NGBDY")).toBe(HEALTHY_ISO);
    expect(endedCell("paper-last-runs-row-kraken-NGBDY")).toBe(
      "2024-10-27T03:33:29.999Z",
    );
    expect(screen.getByText("healthy neighbor run, closed")).toBeDefined();

    // Date valid boundaries stay valid: byte-equivalent UTC rendering,
    // not em dashes.
    expect(startedCell("paper-last-runs-row-kraken-MAXEDG")).toBe(MAX_DATE_ISO);
    expect(endedCell("paper-last-runs-row-kraken-MAXEDG")).toBe(MAX_DATE_ISO);
    expect(startedCell("paper-last-runs-row-kraken-MINEDG")).toBe(MIN_DATE_ISO);
    expect(endedCell("paper-last-runs-row-kraken-MINEDG")).toBe(MIN_DATE_ISO);

    // Every record is still counted and rendered: nothing was dropped to
    // contain the fault.
    expect(screen.getByTestId("paper-last-runs-count").textContent).toBe("8 runs");
  });

  it("keeps the invalid rows' actual identity, status and summary", async () => {
    const { client } = httpPanelClient();
    render(<LastRunsPanel client={client} />);

    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
    });

    expect(
      screen.getByTestId("paper-last-runs-status-kraken-BADFST").textContent,
    ).toBe("closed");
    expect(
      screen.getByTestId("paper-last-runs-status-kraken-BADLST").textContent,
    ).toBe("failed");
    expect(screen.getByText("bad first stamp, healthy last, closed")).toBeDefined();
    expect(screen.getByText("healthy first stamp, bad last, failed")).toBeDefined();
    expect(screen.getByText("one past both Date boundaries, closed")).toBeDefined();
    expect(
      screen.getByTestId("paper-last-runs-fills-kraken-BADLST").textContent,
    ).toBe("0");
  });

  it("contains NaN/Infinity stamps injected through a typed client control", async () => {
    // JSON cannot carry NaN/Infinity past the adapter's finite check, so
    // these travel through the typed PaperRun shape the panel accepts.
    const history: PaperHistory = {
      schema_version: "1",
      runs: [
        {
          venue: "kraken",
          pair: "NANFST",
          pack_id: "trend-follow",
          first_ts_ms: Number.NaN,
          last_ts_ms: HEALTHY_MS,
          ticks_total: 1,
          last_refusal_code: null,
          mode: "paper",
          status: "closed",
          summary: "NaN first stamp, closed",
          recent_fills: [],
        },
        {
          venue: "kraken",
          pair: "INFLST",
          pack_id: "trend-follow",
          first_ts_ms: HEALTHY_MS,
          last_ts_ms: Number.POSITIVE_INFINITY,
          ticks_total: 1,
          last_refusal_code: null,
          mode: "paper",
          status: "closed",
          summary: "infinite last stamp, closed",
          recent_fills: [],
        },
        {
          venue: "kraken",
          pair: "NEGINF",
          pack_id: "trend-follow",
          first_ts_ms: Number.NEGATIVE_INFINITY,
          last_ts_ms: Number.NaN,
          ticks_total: 1,
          last_refusal_code: null,
          mode: "paper",
          status: "closed",
          summary: "negative infinite first, NaN last, closed",
          recent_fills: [],
        },
      ],
    };
    const client = {
      getStatus: vi.fn(),
      pauseEntries: vi.fn(),
      resumeEntries: vi.fn(),
      disarm: vi.fn(),
      listRuns: vi.fn().mockResolvedValue(history),
    } as unknown as PaperClient & PaperRunsClient;
    render(<LastRunsPanel client={client} />);

    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
    });

    expect(startedCell("paper-last-runs-row-kraken-NANFST")).toBe(EMDASH);
    expect(endedCell("paper-last-runs-row-kraken-NANFST")).toBe(HEALTHY_ISO);
    expect(startedCell("paper-last-runs-row-kraken-INFLST")).toBe(HEALTHY_ISO);
    expect(endedCell("paper-last-runs-row-kraken-INFLST")).toBe(EMDASH);
    expect(startedCell("paper-last-runs-row-kraken-NEGINF")).toBe(EMDASH);
    expect(endedCell("paper-last-runs-row-kraken-NEGINF")).toBe(EMDASH);
    expect(screen.getByTestId("paper-last-runs-count").textContent).toBe("3 runs");
  });

  it("keeps detail, fills local time, filters and refresh usable with invalid rows present", async () => {
    const history = mixedWireHistory();
    // The faulting row carries one healthy fill so its detail exercises
    // the unchanged local-time fills path beside the contained stamps.
    (history.runs as WireRun[])[0] = wireRun({
      pair: "BADFST",
      first_ts_ms: OVER_RANGE,
      last_ts_ms: 1_730_000_000_123,
      summary: "bad first stamp, healthy last, closed",
      recent_fills: [{ coid: "coid-fault-row", side: "buy", ts_ms: 1_730_000_045_000 }],
    });
    const { client, fetchMock } = httpPanelClient(history);
    fetchMock.mockResolvedValue(jsonResponse(history));
    render(<LastRunsPanel client={client} />);

    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
    });

    // Detail opens for the faulting row and keeps its actual summary.
    fireEvent.click(screen.getByTestId("paper-last-runs-row-kraken-BADFST"));
    expect(screen.getByTestId("paper-last-runs-detail")).toBeDefined();
    expect(screen.getByTestId("paper-last-runs-detail-summary").textContent).toBe(
      "bad first stamp, healthy last, closed",
    );
    // Fills keep rendering in the viewer's local time (TZ pinned to UTC),
    // on the unchanged fills path.
    expect(
      within(screen.getByTestId("paper-last-runs-fills-table")).getByText(
        "2024-10-27T03:34:05",
      ),
    ).toBeDefined();
    fireEvent.click(screen.getByTestId("paper-last-runs-detail-close"));
    expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();

    // Filters still narrow the mixed table.
    fireEvent.change(screen.getByTestId("paper-last-runs-filter-query"), {
      target: { value: "NGBDY" },
    });
    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-row-kraken-NGBDY")).toBeDefined();
    });
    expect(screen.queryByTestId("paper-last-runs-row-kraken-BADFST")).toBeNull();
    fireEvent.click(screen.getByTestId("paper-last-runs-filter-clear"));

    // Refresh re-reads the wire and re-renders the same mixed history,
    // still without throwing.
    fireEvent.click(screen.getByTestId("paper-last-runs-refresh"));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(startedCell("paper-last-runs-row-kraken-BADFST")).toBe(EMDASH);
    });
    expect(startedCell("paper-last-runs-row-kraken-NGBDY")).toBe(HEALTHY_ISO);
  });

  it("initial render through the HTTP adapter does not throw when the whole history is out of range", async () => {
    const history = {
      schema_version: "1",
      runs: [
        wireRun({ pair: "ALLBAD", first_ts_ms: OVER_RANGE, last_ts_ms: -OVER_RANGE }),
      ],
    };
    const { client } = httpPanelClient(history);
    render(<LastRunsPanel client={client} />);

    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
    });
    expect(startedCell("paper-last-runs-row-kraken-ALLBAD")).toBe(EMDASH);
    expect(endedCell("paper-last-runs-row-kraken-ALLBAD")).toBe(EMDASH);
  });

  it("refresh keeps a selected invalid row's detail reconciled by identity", async () => {
    const history = {
      schema_version: "1",
      runs: [
        wireRun({
          pair: "BADFST",
          first_ts_ms: OVER_RANGE,
          summary: "bad first stamp, healthy last, closed",
        }),
      ],
    };
    const { client, fetchMock } = httpPanelClient(history);
    fetchMock.mockResolvedValue(jsonResponse(history));
    render(<LastRunsPanel client={client} />);

    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
    });
    fireEvent.click(screen.getByTestId("paper-last-runs-row-kraken-BADFST"));
    expect(screen.getByTestId("paper-last-runs-detail")).toBeDefined();

    fireEvent.click(screen.getByTestId("paper-last-runs-refresh"));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
    // The same identity re-selects its fresh object: detail survives with
    // the actual summary, not a crash or a dropped selection.
    await waitFor(() => {
      expect(screen.getByTestId("paper-last-runs-detail")).toBeDefined();
    });
    expect(screen.getByTestId("paper-last-runs-detail-summary").textContent).toBe(
      "bad first stamp, healthy last, closed",
    );
  });
});
