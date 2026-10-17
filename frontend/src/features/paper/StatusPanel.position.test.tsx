import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatusPanel } from "./StatusPanel";
import type {
  PaperClient,
  PaperPosition,
  PaperStatus,
} from "./client";
import type {
  RehearsalClient,
  RehearsalCommandResult,
  RehearsalStatus,
} from "./rehearsalClient";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** The confirmed armed status the panel reads after a backend-confirmed Arm. */
function armedStatus(): PaperStatus {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    entries_paused: false,
    mode: "paper",
    pack_id: "trend-follow",
  };
}

/** The owned position as `/api/v1/paper/position` reads it back after a fill. */
function filledPosition(extra: Partial<PaperPosition> = {}): PaperPosition {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    mode: "paper",
    free_cash: "748.874640020",
    holdings: [{ symbol: "SUI", qty: "62.538182660" }],
    as_of_run: "kraken:trend-follow:SUIUSD",
    ...extra,
  };
}

function rehearsalStatus(extra: Partial<RehearsalStatus> = {}): RehearsalStatus {
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
    ...extra,
  };
}

function makeRehearsalClient(
  overrides: Partial<RehearsalClient> = {},
): RehearsalClient {
  const command = (
    status: Partial<RehearsalStatus>,
  ): RehearsalCommandResult => ({
    schema_version: "1",
    code: "ok",
    ok: true,
    message: "ok",
    status: rehearsalStatus(status),
  });
  return {
    getStatus: vi.fn().mockResolvedValue(rehearsalStatus()),
    start: vi.fn().mockResolvedValue(command({ status: "running", cursor: 1 })),
    pause: vi.fn().mockResolvedValue(command({ status: "paused" })),
    resume: vi.fn().mockResolvedValue(command({ status: "running", cursor: 2 })),
    exit: vi.fn().mockResolvedValue(command({ status: "exited" })),
    stop: vi.fn().mockResolvedValue(command({ status: "stopped" })),
    ...overrides,
  };
}

function makeClient(overrides: Partial<PaperClient> = {}): PaperClient {
  const rehearsal = makeRehearsalClient();
  return {
    getStatus: vi.fn().mockResolvedValue(armedStatus()),
    getPosition: vi.fn().mockResolvedValue(filledPosition()),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    createRehearsalClient: () => rehearsal,
    ...overrides,
  } as PaperClient;
}

describe("StatusPanel owned position (after Arm)", () => {
  it("renders the owned position sentence and free cash verbatim from /api/v1/paper/position", async () => {
    const client = makeClient();
    render(<StatusPanel client={client} />);

    const sentence = await screen.findByTestId("paper-position");
    // Every decimal string is quoted from the wire, never re-formatted:
    // the seeded values keep their full precision exactly as persisted.
    expect(sentence.textContent).toBe(
      "Owned position: 62.538182660 SUI — free cash 748.874640020 USD",
    );
    await waitFor(() => {
      expect(client.getPosition).toHaveBeenCalledTimes(1);
    });
  });

  it("renders the empty owned-position state when the armed pack has no fills", async () => {
    const client = makeClient({
      getPosition: vi.fn().mockResolvedValue(
        filledPosition({ holdings: [], free_cash: "1000" }),
      ),
    });
    render(<StatusPanel client={client} />);

    const sentence = await screen.findByTestId("paper-position");
    expect(sentence.textContent).toBe(
      "Owned position: no open position — free cash 1000 USD",
    );
  });

  it("renders multiple owned holdings in one sentence, wire order preserved", async () => {
    const client = makeClient({
      getPosition: vi.fn().mockResolvedValue(
        filledPosition({
          holdings: [
            { symbol: "SUI", qty: "62.5" },
            { symbol: "BTC", qty: "0.001" },
          ],
        }),
      ),
    });
    render(<StatusPanel client={client} />);

    const sentence = await screen.findByTestId("paper-position");
    expect(sentence.textContent).toBe(
      "Owned position: 62.5 SUI, 0.001 BTC — free cash 748.874640020 USD",
    );
  });

  it("refuses closed-shape wire variants: a malformed body is surfaced as unavailable, never a zero position", async () => {
    // The typed client throws when the body is not the closed shape (e.g.
    // holdings rows as {pair, quantity} instead of {symbol, qty}). The
    // panel must render the honest unavailable line, not a repaired or
    // manufactured position.
    const client = makeClient({
      getPosition: vi.fn().mockRejectedValue(
        new Error("paper position holding row malformed"),
      ),
    });
    render(<StatusPanel client={client} />);

    const unavailable = await screen.findByTestId("paper-position-unavailable");
    expect(unavailable.textContent).toMatch(
      /Owned position unavailable: paper position holding row malformed/,
    );
    expect(screen.queryByTestId("paper-position")).toBeNull();
  });

  it("refuses an armed body missing the projection fields instead of rendering a zero position", async () => {
    const client = makeClient({
      getPosition: vi.fn().mockRejectedValue(
        new Error("paper position body missing projection fields"),
      ),
    });
    render(<StatusPanel client={client} />);

    const unavailable = await screen.findByTestId("paper-position-unavailable");
    expect(unavailable.getAttribute("role")).toBe("alert");
    expect(unavailable.textContent).toMatch(
      /paper position body missing projection fields/,
    );
    expect(screen.queryByTestId("paper-position")).toBeNull();
  });

  it("renders the honest unavailable line for a legacy client without getPosition", async () => {
    const client = makeClient();
    const { getPosition: _omit, ...legacy } = client;
    render(<StatusPanel client={legacy as unknown as PaperClient} />);

    const unavailable = await screen.findByTestId("paper-position-unavailable");
    expect(unavailable.textContent).toBe("Owned position unavailable");
    expect(screen.queryByTestId("paper-position")).toBeNull();
  });

  it("renders no position sentence when no pack is armed", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue({
        schema_version: "1",
        armed: false,
      }),
    });
    render(<StatusPanel client={client} />);

    // The unarmed branch shows the empty state, never a position claim.
    expect(await screen.findByTestId("paper-status-empty")).toBeTruthy();
    expect(screen.queryByTestId("paper-position")).toBeNull();
    expect(screen.queryByTestId("paper-position-unavailable")).toBeNull();
    await waitFor(() => {
      expect(client.getStatus).toHaveBeenCalled();
    });
  });

  it("does not call getPosition when no pack is armed", async () => {
    const getPosition = vi.fn();
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue({
        schema_version: "1",
        armed: false,
      }),
      getPosition,
    });
    render(<StatusPanel client={client} />);

    await screen.findByTestId("paper-status-empty");
    await waitFor(() => {
      expect(client.getStatus).toHaveBeenCalled();
    });
    expect(getPosition).not.toHaveBeenCalled();
  });
});
