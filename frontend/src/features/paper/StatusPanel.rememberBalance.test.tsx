import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StatusPanel } from "./StatusPanel";
import type { PaperClient, PaperCommandResult, PaperStatus } from "./client";
import type { RehearsalClient, RehearsalCommandResult, RehearsalStatus } from "./rehearsalClient";

const LAST_ARMED_BALANCE_KEY = "krellbot.paper.lastArmedBalance";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

beforeEach(() => {
  window.localStorage.clear();
});

function unarmed(): PaperStatus {
  return { schema_version: "1", armed: false };
}

function armOk(): PaperCommandResult {
  return {
    schema_version: "1",
    code: "armed",
    ok: true,
    message: "armed kraken SUIUSD",
    effect: "changed",
    revision_before: null,
    revision_after: null,
  };
}

function runnableDraft(revision_id: string) {
  return {
    schema_version: "1",
    strategy_id: "strat-1",
    revision_id,
    parent_revision_id: null,
    state: "validated",
    runnable: true,
    created_at: "2026-10-08T00:00:00Z",
    id: "trend-follow",
    label: "Trend follow",
    pair: "SUIUSD",
    timeframe: "1h",
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

function rehearsalResult(): RehearsalCommandResult {
  return {
    schema_version: "1",
    code: "ok",
    ok: true,
    message: "ok",
    status: rehearsalStatus(),
  };
}

function makeRehearsalClient(overrides: Partial<RehearsalClient> = {}): RehearsalClient {
  return {
    getStatus: vi.fn().mockResolvedValue(rehearsalStatus()),
    start: vi.fn().mockResolvedValue(rehearsalResult()),
    pause: vi.fn().mockResolvedValue(rehearsalResult()),
    resume: vi.fn().mockResolvedValue(rehearsalResult()),
    exit: vi.fn().mockResolvedValue(rehearsalResult()),
    stop: vi.fn().mockResolvedValue(rehearsalResult()),
    ...overrides,
  };
}

function makeClient(overrides: Partial<PaperClient> = {}): PaperClient {
  const client: PaperClient = {
    getStatus: vi.fn().mockResolvedValue(unarmed()),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    listOwnedDrafts: vi.fn().mockResolvedValue([runnableDraft("rev-2")]),
    arm: vi.fn().mockResolvedValue(armOk()),
    createRehearsalClient: () => makeRehearsalClient(),
    ...overrides,
  };
  return client;
}

async function findBalanceInput(): Promise<HTMLInputElement> {
  const el = await screen.findByTestId("paper-arm-balance");
  return el as HTMLInputElement;
}

describe("StatusPanel remembers the last armed balance", () => {
  it("pre-fills the arm balance input with the persisted last armed balance and stays editable", async () => {
    window.localStorage.setItem(LAST_ARMED_BALANCE_KEY, "777.77");
    const client = makeClient();
    render(<StatusPanel client={client} />);

    // Old behavior: the input started at the hard-coded default "1000" and
    // never consulted localStorage, so the remembered balance never appears.
    const balance = await findBalanceInput();
    expect(balance.value).toBe("777.77");

    // The pre-filled value is editable, not locked.
    fireEvent.change(balance, { target: { value: "300" } });
    expect(balance.value).toBe("300");
  });

  it("keeps the default balance when nothing was ever armed", async () => {
    const client = makeClient();
    render(<StatusPanel client={client} />);
    const balance = await findBalanceInput();
    expect(balance.value).toBe("1000");
  });

  it("does not pre-fill when the persisted value is not a parseable decimal > 0", async () => {
    for (const junk of ["", "   ", "abc", "0", "-5", "1e3", ".5", "12,5"]) {
      window.localStorage.setItem(LAST_ARMED_BALANCE_KEY, junk);
      const { unmount } = render(<StatusPanel client={makeClient()} />);
      const balance = await findBalanceInput();
      expect(balance.value).toBe("1000");
      unmount();
      window.localStorage.clear();
    }
  });

  it("persists the balance after a confirmed arm and offers it on the next mount", async () => {
    window.localStorage.setItem(LAST_ARMED_BALANCE_KEY, "777.77");
    const client = makeClient();
    const { unmount } = render(<StatusPanel client={client} />);

    const balance = await findBalanceInput();
    expect(balance.value).toBe("777.77");
    fireEvent.change(await screen.findByTestId("paper-arm-revision"), {
      target: { value: "rev-2" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /arm paper pack/i }),
    );
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalledTimes(1);
    });

    // A confirmed arm persists the balance that was sent.
    expect(window.localStorage.getItem(LAST_ARMED_BALANCE_KEY)).toBe("777.77");

    unmount();
    window.localStorage.clear();
    window.localStorage.setItem(LAST_ARMED_BALANCE_KEY, "777.77");
    const { unmount: unmount2 } = render(<StatusPanel client={makeClient()} />);
    const again = await findBalanceInput();
    expect(again.value).toBe("777.77");
    unmount2();
  });

  it("persists the edited balance after a confirmed arm, not the stale one", async () => {
    window.localStorage.setItem(LAST_ARMED_BALANCE_KEY, "777.77");
    const client = makeClient();
    render(<StatusPanel client={client} />);

    const balance = await findBalanceInput();
    fireEvent.change(balance, { target: { value: "250.50" } });
    fireEvent.change(await screen.findByTestId("paper-arm-revision"), {
      target: { value: "rev-2" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /arm paper pack/i }),
    );
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalledTimes(1);
    });
    expect(window.localStorage.getItem(LAST_ARMED_BALANCE_KEY)).toBe("250.50");
  });

  it("clearing the field persists empty and suppresses pre-fill on the next mount", async () => {
    window.localStorage.setItem(LAST_ARMED_BALANCE_KEY, "777.77");
    const client = makeClient();
    const { unmount } = render(<StatusPanel client={client} />);

    const balance = await findBalanceInput();
    fireEvent.change(balance, { target: { value: "" } });
    // "User cleared" is remembered as empty: nothing to re-offer.
    expect(window.localStorage.getItem(LAST_ARMED_BALANCE_KEY)).toBe("");

    unmount();
    const { unmount: unmount2 } = render(<StatusPanel client={makeClient()} />);
    const again = await findBalanceInput();
    expect(again.value).toBe("1000");
    unmount2();
  });

  it("does not write to storage when the arm is refused or unknown", async () => {
    const refused = makeClient({
      arm: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "draft_not_runnable",
        ok: false,
        message: "draft rev-2 is not runnable",
        effect: "refused",
      } satisfies PaperCommandResult),
    });
    const { unmount } = render(<StatusPanel client={refused} />);
    fireEvent.change(await screen.findByTestId("paper-arm-balance"), {
      target: { value: "250.50" },
    });
    fireEvent.change(await screen.findByTestId("paper-arm-revision"), {
      target: { value: "rev-2" },
    });
    fireEvent.click(screen.getByRole("button", { name: /arm paper pack/i }));
    await waitFor(() => {
      expect(refused.arm).toHaveBeenCalledTimes(1);
    });
    await screen.findByTestId("paper-arm-error");
    expect(window.localStorage.getItem(LAST_ARMED_BALANCE_KEY)).toBeNull();
    unmount();

    window.localStorage.clear();
    const unknown = makeClient({
      arm: vi.fn().mockRejectedValue(new Error("paper.arm failed: 503")),
    });
    const { unmount: unmount2 } = render(<StatusPanel client={unknown} />);
    fireEvent.change(await screen.findByTestId("paper-arm-balance"), {
      target: { value: "250.50" },
    });
    fireEvent.change(await screen.findByTestId("paper-arm-revision"), {
      target: {value: "rev-2" },
    });
    fireEvent.click(screen.getByRole("button", { name: /arm paper pack/i }));
    await screen.findByTestId("paper-arm-unknown");
    expect(window.localStorage.getItem(LAST_ARMED_BALANCE_KEY)).toBeNull();
    unmount2();
  });
});
