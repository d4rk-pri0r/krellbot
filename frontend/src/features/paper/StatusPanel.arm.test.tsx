import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatusPanel } from "./StatusPanel";
import type { PaperClient, PaperCommandResult, PaperStatus } from "./client";
import type { RehearsalClient, RehearsalCommandResult, RehearsalStatus } from "./rehearsalClient";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function unarmed(): PaperStatus {
  return { schema_version: "1", armed: false };
}

function runnableDraft(revision_id: string, extra: Record<string, unknown> = {}) {
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

function commandResult(
  status: Partial<RehearsalStatus>,
): RehearsalCommandResult {
  return {
    schema_version: "1",
    code: "ok",
    ok: true,
    message: "ok",
    status: rehearsalStatus(status),
  };
}

function makeRehearsalClient(
  overrides: Partial<RehearsalClient> = {},
): RehearsalClient {
  return {
    getStatus: vi.fn().mockResolvedValue(rehearsalStatus()),
    start: vi.fn().mockResolvedValue(commandResult({ status: "running", cursor: 1 })),
    pause: vi.fn().mockResolvedValue(commandResult({ status: "paused" })),
    resume: vi.fn().mockResolvedValue(commandResult({ status: "running", cursor: 2 })),
    exit: vi.fn().mockResolvedValue(commandResult({ status: "exited" })),
    stop: vi.fn().mockResolvedValue(commandResult({ status: "stopped" })),
    ...overrides,
  };
}

function makeClient(overrides: Partial<PaperClient> = {}): PaperClient {
  const rehearsal = makeRehearsalClient();
  const client: PaperClient = {
    getStatus: vi.fn().mockResolvedValue(unarmed()),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    listOwnedDrafts: vi.fn().mockResolvedValue([
      runnableDraft("rev-2"),
      runnableDraft("rev-1", { state: "draft", runnable: false }),
    ]),
    arm: vi.fn().mockResolvedValue(armOk()),
    createRehearsalClient: () => rehearsal,
    ...overrides,
  };
  return client;
}

describe("StatusPanel paper arm tracer (primary user-action path)", () => {
  it("lists owned drafts, selects an exact revision, arms with the paper.arm payload, and shows the armed state only after backend confirmation", async () => {
    const client = makeClient();
    render(<StatusPanel client={client} />);

    // The arm surface appears when no pack is armed.
    const select = await screen.findByTestId("paper-arm-revision");
    const options = select.querySelectorAll("option");
    // Only runnable/validated revisions are selectable; rev-1 (draft,
    // not runnable) must not be offered for arming.
    expect(
      Array.from(options)
        .map((o) => o.textContent ?? "")
        .join("|"),
    ).toContain("rev-2");
    expect(
      Array.from(options)
        .map((o) => o.textContent ?? "")
        .join("|"),
    ).not.toContain("rev-1");

    fireEvent.change(select, { target: { value: "rev-2" } });
    fireEvent.change(screen.getByTestId("paper-arm-balance"), {
      target: { value: "250.50" },
    });

    const armButton = screen.getByRole("button", { name: /arm paper pack/i });
    expect(armButton.getAttribute("disabled")).toBeNull();
    fireEvent.click(armButton);

    await waitFor(() => {
      expect(client.arm).toHaveBeenCalledTimes(1);
    });
    // The exact paper.arm payload the handler reads: revision_id,
    // venue, mode 'paper', paper_balance as a decimal string.
    expect(client.arm).toHaveBeenCalledWith({
      revision_id: "rev-2",
      venue: "kraken",
      mode: "paper",
      paper_balance: "250.50",
    });
  });

  it("keeps the Arm control disabled while the arm command is pending and re-enables after a refusal", async () => {
    const client = makeClient({
      arm: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "draft_not_runnable",
        ok: false,
        message: "draft rev-2 is not runnable",
        effect: "refused",
      } satisfies PaperCommandResult),
    });
    render(<StatusPanel client={client} />);
    fireEvent.change(await screen.findByTestId("paper-arm-revision"), {
      target: { value: "rev-2" },
    });
    fireEvent.change(screen.getByTestId("paper-arm-balance"), {
      target: { value: "100" },
    });
    const armButton = screen.getByRole("button", { name: /arm paper pack/i });
    fireEvent.click(armButton);
    // Pending: disabled while the command is in flight.
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalledTimes(1);
    });
    // Refusal: the backend's own message is shown, no armed claim.
    const error = await screen.findByTestId("paper-arm-error");
    expect(error.textContent).toMatch(/draft rev-2 is not runnable/);
    expect(screen.queryByTestId("paper-arm-error")).not.toBeNull();
    expect(armButton.getAttribute("disabled")).toBeNull();
    expect(screen.queryByTestId("paper-status-pack")).toBeNull();
  });

  it("renders an honest unknown-outcome message when the arm transport throws and never fabricates an armed state", async () => {
    const client = makeClient({
      arm: vi.fn().mockRejectedValue(new Error("paper.arm failed: 503")),
    });
    render(<StatusPanel client={client} />);
    fireEvent.change(await screen.findByTestId("paper-arm-revision"), {
      target: { value: "rev-2" },
    });
    fireEvent.change(screen.getByTestId("paper-arm-balance"), {
      target: { value: "100" },
    });
    fireEvent.click(screen.getByRole("button", { name: /arm paper pack/i }));
    const unknown = await screen.findByTestId("paper-arm-unknown");
    expect(unknown.textContent).toMatch(/Arm outcome unknown/i);
    expect(unknown.textContent).toMatch(/503/);
    expect(screen.queryByTestId("paper-status-pack")).toBeNull();
    // No automatic retry: exactly one arm call.
    await waitFor(() => {
      expect(client.arm).toHaveBeenCalledTimes(1);
    });
  });
});

