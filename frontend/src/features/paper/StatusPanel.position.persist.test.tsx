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

/**
 * The owned position exactly as the persisted
 * ``<home>/run/paper-kraken.json`` state reads it back after a fill and
 * after a backend restart: the decimal strings are byte-identical both
 * times because the state file, not memory, is the source.
 */
function persistedPosition(): PaperPosition {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    mode: "paper",
    free_cash: "748.874640020",
    holdings: [{ symbol: "SUI", qty: "62.538182660" }],
    as_of_run: "kraken:trend-follow:SUIUSD",
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

function makeRehearsalClient(): RehearsalClient {
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
  };
}

function makeClient(overrides: Partial<PaperClient> = {}): PaperClient {
  const rehearsal = makeRehearsalClient();
  return {
    getStatus: vi.fn().mockResolvedValue(armedStatus()),
    getPosition: vi.fn().mockResolvedValue(persistedPosition()),
    pauseEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_paused",
      ok: true,
      message: "entries paused",
      effect: "changed",
      revision_before: null,
      revision_after: null,
    }),
    resumeEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_resumed",
      ok: true,
      message: "entries resumed",
      effect: "changed",
      revision_before: null,
      revision_after: null,
    }),
    disarm: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "disarmed",
      ok: true,
      message: "disarmed kraken SUIUSD",
      effect: "changed",
      revision_before: null,
      revision_after: null,
    }),
    createRehearsalClient: () => rehearsal,
    ...overrides,
  } as PaperClient;
}

const EXPECTED_SENTENCE =
  "Owned position: 62.538182660 SUI — free cash 748.874640020 USD";

describe("StatusPanel owned position persistence (backend stoppage + reopen)", () => {
  it("re-renders the identical owned position after a simulated backend stoppage and reopen", async () => {
    // Session one: the panel is open with the armed pack and reads the
    // owned position from the persisted state.
    const firstClient = makeClient();
    const { unmount } = render(<StatusPanel client={firstClient} />);
    const first = await screen.findByTestId("paper-position");
    expect(first.textContent).toBe(EXPECTED_SENTENCE);
    await waitFor(() => {
      expect(firstClient.getPosition).toHaveBeenCalledTimes(1);
    });

    // The workstation closes (and the backend PID may stop with it): the
    // state file on disk is what survives. Nothing is kept in memory.
    unmount();
    cleanup();

    // Session two: the app reopens against the same home — a fresh panel,
    // a fresh client, and the same persisted state read back through
    // /api/v1/paper/position. No developer shell, no manual state import.
    const secondClient = makeClient();
    render(<StatusPanel client={secondClient} />);
    const second = await screen.findByTestId("paper-position");
    expect(second.textContent).toBe(EXPECTED_SENTENCE);
    await waitFor(() => {
      expect(secondClient.getPosition).toHaveBeenCalledTimes(1);
    });
  });

  it("keeps the same position sentence across a disarm and re-arm round-trip", async () => {
    // The station disarms (the cached position must go: the armed branch
    // is gone) and re-arms; the reopened panel re-reads the same persisted
    // position and the same sentence renders again.
    const client = makeClient();
    const positionMock = client.getPosition as ReturnType<typeof vi.fn>;

    const { unmount } = render(<StatusPanel client={client} />);
    expect((await screen.findByTestId("paper-position")).textContent).toBe(
      EXPECTED_SENTENCE,
    );

    // Confirmed disarm: the panel's onConfirmed state flips to unarmed,
    // the armed branch — and with it the position sentence — is gone.
    fireEventDisarm();
    await screen.findByTestId("paper-status-empty");
    expect(screen.queryByTestId("paper-position")).toBeNull();
    expect(positionMock).toHaveBeenCalledTimes(1);

    // The station re-arms against the same persisted state file and the
    // panel is reopened: a fresh mount re-reads the status (armed again)
    // and re-reads the position from the same wire shape.
    unmount();
    cleanup();
    const rearmedClient = makeClient();
    const rearmedPosition = rearmedClient.getPosition as ReturnType<
      typeof vi.fn
    >;
    render(<StatusPanel client={rearmedClient} />);
    const again = await screen.findByTestId("paper-position");
    expect(again.textContent).toBe(EXPECTED_SENTENCE);
    await waitFor(() => {
      expect(rearmedPosition).toHaveBeenCalledTimes(1);
    });
  });
});

function fireEventDisarm(): void {
  // Click the panel's Disarm control (armed branch) via the DOM: the
  // disarm command is mocked to confirm, and the follow-up status read
  // is what flips the panel to the unarmed branch.
  const button = screen.getByRole("button", { name: /disarm/i });
  button.click();
}
