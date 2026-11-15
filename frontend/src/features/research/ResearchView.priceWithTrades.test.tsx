import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResearchView, type ResearchClient, type StoredResult } from "./ResearchView";
import {
  readPriceSeries,
  readTradeMarkers,
} from "./PriceWithTradesChart";

afterEach(cleanup);

/**
 * M4.2 — Research price chart with trade markers from result/trace.
 *
 * Transport note: every client here is an in-memory vi.fn() fake standing
 * in for the loopback research API. No real venue/engine lifecycle is
 * exercised or implied by these tests.
 */
function makeClient(overrides: Partial<ResearchClient> = {}): ResearchClient {
  const defaultResponse = {
    ok: true,
    status: 200,
    blob: vi.fn().mockResolvedValue(new Blob(['{"ok":true}'])),
  } as unknown as Response;
  return {
    submitRun: vi.fn().mockResolvedValue({ id: "job-price" }),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    getResult: vi.fn().mockResolvedValue(null),
    getJob: vi.fn().mockResolvedValue({ id: "job-price", state: "succeeded" }),
    getResultDownload: vi.fn().mockResolvedValue(defaultResponse),
    ...overrides,
  };
}

/** Production-shaped fixture: closes + entry/exit target reasons. */
const fixtureTrace = [
  {
    bar_ts: 1000,
    input: { ts_ms: 1000, open: 10, high: 11, low: 9.5, close: 10.5, volume: 1 },
    target: { long: false, stop_price: null, reason: "flat" },
    conditions: [],
  },
  {
    bar_ts: 2000,
    input: { ts_ms: 2000, open: 10.5, high: 12, low: 10.4, close: 11.8, volume: 1 },
    target: { long: true, stop_price: 10.6, reason: "entry" },
    conditions: [],
  },
  {
    bar_ts: 3000,
    input: { ts_ms: 3000, open: 11.8, high: 12.2, low: 11.5, close: 12.0, volume: 1 },
    target: { long: true, stop_price: 10.6, reason: "entry" },
    conditions: [],
  },
  {
    bar_ts: 4000,
    input: { ts_ms: 4000, open: 12.0, high: 12.1, low: 11.0, close: 11.2, volume: 1 },
    target: { long: false, stop_price: null, reason: "exit" },
    conditions: [],
  },
];

const fixtureStored: StoredResult = {
  legacy_receipt: {
    engine_version: "0.9.5",
    fee_bps: 10,
    metrics: {
      total_return_pct: 4.2,
      trade_count: 2,
      max_drawdown_pct: -1.5,
    },
    equity_curve: [0, 1, 2, 4.2],
  },
  trace: fixtureTrace,
};

function fillForm(): void {
  fireEvent.change(screen.getByLabelText(/dataset path/i), {
    target: { value: "fixtures/synthetic.csv" },
  });
  fireEvent.change(screen.getByLabelText(/fee basis points/i), {
    target: { value: "10" },
  });
  fireEvent.change(screen.getByLabelText(/^from$/i), {
    target: { value: "0" },
  });
  fireEvent.change(screen.getByLabelText(/^to$/i), {
    target: { value: "1000" },
  });
}

async function loadResult(stored: StoredResult): Promise<void> {
  const client = makeClient({
    getResult: vi.fn().mockResolvedValue(stored),
  });
  render(<ResearchView client={client} />);
  fillForm();
  fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
  await screen.findByTestId("research-job-id");
  fireEvent.click(screen.getByRole("button", { name: /load result/i }));
  await screen.findByTestId("research-result");
}

describe("ResearchView price with trades (fixture result/trace)", () => {
  it("renders a price chart with trade markers from trace target reasons", async () => {
    await loadResult(fixtureStored);

    const panel = screen.getByTestId("research-price-with-trades");
    expect(panel).toBeDefined();
    expect(panel.textContent ?? "").toContain(
      "trace.input.close · markers from trace.target / receipt.trades",
    );

    const svg = screen.getByTestId("research-price-with-trades-svg");
    expect(svg.tagName).toBe("svg");
    expect(svg.getAttribute("role")).toBe("img");

    const line = screen.getByTestId("research-price-with-trades-line");
    expect(line.tagName).toBe("polyline");
    const points = line.getAttribute("points") ?? "";
    expect(points.split(" ").filter(Boolean).length).toBe(fixtureTrace.length);

    const buys = screen.getAllByTestId("research-price-trade-marker-buy");
    const sells = screen.getAllByTestId("research-price-trade-marker-sell");
    expect(buys.length).toBe(2);
    expect(sells.length).toBe(1);
    expect(buys[0].getAttribute("data-bar-ts")).toBe("2000");
    expect(sells[0].getAttribute("data-bar-ts")).toBe("4000");
  });

  it("keeps the chart unavailable when the trace has no readable closes", async () => {
    await loadResult({
      legacy_receipt: { fee_bps: 10, trades: [{ side: "buy" }] },
      trace: [],
    });

    expect(
      screen.getByTestId("research-price-with-trades-unavailable").textContent,
    ).toBe("unavailable");
    expect(screen.queryByTestId("research-price-with-trades-svg")).toBeNull();
  });

  it("places receipt.trades markers only when bar_ts matches a trace bar", () => {
    const trace = [
      {
        bar_ts: 1000,
        input: { close: 1.5 },
        target: { reason: "flat" },
      },
      {
        bar_ts: 2000,
        input: { close: 1.8 },
        target: { reason: "flat" },
      },
    ];
    const receipt = {
      trades: [
        { side: "buy", bar_ts: 2000 },
        { side: "sell" }, // no timestamp — ignored
        { side: "sell", bar_ts: 9999 }, // no matching bar — ignored
      ],
    };
    expect(readPriceSeries(trace)?.map((point) => point.close)).toEqual([
      1.5, 1.8,
    ]);
    expect(readTradeMarkers(receipt, trace)).toEqual([
      {
        barTs: 2000,
        close: 1.8,
        side: "buy",
        index: 1,
        source: "receipt.trades",
      },
    ]);
  });

  it("refuses non-finite or wrong-shape price series values", () => {
    expect(readPriceSeries([])).toBeNull();
    expect(
      readPriceSeries([{ bar_ts: 1, input: { close: Number.NaN } }]),
    ).toBeNull();
    expect(readPriceSeries([{ bar_ts: 1, input: {} }])).toBeNull();
    expect(
      readPriceSeries([
        { bar_ts: 1, input: { close: 1 } },
        { bar_ts: 2, input: { close: 2 } },
      ]),
    ).toEqual([
      { barTs: 1, close: 1, index: 0 },
      { barTs: 2, close: 2, index: 1 },
    ]);
  });
});
