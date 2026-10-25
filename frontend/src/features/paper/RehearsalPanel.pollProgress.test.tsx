/**
 * RehearsalPanel — automatic poll progress under finite slow reads.
 *
 * Reported defect (issue 152): while the rehearsal loop is running, the
 * 1000ms poll interval started another getStatus() read and bumped the
 * epoch before a previous read slower than the interval (e.g. 1500ms)
 * completed. Every such completion — successful lifecycle/cursor/fills
 * updates AND completed failures — was discarded by the epoch guard, so
 * the panel showed a stale running status forever, the intended
 * "refresh failed" warning never appeared, and overlapping requests
 * kept accumulating one per tick.
 *
 * Transport note: every client here is an in-memory vi.fn() fake with
 * explicitly SYNTHETIC finite-latency responses driven by JSDOM fake
 * timers, standing in for the production loopback client
 * (createRehearsalHttpClient → GET /api/v1/rehearsal/status); the
 * production mount is StatusPanel. Only the transport boundary is
 * scripted — the mounted component, reducer and timing behavior are
 * the real shipped code. This is not real browser/backend acceptance.
 *
 * Covered behaviors:
 *  - several reads slower than the interval still make progress
 *    (lifecycle, cursor and fills), with no growing overlapping
 *    request stream: at most one active automatic poll at a time;
 *  - a slow failing read lands its truthful warning and stops the
 *    automatic poll (no endless silent retry);
 *  - a fast-read control keeps the ordinary sub-interval polling
 *    cadence working;
 *  - explicit reconciliation (manual Refresh status) recovers polling
 *    after a failed read stopped it;
 *  - commands and manual Refresh keep precedence over old polls: an
 *    obsolete slow poll result never rolls back command/readback state
 *    or clears newer intent;
 *  - Pause/Stop/Exit stay promptly usable while a poll read is slow
 *    (the poll busy flag never blocks commands and the interval stays
 *    at 1000ms);
 *  - unmount and client-change lifetime cleanup.
 */

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { RehearsalPanel } from "./RehearsalPanel";
import type {
  RehearsalClient,
  RehearsalCommandResult,
  RehearsalStatus,
} from "./rehearsalClient";

afterEach(cleanup);

const POLL_INTERVAL_MS = 1000;

/* ------------------------------------------------------------------ */
/* Synthetic fixtures (clearly labeled, in-memory only)                */
/* ------------------------------------------------------------------ */

function rehearsalStatusFixture(
  extra: Partial<RehearsalStatus> = {},
): RehearsalStatus {
  return {
    schema_version: "1",
    label: "SYNTHETIC PAPER REHEARSAL — simulated fixture, not market data",
    status: "running",
    cursor: 1,
    total_bars: 20,
    balances: { USD: "1000" },
    position: "0",
    resting_stop: null,
    recent_fills: [],
    ...extra,
  };
}

type ScriptedRead = {
  /** Finite synthetic latency in ms for this one transport read. */
  delay: number;
  status?: RehearsalStatus;
  error?: Error;
};

/**
 * A fake rehearsal client whose getStatus resolves/rejects after an
 * explicit finite delay under fake timers. The first scripted read is
 * the mount read; later reads (poll, manual refresh, command
 * follow-ups) consume the queue in order, repeating the last entry.
 */
function scriptedLatencyClient(
  reads: ScriptedRead[],
  commands: Partial<RehearsalClient> = {},
): RehearsalClient & { getStatus: Mock } {
  let index = 0;
  const getStatus = vi.fn().mockImplementation((): Promise<RehearsalStatus> => {
    const step = reads[Math.min(index, reads.length - 1)];
    index += 1;
    return new Promise<RehearsalStatus>((resolve, reject) => {
      setTimeout(() => {
        if (step.error !== undefined) {
          reject(step.error);
        } else {
          resolve(step.status ?? rehearsalStatusFixture());
        }
      }, step.delay);
    });
  });
  return {
    start: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    exit: vi.fn(),
    stop: vi.fn(),
    ...commands,
    getStatus,
  };
}

/* ------------------------------------------------------------------ */
/* Fake-timer helpers (repo pattern from StatusPanel.arm.test.tsx)     */
/* ------------------------------------------------------------------ */

