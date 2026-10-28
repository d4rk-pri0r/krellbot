import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StatusPanel } from "./StatusPanel";
import type { PaperClient, PaperCommandResult, PaperStatus } from "./client";
import type { RehearsalClient, RehearsalCommandResult, RehearsalStatus } from "./rehearsalClient";

/**
 * Browser storage-access fault injection for the OPTIONAL last-armed-balance
 * memory (`readLastArmedBalance` / `writeLastArmedBalance`).
 *
 * Every fault below is a SYNTHETIC standard `DOMException` injected into the
 * JSDOM `window` of this suite. These tests mount the actual production
 * StatusPanel component; they do NOT claim a real browser privacy setting,
 * backend, TCP or native environment was reproduced.
 *
 * Coordinator contract under test: the browser-local remembered balance is
 * optional and never authority — storage denial before opening Paper or
 * during a successful Arm must not crash the panel, must not prevent the
 * confirmed command follow-up status read, must not duplicate the command,
 * and must never fabricate or hide a backend outcome.
 */

const LAST_ARMED_BALANCE_KEY = "krellbot.paper.lastArmedBalance";

/** The real jsdom descriptor, captured before any injection. */
let realStorageDescriptor: PropertyDescriptor | undefined;

beforeEach(() => {
  realStorageDescriptor = Object.getOwnPropertyDescriptor(
    window,
    "localStorage",
  );
  if (realStorageDescriptor === undefined) {
    throw new Error("jsdom window.localStorage own descriptor not found");
  }
  window.localStorage.clear();
});

afterEach(() => {
  // Restore the genuine jsdom storage property for the next test.
  const descriptor = realStorageDescriptor;
  if (descriptor !== undefined) {
    Object.defineProperty(window, "localStorage", descriptor);
  }
  cleanup();
  vi.restoreAllMocks();
});

/**
 * SYNTHETIC fault: acquiring `window.localStorage` itself throws a standard
 * SecurityError DOMException, the shape a real browser raises when storage
 * access is denied by policy. The capability check — not just getItem or
 * setItem — is what must be guarded.
 */
function denyLocalStorageAcquisition(): void {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    get(): Storage {
      throw new DOMException(
        "Access to localStorage is denied for this document (synthetic fault injection)",
        "SecurityError",
      );
    },
  });
}

/** SYNTHETIC fault: the storage property exists but is entirely absent. */
function removeLocalStorage(): void {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: undefined,
  });
}

/** SYNTHETIC fault: acquisition works, `getItem` throws SecurityError. */
function storageWhoseGetItemThrows(): void {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (): string => {
        throw new DOMException(
          "getItem denied (synthetic fault injection)",
          "SecurityError",
        );
      },
      setItem: (): void => {},
    } as unknown as Storage,
  });
}

/** SYNTHETIC fault: acquisition works, `setItem` throws SecurityError. */
function storageWhoseSetItemThrows(): void {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (): string | null => null,
      setItem: (): void => {
        throw new DOMException(
          "setItem denied (synthetic fault injection)",
          "SecurityError",
        );
      },
    } as unknown as Storage,
  });
}

function unarmed(): PaperStatus {
  return { schema_version: "1", armed: false };
}

function armedStatus(extra: Partial<PaperStatus> = {}): PaperStatus {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    entries_paused: true,
    mode: "paper",
    pack_id: "trend-follow",
    ...extra,
  };
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

