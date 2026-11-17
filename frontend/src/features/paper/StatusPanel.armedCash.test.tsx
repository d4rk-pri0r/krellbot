/**
 * StatusPanel — paper status honesty after arm (M2.9).
 *
 * Pins: just-armed free cash is not shown as 0; multi-deploy clarity
 * when armed_count > 1.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatusPanel } from "./StatusPanel";
import type { PaperClient, PaperPosition, PaperStatus } from "./client";
import type { RehearsalClient, RehearsalStatus } from "./rehearsalClient";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function armedStatus(extra: Partial<PaperStatus> = {}): PaperStatus {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    entries_paused: false,
    mode: "paper",
    pack_id: "trend-follow",
    armed_count: 1,
    ...extra,
  };
}

function filledPosition(extra: Partial<PaperPosition> = {}): PaperPosition {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    mode: "paper",
    free_cash: "2500",
    holdings: [],
    as_of_run: null,
    armed_count: 1,
    ...extra,
  };
}

function rehearsalIdle(): RehearsalClient {
  const idle: RehearsalStatus = {
    schema_version: "1",
    label: "SYNTHETIC PAPER REHEARSAL — simulated fixture, not market data",
    status: "idle",
    cursor: 0,
    total_bars: 20,
    balances: { USD: "1000" },
    position: "0",
    resting_stop: null,
    recent_fills: [],
  };
  return {
    getStatus: vi.fn().mockResolvedValue(idle),
    start: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    exit: vi.fn(),
    stop: vi.fn(),
  } as RehearsalClient;
}

function makeClient(overrides: Partial<PaperClient> = {}): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue(armedStatus()),
    getPosition: vi.fn().mockResolvedValue(filledPosition()),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    createRehearsalClient: () => rehearsalIdle(),
    ...overrides,
  };
}

describe("StatusPanel just-armed free cash honesty", () => {
  it("renders configured free cash after arm when as_of_run is still null", async () => {
    render(
      <StatusPanel
        client={makeClient({
          getStatus: vi.fn().mockResolvedValue(armedStatus()),
          getPosition: vi.fn().mockResolvedValue(
            filledPosition({ free_cash: "2500", as_of_run: null }),
          ),
        })}
      />,
    );

    const sentence = await screen.findByTestId("paper-position");
    expect(sentence.textContent).toBe(
      "Owned position: no open position — free cash 2500 USD",
    );
    expect(sentence.textContent).not.toContain("free cash 0");
  });

  it("labels Binance BTCUSDT free cash as USDT, not SDT", async () => {
    render(
      <StatusPanel
        client={makeClient({
          getStatus: vi.fn().mockResolvedValue(
            armedStatus({ venue: "binance", pair: "BTCUSDT", pack_id: "binance-btc" }),
          ),
          getPosition: vi.fn().mockResolvedValue(
            filledPosition({
              venue: "binance",
              pair: "BTCUSDT",
              free_cash: "900.0",
              holdings: [{ symbol: "BTC", qty: "0.01" }],
              as_of_run: "binance:binance-btc:BTCUSDT",
            }),
          ),
        })}
      />,
    );

    const sentence = await screen.findByTestId("paper-position");
    expect(sentence.textContent).toBe(
      "Owned position: 0.01 BTC — free cash 900.0 USDT",
    );
    expect(sentence.textContent).not.toContain(" SDT");
  });
});

describe("StatusPanel multi-deploy clarity", () => {
  it("names that the panel shows one of several armed deployments", async () => {
    render(
      <StatusPanel
        client={makeClient({
          getStatus: vi
            .fn()
            .mockResolvedValue(armedStatus({ armed_count: 2 })),
          getPosition: vi
            .fn()
            .mockResolvedValue(filledPosition({ armed_count: 2 })),
        })}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("paper-status-multi-deploy").textContent).toBe(
        "Showing 1 of 2 armed deployments — see Armed paper runs for the full list.",
      );
    });
  });

  it("omits the multi-deploy note when only one pack is armed", async () => {
    render(<StatusPanel client={makeClient()} />);
    await screen.findByTestId("paper-position");
    expect(screen.queryByTestId("paper-status-multi-deploy")).toBeNull();
  });
});
