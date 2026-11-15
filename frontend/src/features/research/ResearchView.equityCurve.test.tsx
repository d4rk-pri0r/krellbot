import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResearchView, type ResearchClient, type StoredResult } from "./ResearchView";
import { readEquityCurve } from "./EquityCurveChart";

afterEach(cleanup);

/**
 * M4.1 — Research equity curve from a fixture receipt.
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
    submitRun: vi.fn().mockResolvedValue({ id: "job-equity" }),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    getResult: vi.fn().mockResolvedValue(null),
    getJob: vi.fn().mockResolvedValue({ id: "job-equity", state: "succeeded" }),
    getResultDownload: vi.fn().mockResolvedValue(defaultResponse),
    ...overrides,
  };
}

/** Production-shaped fixture: typed percent series, no currency equity. */
const fixtureReceipt = {
  engine_version: "0.9.5",
  pack_sha256:
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  data_manifest_sha256: "feedface",
  venue: "kraken",
  pair: "SUIUSD",
  tf: "1h",
  from: "2026-01-01",
  to: "2026-01-02",
  fee_bps: 10,
  slippage_bps: 0,
  slippage_mult: 1.0,
  metrics: {
    total_return_pct: 12.5,
    cagr_pct: 9125.0,
    max_drawdown_pct: -4.25,
    return_to_dd: 2.94,
    per_year: { trades: 0, r: 0 },
    trade_count: 7,
    exposure_pct: 55.0,
  },
  equity_curve: [0, 1.2, 2.4, -0.5, 12.5],
};

const fixtureStored: StoredResult = {
  legacy_receipt: fixtureReceipt,
  trace: [],
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

describe("ResearchView equity curve (fixture receipt)", () => {
  it("renders an equity series chart from receipt.equity_curve", async () => {
    await loadResult(fixtureStored);

    const panel = screen.getByTestId("research-equity-curve");
    expect(panel).toBeDefined();
    expect(panel.textContent ?? "").toContain(
      "receipt.equity_curve · percent return series",
    );

    const svg = screen.getByTestId("research-equity-curve-svg");
    expect(svg.tagName).toBe("svg");
    expect(svg.getAttribute("role")).toBe("img");

    const line = screen.getByTestId("research-equity-curve-line");
    expect(line.tagName).toBe("polyline");
    const points = line.getAttribute("points") ?? "";
    expect(points.split(" ").filter(Boolean).length).toBe(
      fixtureReceipt.equity_curve.length,
    );

    // Currency equity cell stays unavailable — the curve is percent return.
    expect(screen.getByTestId("research-result-equity").textContent).toBe(
      "unavailable",
    );
  });

  it("keeps the chart unavailable when equity_curve is missing", async () => {
    await loadResult({
      legacy_receipt: { fee_bps: 10, metrics: { total_return_pct: 1 } },
      trace: [],
    });

    expect(
      screen.getByTestId("research-equity-curve-unavailable").textContent,
    ).toBe("unavailable");
    expect(screen.queryByTestId("research-equity-curve-svg")).toBeNull();
  });

  it("refuses non-finite or wrong-shape equity_curve values", () => {
    expect(readEquityCurve({ equity_curve: [0, Number.NaN, 1] })).toBeNull();
    expect(readEquityCurve({ equity_curve: "not-an-array" })).toBeNull();
    expect(readEquityCurve({ equity_curve: [] })).toBeNull();
    expect(readEquityCurve({ equity_curve: [0, 1.5, 2] })).toEqual([0, 1.5, 2]);
  });
});
