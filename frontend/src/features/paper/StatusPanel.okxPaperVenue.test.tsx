/**
 * Paper arm venue picker includes OKX for paper paths and does not arm live.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OKX_PAPER_WAVE_PAIR } from "../strategies/ownedStrategy";
import type { PaperClient, PaperCommandResult, PaperStatus } from "./client";
import type { RehearsalClient, RehearsalCommandResult, RehearsalStatus } from "./rehearsalClient";
import { StatusPanel } from "./StatusPanel";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function unarmed(): PaperStatus {
  return { schema_version: "1", armed: false };
}

function armOk(): PaperCommandResult {
  return {
    schema_version: "1",
    code: "armed",
    ok: true,
    message: "armed okx BTC-USDT",
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
        strategy_id: "strat-okx",
        revision_id: "rev-okx",
        parent_revision_id: null,
        state: "validated",
        runnable: true,
        created_at: "2026-11-20T00:00:00Z",
        id: "okx-follow",
        label: "OKX follow",
        pair: OKX_PAPER_WAVE_PAIR,
        timeframe: "1h",
      },
    ]),
    arm: vi.fn().mockResolvedValue(armOk()),
    createRehearsalClient: () => rehearsal,
  };
}

describe("paper venue picker includes okx", () => {
  it("arms paper with venue okx when selected", async () => {
    const client = makeClient();
    render(<StatusPanel client={client} />);
    await screen.findByTestId("paper-arm-revision");
    fireEvent.change(await screen.findByTestId("paper-arm-revision"), {
      target: { value: "rev-okx" },
    });
    fireEvent.change(screen.getByTestId("paper-arm-venue"), {
      target: { value: "okx" },
    });
    fireEvent.click(screen.getByRole("button", { name: /start paper run/i }));
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalled();
    });
    expect(client.arm).toHaveBeenCalledWith(
      expect.objectContaining({
        venue: "okx",
        mode: "paper",
      }),
    );
  });
});
