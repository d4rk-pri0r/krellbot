/**
 * M14.7: paper arm venue picker includes Binance-class `binance` for paper
 * paths. Live surfaces must not claim qualified Binance live.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatusPanel } from "./StatusPanel";
import type { PaperClient, PaperCommandResult, PaperStatus } from "./client";
import type { RehearsalClient, RehearsalCommandResult, RehearsalStatus } from "./rehearsalClient";
import { BINANCE_PAPER_WAVE_PAIR, VENUES } from "../strategies/ownedStrategy";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function unarmed(): PaperStatus {
  return { schema_version: "1", armed: false };
}

function armOk(venue: string, pair: string): PaperCommandResult {
  return {
    schema_version: "1",
    code: "armed",
    ok: true,
    message: `armed ${venue} ${pair}`,
    effect: "changed",
    revision_before: null,
    revision_after: null,
  };
}

function rehearsalStatus(): RehearsalStatus {
  return {
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
}

function makeClient(overrides: Partial<PaperClient> = {}): PaperClient {
  const rehearsal: RehearsalClient = {
    getStatus: vi.fn().mockResolvedValue(rehearsalStatus()),
    start: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "ok",
      ok: true,
      message: "ok",
      status: rehearsalStatus(),
    } satisfies RehearsalCommandResult),
    pause: vi.fn(),
    resume: vi.fn(),
    exit: vi.fn(),
    stop: vi.fn(),
  };
  return {
    getStatus: vi.fn().mockResolvedValue(unarmed()),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    listOwnedDrafts: vi.fn().mockResolvedValue([
      {
        schema_version: "1",
        strategy_id: "strat-1",
        revision_id: "rev-binance",
        parent_revision_id: null,
        state: "validated",
        runnable: true,
        created_at: "2026-10-08T00:00:00Z",
        id: "trend-follow",
        label: "Trend follow",
        pair: BINANCE_PAPER_WAVE_PAIR,
        timeframe: "1h",
      },
    ]),
    arm: vi.fn().mockResolvedValue(armOk("binance", BINANCE_PAPER_WAVE_PAIR)),
    createRehearsalClient: () => rehearsal,
    ...overrides,
  };
}

describe("paper venue picker includes binance", () => {
  it("offers kraken, coinbase, and binance on the paper arm select", async () => {
    render(<StatusPanel client={makeClient()} />);
    const select = await screen.findByTestId("paper-arm-venue");
    const values = Array.from(select.querySelectorAll("option")).map(
      (option) => (option as HTMLOptionElement).value,
    );
    expect(values).toEqual(["kraken", "coinbase", "binance", "gate", "pionex", "kucoin"]);
    expect(VENUES).toContain("binance");
  });

  it("arms paper with venue binance when selected", async () => {
    const client = makeClient();
    render(<StatusPanel client={client} />);
    await screen.findByTestId("paper-arm-revision");
    fireEvent.change(await screen.findByTestId("paper-arm-revision"), {
      target: { value: "rev-binance" },
    });
    fireEvent.change(screen.getByTestId("paper-arm-venue"), {
      target: { value: "binance" },
    });
    fireEvent.click(screen.getByRole("button", { name: /start paper run/i }));
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalled();
    });
    expect(client.arm).toHaveBeenCalledWith(
      expect.objectContaining({
        venue: "binance",
        mode: "paper",
      }),
    );
  });
});
