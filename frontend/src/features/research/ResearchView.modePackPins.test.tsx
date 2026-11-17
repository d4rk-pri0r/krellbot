/**
 * M15.6 — Research mode-pack pins: metrics render; copy distinguishes
 * backtest/fixture from live. Transport is an in-memory fake.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ResearchView,
  type ResearchClient,
  type StoredResult,
} from "./ResearchView";

afterEach(cleanup);

function makeClient(overrides: Partial<ResearchClient> = {}): ResearchClient {
  const defaultResponse = {
    ok: true,
    status: 200,
    blob: vi.fn().mockResolvedValue(new Blob(['{"ok":true}'])),
  } as unknown as Response;
  return {
    submitRun: vi.fn().mockResolvedValue({ id: "job-mode-pin" }),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    getResult: vi.fn().mockResolvedValue(null),
    getJob: vi.fn().mockResolvedValue({ id: "job-mode-pin", state: "succeeded" }),
    getResultDownload: vi.fn().mockResolvedValue(defaultResponse),
    ...overrides,
  };
}

const modePackReceipt = {
  engine_version: "0.9.7",
  pack_sha256: "a".repeat(64),
  data_manifest_sha256: "pinned-fixture-sha",
  venue: "kraken",
  pair: "SUIUSD",
  tf: "1h",
  fee_bps: 40,
  metrics: {
    total_return_pct: 1.5,
    max_drawdown_pct: -0.8,
    trade_count: 2,
  },
  equity_curve: [0, 0.5, 1.5],
  trades: [{ side: "buy" }, { side: "sell" }],
};

const modePackStored: StoredResult = {
  legacy_receipt: modePackReceipt,
  trace: [
    { ts_ms: 0, close: 100, reason: "flat" },
    { ts_ms: 3600000, close: 101, reason: "entry" },
  ],
};

async function loadModePackResult(): Promise<void> {
  const client = makeClient({
    getResult: vi.fn().mockResolvedValue(modePackStored),
  });
  render(<ResearchView client={client} />);
  fireEvent.change(screen.getByLabelText(/pack path/i), {
    target: { value: "mode-grid.json" },
  });
  fireEvent.change(screen.getByLabelText(/dataset path/i), {
    target: { value: "fixtures/mode_research_pin_1h.csv" },
  });
  fireEvent.change(screen.getByLabelText(/fee basis points/i), {
    target: { value: "40" },
  });
  fireEvent.change(screen.getByLabelText(/^from$/i), {
    target: { value: "0" },
  });
  fireEvent.change(screen.getByLabelText(/^to$/i), {
    target: { value: "100000000" },
  });
  fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
  await screen.findByTestId("research-job-id");
  fireEvent.click(screen.getByRole("button", { name: /load result/i }));
  await screen.findByTestId("research-result");
}

describe("ResearchView mode pack pinned-fixture honesty (M15.6)", () => {
  it("intro copy distinguishes backtest/fixture from live", () => {
    render(<ResearchView client={makeClient()} />);
    const intro = screen.getByRole("region", { name: /research/i }).textContent ?? "";
    expect(intro.toLowerCase()).toContain("backtest");
    expect(intro.toLowerCase()).toContain("not market performance");
    expect(intro.toLowerCase()).toContain("live trading result");
  });

  it("renders mode-pack receipt metrics with honesty banner", async () => {
    await loadModePackResult();
    const honesty = screen.getByTestId("research-result-honesty");
    expect(honesty.textContent ?? "").toMatch(/backtest/i);
    expect(honesty.textContent ?? "").toMatch(/pinned fixture/i);
    expect((honesty.textContent ?? "").toLowerCase()).toContain(
      "not live market performance",
    );
    expect(screen.getByTestId("research-result").textContent ?? "").toMatch(
      /1\.5|2|equity/i,
    );
    expect(screen.getByTestId("research-equity-curve")).toBeDefined();
  });
});
