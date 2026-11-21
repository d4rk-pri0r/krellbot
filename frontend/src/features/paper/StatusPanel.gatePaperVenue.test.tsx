/**
 * Paper arm offers Gate and records a paper arm for BTC-USDT.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PaperClient, PaperCommandResult, PaperStatus } from "./client";
import type { RehearsalClient, RehearsalCommandResult, RehearsalStatus } from "./rehearsalClient";
import { StatusPanel } from "./StatusPanel";
import { GATE_PAPER_WAVE_PAIR } from "../strategies/ownedStrategy";

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

function makeClient(): PaperClient {
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
        revision_id: "rev-gate",
        parent_revision_id: null,
        state: "validated",
        runnable: true,
        created_at: "2026-10-08T00:00:00Z",
        id: "trend-follow",
        label: "Trend follow",
        pair: GATE_PAPER_WAVE_PAIR,
        timeframe: "1h",
      },
    ]),
    arm: vi.fn().mockResolvedValue(armOk("gate", GATE_PAPER_WAVE_PAIR)),
    createRehearsalClient: () => rehearsal,
  };
}

describe("paper arm gate", () => {
  it("arms paper with venue gate when selected", async () => {
    const client = makeClient();
    render(<StatusPanel client={client} />);
    await screen.findByTestId("paper-arm-revision");
    fireEvent.change(await screen.findByTestId("paper-arm-revision"), {
      target: { value: "rev-gate" },
    });
    fireEvent.change(screen.getByTestId("paper-arm-venue"), {
      target: { value: "gate" },
    });
    fireEvent.click(screen.getByRole("button", { name: /start paper run/i }));
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalled();
    });
    expect(client.arm).toHaveBeenCalledWith(
      expect.objectContaining({
        venue: "gate",
        mode: "paper",
      }),
    );
  });
});
