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

function armedStatus(extra: Partial<PaperStatus> = {}): PaperStatus {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    entries_paused: false,
    mode: "paper",
    pack_id: "trend-follow",
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
    free_cash: "748.123400",
    holdings: [{ symbol: "SUI", qty: "2.5000" }],
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
  return {
    getStatus: vi.fn().mockResolvedValue(armedStatus()),
    getPosition: vi.fn().mockResolvedValue(filledPosition()),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    createRehearsalClient: () => makeRehearsalClient(),
    ...overrides,
  } as PaperClient;
}

function paperRefreshButton(): HTMLElement {
  const candidates = screen.getAllByRole("button", { name: /refresh status/i });
  const paper = candidates.find((button) =>
    (button.className ?? "").includes("kbot-paper-status__action"),
  );
  if (paper === undefined) {
    throw new Error("paper Refresh status button not found");
  }
  return paper;
}

describe("StatusPanel owned position market scope (#173)", () => {
  it("invalidates the cached SUI position when refresh confirms ETHUSD", async () => {
    let statusReads = 0;
    let positionReads = 0;
    // Object holder so tsc does not narrow the deferred resolve to `never`
    // after the assignment only happens inside a Promise executor.
    const ethPositionGate: {
      resolve: ((position: PaperPosition) => void) | null;
    } = { resolve: null };

    const client = makeClient({
      getStatus: vi.fn().mockImplementation(async () => {
        statusReads += 1;
        if (statusReads === 1) {
          return armedStatus({ pair: "SUIUSD", pack_id: "sui-pack" });
        }
        return armedStatus({ pair: "ETHUSD", pack_id: "eth-pack" });
      }),
      getPosition: vi.fn().mockImplementation(async () => {
        positionReads += 1;
        if (positionReads === 1) {
          return filledPosition({
            pair: "SUIUSD",
            free_cash: "748.123400",
            holdings: [{ symbol: "SUI", qty: "2.5000" }],
            as_of_run: "kraken:sui-pack:SUIUSD",
          });
        }
        return await new Promise<PaperPosition>((resolve) => {
          ethPositionGate.resolve = resolve;
        });
      }),
    });

    render(<StatusPanel client={client} />);

    const suiSentence = await screen.findByTestId("paper-position");
    expect(suiSentence.textContent).toBe(
      "Owned position: 2.5000 SUI — free cash 748.123400 USD",
    );
    expect(screen.getByTestId("paper-status-pack").textContent).toMatch(
      /SUIUSD/,
    );

    // Another local client changed the armed market; refresh confirms ETHUSD
    // while the ETH position read is still pending.
    paperRefreshButton().click();

    await waitFor(() => {
      expect(screen.getByTestId("paper-status-pack").textContent).toMatch(
        /ETHUSD/,
      );
    });
    // Cached SUI holdings must not remain under the ETHUSD heading.
    expect(screen.queryByTestId("paper-position")).toBeNull();
    expect(
      (await screen.findByTestId("paper-position-pending")).textContent,
    ).toMatch(/Reading owned position/);

    await waitFor(() => {
      expect(ethPositionGate.resolve).not.toBeNull();
    });
    ethPositionGate.resolve!(
      filledPosition({
        pair: "ETHUSD",
        free_cash: "900.000000",
        holdings: [{ symbol: "ETH", qty: "0.1250" }],
        as_of_run: "kraken:eth-pack:ETHUSD",
      }),
    );

    const ethSentence = await screen.findByTestId("paper-position");
    expect(ethSentence.textContent).toBe(
      "Owned position: 0.1250 ETH — free cash 900.000000 USD",
    );
    expect(ethSentence.textContent).not.toMatch(/SUI/);
  });

  it("refuses a position body whose market identity disagrees with status", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(
        armedStatus({ pair: "ETHUSD", pack_id: "eth-pack" }),
      ),
      getPosition: vi.fn().mockResolvedValue(
        filledPosition({
          pair: "SUIUSD",
          free_cash: "748.123400",
          holdings: [{ symbol: "SUI", qty: "2.5000" }],
        }),
      ),
    });

    render(<StatusPanel client={client} />);

    await screen.findByTestId("paper-status-pack");
    const unavailable = await screen.findByTestId("paper-position-unavailable");
    expect(unavailable.textContent).toMatch(
      /Owned position does not match the current armed market/,
    );
    expect(screen.queryByTestId("paper-position")).toBeNull();
    expect(screen.getByTestId("paper-status-pack").textContent).toMatch(
      /ETHUSD/,
    );
  });

  it("keeps a matching-position sentence across an ordinary same-market refresh", async () => {
    const client = makeClient({
      getStatus: vi.fn().mockResolvedValue(armedStatus()),
      getPosition: vi.fn().mockResolvedValue(filledPosition()),
    });

    render(<StatusPanel client={client} />);

    const first = await screen.findByTestId("paper-position");
    expect(first.textContent).toBe(
      "Owned position: 2.5000 SUI — free cash 748.123400 USD",
    );

    paperRefreshButton().click();

    await waitFor(() => {
      expect(client.getStatus).toHaveBeenCalledTimes(2);
    });
    const again = await screen.findByTestId("paper-position");
    expect(again.textContent).toBe(
      "Owned position: 2.5000 SUI — free cash 748.123400 USD",
    );
  });
});