async function settle(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

const panel = () => screen.getByTestId("rehearsal-panel");
const cursorText = () => screen.getByTestId("rehearsal-cursor").textContent;
const fillRowCount = () => screen.queryAllByTestId("rehearsal-fill").length;
const commandButton = (name: string) =>
  screen.getByTestId(`rehearsal-command-${name}`) as HTMLButtonElement;

async function renderRunning(
  client: RehearsalClient,
): Promise<void> {
  render(<RehearsalPanel client={client} />);
  await settle(50);
  expect(panel().getAttribute("data-rehearsal-status")).toBe("running");
}

/* ------------------------------------------------------------------ */
/* Cases                                                               */
/* ------------------------------------------------------------------ */

describe("rehearsal poll progress under finite slow reads", () => {
  it("makes progress across several reads slower than the interval with one active poll at a time", async () => {
    vi.useFakeTimers();
    try {
      const client = scriptedLatencyClient([
        // Mount read: fast, running at bar 1.
        { delay: 50, status: rehearsalStatusFixture() },
        // Three poll reads, each slower than the 1000ms interval.
        {
          delay: 1500,
          status: rehearsalStatusFixture({
            cursor: 2,
            recent_fills: [
              {
                coid: "coid-slow-2",
                side: "buy",
                qty: "1.25",
                price: "0.5",
                ts_ms: Date.UTC(2026, 9, 7, 9, 30, 5),
                kind: "fill",
              },
            ],
          }),
        },
        { delay: 1500, status: rehearsalStatusFixture({ cursor: 3 }) },
        { delay: 1500, status: rehearsalStatusFixture({ cursor: 4 }) },
        // Tail (must never be reached by a healthy poll loop here).
        { delay: 1500, status: rehearsalStatusFixture({ cursor: 99 }) },
      ]);
      await renderRunning(client);
      const getStatus = client.getStatus;
      expect(getStatus).toHaveBeenCalledTimes(1);
      expect(cursorText()).toBe("Bar 1 of 20");
      expect(fillRowCount()).toBe(0);

      // t=1050: first tick starts poll read #1 (completes at t=2550).
      await settle(1000);
      expect(getStatus).toHaveBeenCalledTimes(2);
      expect(cursorText()).toBe("Bar 1 of 20");

      // t=2050: the tick fires while read #1 is still in flight. It
      // must not start another read and must not invalidate #1.
      await settle(1000);
      expect(getStatus).toHaveBeenCalledTimes(2);

      // t=2550: the slow read completes and lands.
      await settle(500);
      expect(cursorText()).toBe("Bar 2 of 20");
      expect(fillRowCount()).toBe(1);
      expect(panel().getAttribute("data-rehearsal-status")).toBe("running");

      // t=3050..6550: two more slower-than-interval reads, same rule.
      await settle(500);
      expect(getStatus).toHaveBeenCalledTimes(3);
      await settle(1000);
      expect(getStatus).toHaveBeenCalledTimes(3);
      await settle(500);
      expect(cursorText()).toBe("Bar 3 of 20");
      await settle(500);
      expect(getStatus).toHaveBeenCalledTimes(4);
      await settle(1500);
      expect(cursorText()).toBe("Bar 4 of 20");

      // After ~6.5s of running with 1500ms reads: exactly the mount
      // read plus three poll reads — no growing overlap stream.
      expect(getStatus).toHaveBeenCalledTimes(4);
    } finally {
      vi.useRealTimers();
    }
  });

  it("lands a slow failing read as the truthful warning and stops the automatic poll", async () => {
    vi.useFakeTimers();
    try {
      const client = scriptedLatencyClient([
        { delay: 50, status: rehearsalStatusFixture() },
        { delay: 1500, error: new Error("rehearsal status failed: 503") },
      ]);
      await renderRunning(client);
      const getStatus = client.getStatus;

      // t=1050: the failing slow read starts; it rejects at t=2550.
      await settle(1000);
      expect(getStatus).toHaveBeenCalledTimes(2);
      await settle(1000);
      // Still in flight at t=2050: no second overlapping read.
      expect(getStatus).toHaveBeenCalledTimes(2);

      // t=2550: the rejection lands — warning shown, last confirmed
      // running status kept, auto-poll stopped.
      await settle(500);
      const unknown = screen.getByTestId("rehearsal-unknown");
      expect(unknown.getAttribute("role")).toBe("alert");
      expect(unknown.textContent).toMatch(
        /Rehearsal status refresh failed: rehearsal status failed: 503/,
      );
      expect(unknown.textContent).toMatch(/refresh to reconcile/i);
      expect(panel().getAttribute("data-rehearsal-status")).toBe("running");
      expect(cursorText()).toBe("Bar 1 of 20");

      // Quiet window: no endless silent retry.
      await settle(5000);
      expect(getStatus).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps polling progress on the fast-read control (reads faster than the interval)", async () => {
    vi.useFakeTimers();
    try {
      const client = scriptedLatencyClient([
        { delay: 50, status: rehearsalStatusFixture() },
        { delay: 50, status: rehearsalStatusFixture({ cursor: 2 }) },
        { delay: 50, status: rehearsalStatusFixture({ cursor: 3 }) },
        { delay: 50, status: rehearsalStatusFixture({ cursor: 4 }) },
      ]);
      await renderRunning(client);
      const getStatus = client.getStatus;
      expect(cursorText()).toBe("Bar 1 of 20");

      // Each advance covers one tick plus the fast read's latency.
      await settle(1100);
      expect(getStatus).toHaveBeenCalledTimes(2);
      expect(cursorText()).toBe("Bar 2 of 20");

      await settle(1000);
      expect(getStatus).toHaveBeenCalledTimes(3);
      expect(cursorText()).toBe("Bar 3 of 20");

      await settle(1000);
      expect(getStatus).toHaveBeenCalledTimes(4);
      expect(cursorText()).toBe("Bar 4 of 20");
    } finally {
      vi.useRealTimers();
    }
  });

  it("recovers polling after an explicit reconciliation read succeeds", async () => {
    vi.useFakeTimers();
    try {
      const client = scriptedLatencyClient([
        { delay: 50, status: rehearsalStatusFixture() },
        // Slow failing poll read stops the automatic loop.
        { delay: 1500, error: new Error("rehearsal status failed: 503") },
        // Explicit manual Refresh reconciles quickly…
        { delay: 50, status: rehearsalStatusFixture({ cursor: 6 }) },
        // …and automatic polling recovers with slow reads again.
        { delay: 1500, status: rehearsalStatusFixture({ cursor: 7 }) },
        { delay: 1500, status: rehearsalStatusFixture({ cursor: 8 }) },
      ]);
      await renderRunning(client);
      const getStatus = client.getStatus;

      await settle(1000);
      expect(getStatus).toHaveBeenCalledTimes(2);
      await settle(1500);
      expect(screen.getByTestId("rehearsal-unknown")).toBeDefined();
      expect(getStatus).toHaveBeenCalledTimes(2);

      // Explicit reconciliation: the user refreshes manually.
      fireEvent.click(commandButton("refresh"));
      await settle(100);
      expect(getStatus).toHaveBeenCalledTimes(3);
      expect(cursorText()).toBe("Bar 6 of 20");
      // The stale warning is resolved by the confirmed read.
      expect(screen.queryByTestId("rehearsal-unknown")).toBeNull();
      expect(panel().getAttribute("data-rehearsal-status")).toBe("running");

      // The automatic poll resumes and slow reads make progress again.
      await settle(1000);
      expect(getStatus).toHaveBeenCalledTimes(4);
      expect(cursorText()).toBe("Bar 6 of 20");
      await settle(1500);
      expect(cursorText()).toBe("Bar 7 of 20");
      await settle(1000);
      expect(getStatus).toHaveBeenCalledTimes(5);
      expect(cursorText()).toBe("Bar 7 of 20");
      await settle(1000);
      expect(cursorText()).toBe("Bar 8 of 20");
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps manual Refresh authoritative over a slow poll read already in flight", async () => {
    vi.useFakeTimers();
    try {
      const client = scriptedLatencyClient([
        { delay: 50, status: rehearsalStatusFixture() },
        // Obsolete slow poll read; it would report bar 99 later.
        { delay: 1500, status: rehearsalStatusFixture({ cursor: 99 }) },
        // Manual refresh lands first, at bar 6.
        { delay: 50, status: rehearsalStatusFixture({ cursor: 6 }) },
        { delay: 1500, status: rehearsalStatusFixture({ cursor: 7 }) },
      ]);
      await renderRunning(client);
      const getStatus = client.getStatus;

      await settle(1000);
      expect(getStatus).toHaveBeenCalledTimes(2);
      expect(cursorText()).toBe("Bar 1 of 20");

      // Manual refresh wins over the in-flight slow poll read.
      fireEvent.click(commandButton("refresh"));
      await settle(100);
      expect(getStatus).toHaveBeenCalledTimes(3);
      expect(cursorText()).toBe("Bar 6 of 20");

      // The obsolete slow read completes at t=2550 and must not roll
      // the panel back to its stale bar 99 projection.
      await settle(1500);
      expect(cursorText()).toBe("Bar 6 of 20");
      expect(getStatus).toHaveBeenCalledTimes(3);
      expect(screen.queryByTestId("rehearsal-unknown")).toBeNull();
      expect(screen.queryByTestId("rehearsal-error")).toBeNull();

      // Polling continues normally afterwards.
      await settle(500);
      expect(getStatus).toHaveBeenCalledTimes(4);
      await settle(1500);
      expect(cursorText()).toBe("Bar 7 of 20");
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps Pause/Stop/Exit promptly usable while a poll read is slow and never lets the obsolete result roll back the command", async () => {
    vi.useFakeTimers();
    try {
      const pausedReadback: RehearsalCommandResult = {
        schema_version: "1",
        code: "ok",
        ok: true,
        message: "ok",
        status: rehearsalStatusFixture({ status: "paused", cursor: 5 }),
      };
      const pause = vi.fn().mockResolvedValue(pausedReadback);
      const client = scriptedLatencyClient(
        [
          { delay: 50, status: rehearsalStatusFixture() },
          // Slow poll read in flight when Pause is clicked; its late
          // success would claim running at bar 9.
          { delay: 1500, status: rehearsalStatusFixture({ cursor: 9 }) },
        ],
        { pause },
      );
      await renderRunning(client);
      const getStatus = client.getStatus;

      await settle(1000);
      expect(getStatus).toHaveBeenCalledTimes(2);

      // Risk-reduction commands stay enabled while the read is slow:
      // the poll's busy flag must not block commands or disable the
      // panel, and the interval itself stays at 1000ms.
      for (const name of ["pause", "stop", "exit"]) {
        expect(commandButton(name).disabled).toBe(false);
        expect(commandButton(name).hasAttribute("aria-busy")).toBe(false);
      }
      expect(POLL_INTERVAL_MS).toBe(1000);

      fireEvent.click(commandButton("pause"));
      expect(pause).toHaveBeenCalledTimes(1);
      await settle(100);
      expect(panel().getAttribute("data-rehearsal-status")).toBe("paused");
      expect(cursorText()).toBe("Bar 5 of 20");

      // The obsolete slow poll read completes at t=2550: no rollback,
      // no fabricated warning or error, no automatic command retry.
      await settle(2000);
      expect(panel().getAttribute("data-rehearsal-status")).toBe("paused");
      expect(cursorText()).toBe("Bar 5 of 20");
      expect(screen.queryByTestId("rehearsal-unknown")).toBeNull();
      expect(screen.queryByTestId("rehearsal-error")).toBeNull();
      expect(pause).toHaveBeenCalledTimes(1);
      expect(getStatus).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops poll reads on unmount and settles the in-flight read without state updates", async () => {
    vi.useFakeTimers();
    try {
      const client = scriptedLatencyClient([
        { delay: 50, status: rehearsalStatusFixture() },
        { delay: 1500, status: rehearsalStatusFixture({ cursor: 2 }) },
      ]);
      const { container } = render(<RehearsalPanel client={client} />);
      await settle(50);
      await settle(1000);
      const getStatus = client.getStatus;
      expect(getStatus).toHaveBeenCalledTimes(2);

      // Unmount while the slow poll read is still in flight.
      cleanup();
      expect(container.textContent ?? "").toBe("");

      // No further reads are issued and the in-flight completion at
      // t=2550 is discarded without touching unmounted state.
      await settle(5000);
      expect(getStatus).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("invalidates slow poll reads from a replaced client without corrupting the new client's state", async () => {
    vi.useFakeTimers();
    try {
      const first = scriptedLatencyClient([
        { delay: 50, status: rehearsalStatusFixture() },
        // Slow poll read from the replaced client; would claim bar 99.
        { delay: 1500, status: rehearsalStatusFixture({ cursor: 99 }) },
      ]);
      const second = scriptedLatencyClient([
        { delay: 50, status: rehearsalStatusFixture({ status: "paused", cursor: 3 }) },
      ]);
      const view = render(<RehearsalPanel client={first} />);
      await settle(50);
      await settle(1000);
      expect(first.getStatus).toHaveBeenCalledTimes(2);

      // Client identity changes while the old poll read is in flight.
      view.rerender(<RehearsalPanel client={second} />);
      await settle(100);
      expect(panel().getAttribute("data-rehearsal-status")).toBe("paused");
      expect(cursorText()).toBe("Bar 3 of 20");
      expect(second.getStatus).toHaveBeenCalledTimes(1);

      // The obsolete read completes at t=2550 and is discarded.
      await settle(2000);
      expect(panel().getAttribute("data-rehearsal-status")).toBe("paused");
      expect(cursorText()).toBe("Bar 3 of 20");
      expect(panel().textContent ?? "").not.toContain("99");
      expect(first.getStatus).toHaveBeenCalledTimes(2);
      expect(second.getStatus).toHaveBeenCalledTimes(1);
      expect(screen.queryByTestId("rehearsal-unknown")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