describe("StatusPanel-mounted Synthetic paper rehearsal tracer", () => {
  it("starts, pauses, resumes, exits and stops through the frozen command set with status readback", async () => {
    // A stateful fake backend: GET reflects exactly what the last
    // confirmed command set, the way the real service does.
    let current = rehearsalStatus();
    const rehearsal = makeRehearsalClient({
      getStatus: vi.fn().mockImplementation(() => Promise.resolve(current)),
      start: vi.fn().mockImplementation(() => {
        current = rehearsalStatus({ status: "running", cursor: 1 });
        return Promise.resolve(commandResult({ status: "running", cursor: 1 }));
      }),
      pause: vi.fn().mockImplementation(() => {
        current = rehearsalStatus({ status: "paused", cursor: 1 });
        return Promise.resolve(commandResult({ status: "paused", cursor: 1 }));
      }),
      resume: vi.fn().mockImplementation(() => {
        current = rehearsalStatus({ status: "running", cursor: 2 });
        return Promise.resolve(commandResult({ status: "running", cursor: 2 }));
      }),
      exit: vi.fn().mockImplementation(() => {
        current = rehearsalStatus({ status: "exited", cursor: 5 });
        return Promise.resolve(commandResult({ status: "exited", cursor: 5 }));
      }),
      stop: vi.fn().mockImplementation(() => {
        current = rehearsalStatus({ status: "stopped", cursor: 5 });
        return Promise.resolve(commandResult({ status: "stopped", cursor: 5 }));
      }),
    });
    const client = makeClient({
      createRehearsalClient: () => rehearsal,
    });
    render(<StatusPanel client={client} />);

    // Let the mount read land before asserting the idle projection.
    const panel = await screen.findByTestId("rehearsal-panel");
    await waitFor(() => {
      expect(panel.getAttribute("data-rehearsal-status")).toBe("idle");
    });
    // The panel is explicitly labeled synthetic/simulated.
    expect(panel.textContent ?? "").toMatch(/Synthetic paper rehearsal/i);
    expect(panel.textContent ?? "").toMatch(/simulated/i);
    expect(panel.getAttribute("data-rehearsal-status")).toBe("idle");

    fireEvent.click(screen.getByRole("button", { name: /start rehearsal/i }));
    await waitFor(() => {
      expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-status")).toBe("running");
    });

    fireEvent.click(screen.getByRole("button", { name: /pause rehearsal/i }));
    await waitFor(() => {
      expect(rehearsal.pause).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-status")).toBe("paused");
    });

    fireEvent.click(screen.getByRole("button", { name: /resume rehearsal/i }));
    await waitFor(() => {
      expect(rehearsal.resume).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-status")).toBe("running");
    });

    fireEvent.click(screen.getByRole("button", { name: /exit rehearsal/i }));
    await waitFor(() => {
      expect(rehearsal.exit).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-status")).toBe("exited");
    });

    // A fresh start after exit is a new user action.
    fireEvent.click(screen.getByRole("button", { name: /start rehearsal/i }));
    await waitFor(() => {
      expect(rehearsal.start).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-status")).toBe("running");
    });
    fireEvent.click(screen.getByRole("button", { name: /stop rehearsal/i }));
    await waitFor(() => {
      expect(rehearsal.stop).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-status")).toBe("stopped");
    });
  });

  it("disables every rehearsal command while one is pending", async () => {
    let resolveStart: (r: RehearsalCommandResult) => void = () => {};
    const gate = new Promise<RehearsalCommandResult>((resolve) => {
      resolveStart = resolve;
    });
    const rehearsal = makeRehearsalClient({
      start: vi.fn().mockReturnValue(gate),
    });
    const client = makeClient({ createRehearsalClient: () => rehearsal });
    render(<StatusPanel client={client} />);
    await screen.findByTestId("rehearsal-panel");

    fireEvent.click(screen.getByRole("button", { name: /start rehearsal/i }));
    await waitFor(() => {
      expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-pending")).toBe("start");
    });
    const stopButton = screen.queryByRole("button", { name: /stop rehearsal/i });
    expect(stopButton?.getAttribute("disabled")).toBe("");

    resolveStart(commandResult({ status: "running" }));
    await waitFor(() => {
      expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-pending")).toBe("");
    });
  });

  it("shows the backend cursor, fills, balances, position and stop state", async () => {
    const rehearsal = makeRehearsalClient({
      getStatus: vi.fn().mockResolvedValue(
        rehearsalStatus({
          status: "running",
          cursor: 7,
          total_bars: 20,
          balances: { USD: "984.25", SUI: "1.5" },
          position: "1.5",
          resting_stop: "0.42",
          recent_fills: [
            {
              coid: "c-1",
              side: "buy",
              qty: "1.5",
              price: "0.45",
              ts_ms: 1760000000000,
              kind: "fill",
            },
          ],
        }),
      ),
    });
    const client = makeClient({ createRehearsalClient: () => rehearsal });
    render(<StatusPanel client={client} />);
    await screen.findByTestId("rehearsal-panel");
    await waitFor(() => {
      expect(screen.getByTestId("rehearsal-cursor").textContent).toMatch(
        /Bar 7 of 20/,
      );
    });
    const panel = screen.getByTestId("rehearsal-panel");
    expect(panel.textContent ?? "").toMatch(/7/);
    expect(panel.textContent ?? "").toMatch(/20/);
    expect(panel.textContent ?? "").toMatch(/984\.25/);
    expect(panel.textContent ?? "").toMatch(/1\.5/);
    expect(panel.textContent ?? "").toMatch(/0\.42/);
    expect(panel.textContent ?? "").toMatch(/c-1/);
  });

  it("renders a refused rehearsal command honestly and keeps the last confirmed status", async () => {
    const rehearsal = makeRehearsalClient({
      start: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "rehearsal_not_idle",
        ok: false,
        message: "rehearsal already running",
      } satisfies RehearsalCommandResult),
    });
    const client = makeClient({ createRehearsalClient: () => rehearsal });
    render(<StatusPanel client={client} />);
    await screen.findByTestId("rehearsal-panel");
    fireEvent.click(screen.getByRole("button", { name: /start rehearsal/i }));
    const error = await screen.findByTestId("rehearsal-error");
    expect(error.textContent).toMatch(/rehearsal already running/);
    expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-status")).toBe("idle");
  });

  it("renders an unknown rehearsal outcome on transport failure without inventing a status", async () => {
    const rehearsal = makeRehearsalClient({
      stop: vi.fn().mockRejectedValue(new Error("rehearsal.stop failed: 500")),
    });
    const client = makeClient({ createRehearsalClient: () => rehearsal });
    render(<StatusPanel client={client} />);
    await screen.findByTestId("rehearsal-panel");
    fireEvent.click(screen.getByRole("button", { name: /stop rehearsal/i }));
    const unknown = await screen.findByTestId("rehearsal-unknown");
    expect(unknown.textContent).toMatch(/Stop outcome unknown/i);
    expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-status")).toBe("idle");
    expect(rehearsal.stop).toHaveBeenCalledTimes(1);
  });

  it("polls the backend while running and stops polling when the read fails", async () => {
    vi.useFakeTimers();
    try {
      const getStatus = vi
        .fn()
        // mount read: idle
        .mockResolvedValueOnce(rehearsalStatus())
        // poll reads while running
        .mockResolvedValueOnce(rehearsalStatus({ status: "running", cursor: 3 }))
        .mockResolvedValueOnce(rehearsalStatus({ status: "running", cursor: 4 }))
        .mockRejectedValueOnce(new Error("rehearsal status failed: 503"));
      const rehearsal = makeRehearsalClient({
        start: vi.fn().mockResolvedValue(commandResult({ status: "running", cursor: 3 })),
        getStatus,
      });
      const client = makeClient({ createRehearsalClient: () => rehearsal });
      render(<StatusPanel client={client} />);

      // With fake timers, RTL's findBy* polling never advances: flush
      // the mount read explicitly (repo pattern from OperationsView).
      const settle = async (ms = 0): Promise<void> => {
        await act(async () => {
          await vi.advanceTimersByTimeAsync(ms);
        });
      };
      await settle(1);
      const panel = screen.getByTestId("rehearsal-panel");
      expect(panel.getAttribute("data-rehearsal-status")).toBe("idle");

      fireEvent.click(screen.getByRole("button", { name: /start rehearsal/i }));
      await settle(1);
      expect(panel.getAttribute("data-rehearsal-status")).toBe("running");

      // Poll ticks land while running.
      await settle(1200);
      expect(getStatus.mock.calls.length).toBeGreaterThanOrEqual(1);
      await settle(1200);
      expect(getStatus.mock.calls.length).toBeGreaterThanOrEqual(2);

      // The failing read stops the loop and surfaces the failure; no
      // endless silent retry.
      await settle(1200);
      const callsAfterFailure = getStatus.mock.calls.length;
      await settle(5000);
      expect(getStatus.mock.calls.length).toBe(callsAfterFailure);
      expect(screen.getByTestId("rehearsal-unknown").textContent).toMatch(
        /Rehearsal status refresh failed/i,
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders the honest unavailable state when the injected client cannot create a rehearsal client", async () => {
    const client: PaperClient = {
      getStatus: vi.fn().mockResolvedValue(unarmed()),
      pauseEntries: vi.fn(),
      resumeEntries: vi.fn(),
      disarm: vi.fn(),
    };
    render(<StatusPanel client={client} />);
    expect(
      await screen.findByTestId("rehearsal-unavailable", {}, { timeout: 2000 }),
    ).toBeDefined();
  });
});
