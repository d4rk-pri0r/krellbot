import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatusPanel } from "./StatusPanel";
import type { PaperClient, PaperCommandResult, PaperStatus } from "./client";
import type { RehearsalClient, RehearsalStatus } from "./rehearsalClient";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function unarmed(): PaperStatus {
  return { schema_version: "1", armed: false };
}

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
  const client: PaperClient = {
    getStatus: vi.fn().mockResolvedValue(unarmed()),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    listOwnedDrafts: vi.fn().mockResolvedValue([runnableDraft("rev-2")]),
    arm: vi.fn().mockResolvedValue(armOk()),
    createRehearsalClient: () => rehearsalIdle(),
    ...overrides,
  };
  return client;
}

/** The panel's own Refresh control (the rehearsal surface has a same-named one). */
function paperRefreshButton(): HTMLElement {
  const candidates = screen.getAllByRole("button", { name: /refresh status/i });
  const paper = candidates.find((button) =>
    (button.className ?? "").includes("kbot-paper-status__action"),
  );
  if (paper === undefined) {
    throw new Error("paper refresh button not found");
  }
  return paper;
}

/** Settle every pending promise/microtask and a real-time quiet window. */
async function settle(ms = 60): Promise<void> {
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

describe("StatusPanel post-arm automatic status refresh (Paper tab)", () => {
  it("(a) after a successful Arm from unarmed, exactly one automatic getStatus() runs and the armed entries-paused raise-stop branch renders on the same panel", async () => {
    const getStatus = vi
      .fn()
      // mount read: confirmed unarmed, so the arm form renders
      .mockResolvedValueOnce(unarmed())
      // post-arm read: the backend now reports the armed paper pack with
      // entries paused
      .mockResolvedValue(armedStatus({ entries_paused: true }));
    const client = makeClient({ getStatus });
    const view = render(<StatusPanel client={client} />);

    // The panel settles unarmed and the arm form is offered.
    expect(await screen.findByTestId("paper-arm-form")).toBeDefined();
    await waitFor(() => {
      expect(getStatus).toHaveBeenCalledTimes(1);
    });

    const panelBefore = view.container.querySelector(
      '[data-testid="paper-status-panel"]',
    );

    await armFromForm();
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalledTimes(1);
    });

    // The post-Arm read fired automatically: exactly one extra read, no
    // manual Refresh, no navigation, no remount.
    await waitFor(() => {
      expect(getStatus).toHaveBeenCalledTimes(2);
    });
    const entries = await screen.findByTestId("paper-status-entries");
    expect(entries.textContent).toMatch(/Entries paused/);
    expect(screen.getByTestId("paper-status-pack").textContent).toMatch(
      /trend-follow on kraken SUIUSD/,
    );

    // The full post-Arm control set on the SAME StatusPanel.
    expect(
      screen.getByRole("button", { name: /pause entries/i }).getAttribute("disabled"),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: /resume entries/i }).getAttribute("disabled"),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: /^disarm$/i }).getAttribute("disabled"),
    ).toBeNull();
    // The resting_stop branch: the raise-stop input + Apply are mounted.
    expect(screen.getByTestId("paper-raise-stop")).toBeDefined();
    expect(screen.getByTestId("paper-raise-stop-input")).toBeDefined();
    expect(
      screen.getByTestId("paper-raise-stop-apply").getAttribute("disabled"),
    ).toBe("");

    // Same mounted panel node: the controls rendered in place, not via a
    // remount.
    const panelAfter = view.container.querySelector(
      '[data-testid="paper-status-panel"]',
    );
    expect(panelAfter).toBe(panelBefore);
  });

  it("(b) zero automatic polls after the post-Arm read resolves; the explicit Refresh control remains available but never needs to fire", async () => {
    const getStatus = vi
      .fn()
      .mockResolvedValueOnce(unarmed())
      .mockResolvedValue(armedStatus({ entries_paused: true }));
    const client = makeClient({ getStatus });
    render(<StatusPanel client={client} />);

    await screen.findByTestId("paper-arm-form");
    await armFromForm();
    await waitFor(() => {
      expect(getStatus).toHaveBeenCalledTimes(2);
    });
    await screen.findByTestId("paper-status-entries");

    // Quiet window well past any plausible poll tick: the count stays at
    // exactly mount + post-Arm.
    await settle(120);
    expect(getStatus).toHaveBeenCalledTimes(2);

    // The panel is idle and stays explicitly refreshable — the manual
    // affordance is untouched, it just is not needed.
    expect(screen.getByTestId("paper-status-panel").getAttribute("data-pending")).toBe(
      "",
    );
    expect(paperRefreshButton().getAttribute("disabled")).toBeNull();

    // An explicit Refresh remains an option and still works.
    fireEvent.click(paperRefreshButton());
    await waitFor(() => {
      expect(getStatus).toHaveBeenCalledTimes(3);
    });
  });

  it("(c) a refused Arm performs no post-Arm read: the backend refusal stays inline, no armed claim, no throw", async () => {
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
    render(<StatusPanel client={client} />);

    await screen.findByTestId("paper-arm-form");
    await armFromForm();

    // The backend's own refusal words, inline on the arm form.
    const error = await screen.findByTestId("paper-arm-error");
    expect(error.textContent).toMatch(/draft rev-2 is not runnable/);

    // Exactly the mount read: a refused arm is not an arm transition, so
    // no automatic read fires.
    await settle(80);
    expect(getStatus).toHaveBeenCalledTimes(1);
    expect(client.arm).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("paper-status-pack")).toBeNull();
    expect(screen.queryByTestId("paper-raise-stop")).toBeNull();
  });

  it("(d) a failed post-Arm getStatus surfaces the honest unavailable state without throwing, and an explicit Retry reconciles to the armed controls", async () => {
    const getStatus = vi
      .fn()
      // mount read: confirmed unarmed
      .mockResolvedValueOnce(unarmed())
      // post-arm read: transport failure
      .mockRejectedValueOnce(new Error("paper status failed: 503"))
      // explicit Retry: the server state
      .mockResolvedValue(armedStatus({ entries_paused: true }));
    const client = makeClient({ getStatus });
    render(<StatusPanel client={client} />);

    await screen.findByTestId("paper-arm-form");
    await armFromForm();
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalledTimes(1);
    });

    // The failed post-Arm read is surfaced honestly: availability unknown,
    // never an unarmed claim, never a crash.
    const unavailable = await screen.findByTestId("paper-status-unavailable");
    expect(unavailable.textContent).toMatch(/Paper status unavailable/);
    expect(screen.queryByTestId("paper-status-empty")).toBeNull();
    expect(screen.queryByTestId("paper-status-pack")).toBeNull();

    // No automatic second attempt after the failure.
    await settle(80);
    expect(getStatus).toHaveBeenCalledTimes(2);

    // The user reconciles with the explicit control.
    fireEvent.click(screen.getByRole("button", { name: /retry status/i }));
    await waitFor(() => {
      expect(getStatus).toHaveBeenCalledTimes(3);
    });
    const entries = await screen.findByTestId("paper-status-entries");
    expect(entries.textContent).toMatch(/Entries paused/);
    expect(
      screen.getByRole("button", { name: /^disarm$/i }).getAttribute("disabled"),
    ).toBeNull();
    expect(screen.getByTestId("paper-raise-stop-apply")).toBeDefined();
  });

  it("a second confirmed Arm in the same mount performs exactly one further bounded read (epoch guard), never polling", async () => {
    // Arm -> disarm -> arm again on the same mounted panel. Disarm performs
    // no follow-up read (existing contract), so exactly three reads happen:
    // mount, post-arm #1, post-arm #2.
    const getStatus = vi
      .fn()
      .mockResolvedValueOnce(unarmed()) // mount
      .mockResolvedValueOnce(armedStatus({ entries_paused: true })) // post-arm #1
      .mockResolvedValueOnce(armedStatus({ entries_paused: true })); // post-arm #2
    const client = makeClient({
      getStatus,
      disarm: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "disarmed",
        ok: true,
        message: "disarmed kraken SUIUSD",
        effect: "changed",
      } satisfies PaperCommandResult),
    });
    render(<StatusPanel client={client} />);

    await screen.findByTestId("paper-arm-form");
    await armFromForm();
    await waitFor(() => {
      expect(getStatus).toHaveBeenCalledTimes(2);
    });
    await screen.findByTestId("paper-status-entries");

    fireEvent.click(screen.getByRole("button", { name: /^disarm$/i }));
    await waitFor(() => {
      expect(client.disarm).toHaveBeenCalledTimes(1);
    });
    // Disarm applies its confirmed state directly and performs no
    // reconciliation read (the existing reducer contract): still 2 reads.
    await screen.findByTestId("paper-arm-form");
    expect(getStatus).toHaveBeenCalledTimes(2);

    await armFromForm();
    await waitFor(() => {
      expect(getStatus).toHaveBeenCalledTimes(3);
    });
    const entries = await screen.findByTestId("paper-status-entries");
    expect(entries.textContent).toMatch(/Entries paused/);

    await settle(120);
    expect(getStatus).toHaveBeenCalledTimes(3);
  });
});