function makeRehearsalClient(
  overrides: Partial<RehearsalClient> = {},
): RehearsalClient {
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

/** Settle every pending promise/microtask and a real-time quiet window. */
async function settle(ms = 120): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

async function armFromForm(): Promise<void> {
  fireEvent.change(await screen.findByTestId("paper-arm-revision"), {
    target: { value: "rev-2" },
  });
  fireEvent.change(screen.getByTestId("paper-arm-balance"), {
    target: { value: "250.50" },
  });
  fireEvent.click(screen.getByRole("button", { name: /arm paper pack/i }));
}

describe("StatusPanel optional storage access (browser-local memory is optional, never authority)", () => {
  it("healthy storage control: offers a remembered valid balance and the default when nothing is remembered", async () => {
    window.localStorage.setItem(LAST_ARMED_BALANCE_KEY, "777.77");
    render(<StatusPanel client={makeClient()} />);
    const balance = (await screen.findByTestId(
      "paper-arm-balance",
    )) as HTMLInputElement;
    expect(balance.value).toBe("777.77");
  });

  it("healthy storage control: nothing remembered falls back to the default 1000", async () => {
    render(<StatusPanel client={makeClient()} />);
    const balance = (await screen.findByTestId(
      "paper-arm-balance",
    )) as HTMLInputElement;
    expect(balance.value).toBe("1000");
  });

  it("invalid remembered balances are not offered: the default 1000 stands", async () => {
    for (const junk of ["", "abc", "0", "-5", "1e3", ".5"]) {
      window.localStorage.setItem(LAST_ARMED_BALANCE_KEY, junk);
      const { unmount } = render(<StatusPanel client={makeClient()} />);
      const balance = (await screen.findByTestId(
        "paper-arm-balance",
      )) as HTMLInputElement;
      expect(balance.value).toBe("1000");
      unmount();
      window.localStorage.clear();
    }
  });

  it("opening Paper with a SecurityError-throwing localStorage getter still renders the arm form with the default balance", async () => {
    // SYNTHETIC fault injection: the localStorage *acquisition* itself
    // throws the standard DOMException. Previously the capability check
    // read window.localStorage outside try and the whole panel crashed.
    denyLocalStorageAcquisition();
    render(<StatusPanel client={makeClient()} />);

    const form = await screen.findByTestId(
      "paper-arm-form",
      {},
      { timeout: 3000 },
    );
    expect(form).toBeDefined();
    const balance = (await screen.findByTestId(
      "paper-arm-balance",
    )) as HTMLInputElement;
    expect(balance.value).toBe("1000");
    // The form stays usable: a balance can still be entered.
    fireEvent.change(balance, { target: { value: "250.50" } });
    expect(
      screen.getByRole("button", { name: /arm paper pack/i }).getAttribute(
        "disabled",
      ),
    ).toBeNull();
  });

  it("opening Paper with entirely absent storage still renders the arm form with the default balance", async () => {
    removeLocalStorage();
    render(<StatusPanel client={makeClient()} />);
    const form = await screen.findByTestId("paper-arm-form");
    expect(form).toBeDefined();
    expect(
      ((await screen.findByTestId("paper-arm-balance")) as HTMLInputElement)
        .value,
    ).toBe("1000");
  });

  it("opening Paper when getItem itself throws still renders the arm form with the default balance", async () => {
    storageWhoseGetItemThrows();
    render(<StatusPanel client={makeClient()} />);
    const form = await screen.findByTestId("paper-arm-form");
    expect(form).toBeDefined();
    expect(
      ((await screen.findByTestId("paper-arm-balance")) as HTMLInputElement)
        .value,
    ).toBe("1000");
  });

  it("a confirmed Arm whose completion write is denied (SecurityError acquisition) still performs exactly one follow-up status read and renders the armed controls", async () => {
    const getStatus = vi
      .fn()
      // mount read: confirmed unarmed, so the arm form renders
      .mockResolvedValueOnce(unarmed())
      // post-arm read: the backend now reports the armed paper pack
      .mockResolvedValue(armedStatus({ entries_paused: true }));
    const client = makeClient({ getStatus });
    render(<StatusPanel client={client} />);

    // The form renders under healthy storage first…
    expect(await screen.findByTestId("paper-arm-form")).toBeDefined();
    // …then storage access is denied before the user completes the Arm
    // (SYNTHETIC fault injection at command completion time).
    denyLocalStorageAcquisition();
    await armFromForm();

    // Exactly one arm command: the denial must not duplicate or retry it.
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalledTimes(1);
    });
    // The denied best-effort write must not prevent the confirmed
    // command's follow-up status read.
    await waitFor(() => {
      expect(getStatus).toHaveBeenCalledTimes(2);
    });
    const entries = await screen.findByTestId("paper-status-entries");
    expect(entries.textContent).toMatch(/Entries paused/);
    expect(screen.getByTestId("paper-status-pack").textContent).toMatch(
      /trend-follow on kraken SUIUSD/,
    );
    // Quiet window: no second command, no polling.
    await settle(160);
    expect(client.arm).toHaveBeenCalledTimes(1);
    expect(getStatus).toHaveBeenCalledTimes(2);
    expect(
      screen.queryByTestId("paper-arm-unknown"),
    ).toBeNull();
    expect(screen.queryByTestId("paper-status-unavailable")).toBeNull();
  });

  it("a confirmed Arm whose setItem throws still performs the follow-up read and renders the armed controls", async () => {
    const getStatus = vi
      .fn()
      .mockResolvedValueOnce(unarmed())
      .mockResolvedValue(armedStatus({ entries_paused: true }));
    const client = makeClient({ getStatus });
    render(<StatusPanel client={client} />);

    expect(await screen.findByTestId("paper-arm-form")).toBeDefined();
    storageWhoseSetItemThrows();
    await armFromForm();

    await waitFor(() => {
      expect(client.arm).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(getStatus).toHaveBeenCalledTimes(2);
    });
    expect(
      (await screen.findByTestId("paper-status-entries")).textContent,
    ).toMatch(/Entries paused/);
    await settle(160);
    expect(client.arm).toHaveBeenCalledTimes(1);
    expect(getStatus).toHaveBeenCalledTimes(2);
  });

  it("storage denial never hides a backend refusal: the arm form stays with the inline refusal and no follow-up read fires", async () => {
    const getStatus = vi.fn().mockResolvedValue(unarmed());
    const client = makeClient({
      getStatus,
      arm: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "draft_not_runnable",
        ok: false,
        message: "draft rev-2 is not runnable",
        effect: "refused",
      } satisfies PaperCommandResult),
    });
    denyLocalStorageAcquisition();
    render(<StatusPanel client={client} />);

    expect(await screen.findByTestId("paper-arm-form")).toBeDefined();
    await armFromForm();

    const error = await screen.findByTestId("paper-arm-error");
    expect(error.textContent).toMatch(/draft rev-2 is not runnable/);
    expect(screen.queryByTestId("paper-arm-unknown")).toBeNull();
    expect(screen.queryByTestId("paper-status-pack")).toBeNull();
    // A refused arm is not an arm transition: exactly the mount read.
    await settle(160);
    expect(client.arm).toHaveBeenCalledTimes(1);
    expect(getStatus).toHaveBeenCalledTimes(1);
  });

  it("storage denial never hides an unknown transport outcome: the honest unknown message stands, no armed claim, no automatic retry", async () => {
    const getStatus = vi.fn().mockResolvedValue(unarmed());
    const client = makeClient({
      getStatus,
      arm: vi.fn().mockRejectedValue(new Error("paper.arm failed: 503")),
    });
    denyLocalStorageAcquisition();
    render(<StatusPanel client={client} />);

    expect(await screen.findByTestId("paper-arm-form")).toBeDefined();
    await armFromForm();

    const unknown = await screen.findByTestId("paper-arm-unknown");
    expect(unknown.textContent).toMatch(/Arm outcome unknown/i);
    expect(unknown.textContent).toMatch(/503/);
    expect(screen.queryByTestId("paper-status-pack")).toBeNull();
    await settle(160);
    expect(client.arm).toHaveBeenCalledTimes(1);
  });

  it("clearing the balance field under storage denial neither crashes nor silently refills the field", async () => {
    render(<StatusPanel client={makeClient()} />);
    const balance = (await screen.findByTestId(
      "paper-arm-balance",
    )) as HTMLInputElement;
    expect(balance.value).toBe("1000");

    // An explicit clear also writes (an empty remember-value); under
    // denial that write must be swallowed, not thrown into the event.
    denyLocalStorageAcquisition();
    fireEvent.change(balance, { target: { value: "" } });
    expect(balance.value).toBe("");
    // A fresh mount under continued denial still offers the default.
    cleanup();
    render(<StatusPanel client={makeClient()} />);
    const again = (await screen.findByTestId(
      "paper-arm-balance",
    )) as HTMLInputElement;
    expect(again.value).toBe("1000");
  });
});
