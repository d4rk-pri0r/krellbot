import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JobsDrawer, type JobRow } from "./JobsDrawer";

/**
 * Keyboard dismissal + focus recovery for the Jobs drawer (#jobs-escape).
 *
 * The drawer declares role="dialog" aria-modal="true", so an ordinary
 * unmodified, non-composing Escape pressed on the trigger (while open) or
 * inside the dialog must close it through the same close path as the visible
 * Close button and return real DOM focus to the Jobs trigger.
 *
 * Ownership is component-scoped: only Escape events whose target is the
 * trigger or an element inside the dialog are consumed. Modified, composing
 * or already-prevented events — and Escape owned by anything outside this
 * component — are left untouched. Every focus assertion reads
 * document.activeElement against an element that really holds DOM focus;
 * activeElement is never mocked.
 */

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => {};
  let reject: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function getTrigger(): HTMLElement {
  return screen.getByRole("button", { name: "Jobs" });
}

function isOpen(): boolean {
  return getTrigger().getAttribute("aria-expanded") === "true";
}

/** Opens the drawer by activating the trigger while it truly holds focus. */
function openFromFocusedTrigger(): HTMLElement {
  const trigger = getTrigger();
  trigger.focus();
  expect(document.activeElement).toBe(trigger);
  fireEvent.click(trigger);
  expect(isOpen()).toBe(true);
  return trigger;
}

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

/** A pending read so the drawer stays in its loading state. */
function pendingList(): { list: () => Promise<JobRow[]>; gate: Deferred<JobRow[]> } {
  const gate = deferred<JobRow[]>();
  const list = vi.fn().mockReturnValue(gate.promise);
  return { list, gate };
}

const JOB_1: JobRow = { id: "job-1", kind: "research.backtest", state: "succeeded" };
const JOB_2: JobRow = { id: "job-2", kind: "research.mro.sweep", state: "queued" };

/**
 * Dispatch a genuinely cancelable Escape keydown from a real focused owner,
 * inside act() so React flushes the resulting state update synchronously.
 * Returns whether the event ended up consumed (defaultPrevented), which is
 * only observable because the event is truly cancelable.
 */
function pressEscape(target: HTMLElement, init?: KeyboardEventInit): boolean {
  target.focus();
  expect(document.activeElement).toBe(target);
  const event = new KeyboardEvent("keydown", {
    key: "Escape",
    bubbles: true,
    cancelable: true,
    ...init,
  });
  let notConsumed = true;
  act(() => {
    notConsumed = target.dispatchEvent(event);
  });
  return !notConsumed;
}

/** A cancelable non-Escape keydown on a focused owner, reporting consumption. */
function pressKey(target: HTMLElement, key: string): boolean {
  target.focus();
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
  let notConsumed = true;
  act(() => {
    notConsumed = target.dispatchEvent(event);
  });
  return !notConsumed;
}

function assertClosedWithTriggerFocus(): void {
  expect(isOpen()).toBe(false);
  expect(screen.queryByTestId("kbot-jobs-dialog")).toBeNull();
  expect(document.activeElement).toBe(getTrigger());
}

describe("JobsDrawer Escape dismissal and focus recovery", () => {
  it("closes on Escape from the focused trigger and returns real focus to it", async () => {
    render(<JobsDrawer client={{ list: pendingList().list }} />);
    const trigger = openFromFocusedTrigger();
    await settle();
    expect(pressEscape(trigger)).toBe(true);
    assertClosedWithTriggerFocus();
  });

  it("closes on Escape while Refresh owns focus, restoring trigger focus", async () => {
    render(<JobsDrawer client={{ list: pendingList().list }} />);
    openFromFocusedTrigger();
    await settle();
    const refresh = screen.getByRole("button", { name: /refresh jobs/i });
    expect(pressEscape(refresh)).toBe(true);
    assertClosedWithTriggerFocus();
  });

  it("closes on Escape while the visible Close button owns focus, restoring trigger focus", async () => {
    render(<JobsDrawer client={{ list: pendingList().list }} />);
    openFromFocusedTrigger();
    await settle();
    const close = screen.getByRole("button", { name: /close jobs drawer/i });
    expect(pressEscape(close)).toBe(true);
    assertClosedWithTriggerFocus();
  });

  it("closes on Escape while a job row owns focus, restoring trigger focus", async () => {
    render(<JobsDrawer client={{ list: vi.fn().mockResolvedValue([JOB_1, JOB_2]) }} />);
    openFromFocusedTrigger();
    const row = await screen.findAllByTestId("job-row");
    const last = row[row.length - 1];
    if (!(last instanceof HTMLElement)) {
      throw new Error("job row missing");
    }
    last.focus();
    expect(document.activeElement).toBe(last);
    expect(pressEscape(last)).toBe(true);
    assertClosedWithTriggerFocus();
  });

  it("closes on Escape while the read is still loading, without waiting for it", async () => {
    const { list, gate } = pendingList();
    render(<JobsDrawer client={{ list }} />);
    openFromFocusedTrigger();
    expect(screen.getByTestId("jobs-loading").textContent).toMatch(/loading/i);
    const refresh = screen.getByRole("button", { name: /refresh jobs/i });
    expect(pressEscape(refresh)).toBe(true);
    assertClosedWithTriggerFocus();
    // The abandoned read resolving afterwards cannot resurrect the drawer.
    await act(async () => {
      gate.resolve([JOB_1]);
    });
    expect(screen.queryByTestId("kbot-jobs-dialog")).toBeNull();
    expect(screen.queryByTestId("job-row")).toBeNull();
  });

  it("closes on Escape from the error/retry state", async () => {
    const failing = vi.fn().mockRejectedValue(new Error("jobs failed: 503"));
    render(<JobsDrawer client={{ list: failing }} />);
    openFromFocusedTrigger();
    const alert = await screen.findByTestId("jobs-error");
    expect(alert.getAttribute("role")).toBe("alert");
    const retry = screen.getByRole("button", { name: /retry/i });
    expect(pressEscape(retry)).toBe(true);
    assertClosedWithTriggerFocus();
  });

  it("closes on Escape from the ready-empty state", async () => {
    render(<JobsDrawer client={{ list: vi.fn().mockResolvedValue([]) }} />);
    openFromFocusedTrigger();
    expect(await screen.findByTestId("jobs-empty")).not.toBeNull();
    // With no rows the CSV export button is disabled, so the ready-empty
    // state is exercised through its still-focusable toolbar controls.
    const refresh = screen.getByRole("button", { name: /refresh jobs/i });
    expect(pressEscape(refresh)).toBe(true);
    assertClosedWithTriggerFocus();
  });

  it("restores trigger focus when closing through the visible Close button", async () => {
    render(<JobsDrawer client={{ list: vi.fn().mockResolvedValue([JOB_1]) }} />);
    const trigger = openFromFocusedTrigger();
    await screen.findByTestId("job-row");
    const close = screen.getByRole("button", { name: /close jobs drawer/i });
    close.focus();
    expect(document.activeElement).toBe(close);
    fireEvent.click(close);
    expect(isOpen()).toBe(false);
    expect(screen.queryByTestId("kbot-jobs-dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("does not claim Escape while the drawer is closed", () => {
    render(<JobsDrawer client={{ list: vi.fn().mockResolvedValue([JOB_1]) }} />);
    const trigger = getTrigger();
    expect(isOpen()).toBe(false);
    expect(pressEscape(trigger)).toBe(false);
    expect(isOpen()).toBe(false);
    expect(document.activeElement).toBe(trigger);
  });

  it("does not consume Escape pressed with a modifier key", async () => {
    render(<JobsDrawer client={{ list: pendingList().list }} />);
    openFromFocusedTrigger();
    await settle();
    const close = screen.getByRole("button", { name: /close jobs drawer/i });
    for (const init of [
      { ctrlKey: true },
      { altKey: true },
      { metaKey: true },
      { shiftKey: true },
    ] as KeyboardEventInit[]) {
      expect(pressEscape(close, init)).toBe(false);
      expect(isOpen()).toBe(true);
      expect(screen.getByTestId("kbot-jobs-dialog")).not.toBeNull();
    }
  });

  it("does not consume a composing Escape (isComposing / keyCode 229)", async () => {
    render(<JobsDrawer client={{ list: pendingList().list }} />);
    openFromFocusedTrigger();
    await settle();
    const close = screen.getByRole("button", { name: /close jobs drawer/i });
    expect(pressEscape(close, { isComposing: true })).toBe(false);
    expect(isOpen()).toBe(true);
    expect(pressEscape(close, { keyCode: 229 })).toBe(false);
    expect(isOpen()).toBe(true);
    expect(screen.getByTestId("kbot-jobs-dialog")).not.toBeNull();
  });

  it("does not consume an Escape another handler already prevented", async () => {
    render(<JobsDrawer client={{ list: pendingList().list }} />);
    openFromFocusedTrigger();
    await settle();
    const close = screen.getByRole("button", { name: /close jobs drawer/i });
    close.focus();
    expect(document.activeElement).toBe(close);
    const event = new KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
      cancelable: true,
    });
    event.preventDefault();
    expect(event.defaultPrevented).toBe(true);
    act(() => {
      close.dispatchEvent(event);
    });
    expect(isOpen()).toBe(true);
    expect(screen.getByTestId("kbot-jobs-dialog")).not.toBeNull();
  });

  it("does not close for Escape owned by an element outside the Jobs trigger/dialog", async () => {
    render(
      <>
        <button type="button" id="outside-owner">
          Outside overlay control
        </button>
        <JobsDrawer client={{ list: pendingList().list }} />
      </>,
    );
    openFromFocusedTrigger();
    await settle();
    const outside = document.getElementById("outside-owner");
    if (!(outside instanceof HTMLElement)) {
      throw new Error("outside control missing");
    }
    expect(pressEscape(outside)).toBe(false);
    expect(isOpen()).toBe(true);
    expect(screen.getByTestId("kbot-jobs-dialog")).not.toBeNull();
  });

  it("does not claim unrelated keys pressed inside the dialog", async () => {
    render(<JobsDrawer client={{ list: pendingList().list }} />);
    openFromFocusedTrigger();
    await settle();
    const close = screen.getByRole("button", { name: /close jobs drawer/i });
    for (const key of ["Enter", "Tab", "ArrowDown", "a"]) {
      expect(pressKey(close, key)).toBe(false);
    }
    expect(isOpen()).toBe(true);
    expect(screen.getByTestId("kbot-jobs-dialog")).not.toBeNull();
  });

  it("reopens after Escape-close and performs a normal fresh read", async () => {
    const first = deferred<JobRow[]>();
    const second = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    render(<JobsDrawer client={{ list }} />);
    const trigger = openFromFocusedTrigger();
    expect(screen.getByTestId("jobs-loading").textContent).toMatch(/loading/i);
    expect(pressEscape(trigger)).toBe(true);
    assertClosedWithTriggerFocus();
    // A late resolution of the abandoned read cannot reopen or paint rows.
    await act(async () => {
      first.resolve([JOB_1]);
    });
    expect(screen.queryByTestId("kbot-jobs-dialog")).toBeNull();
    expect(screen.queryByTestId("job-row")).toBeNull();
    // Reopening from the (focused) trigger starts a new read.
    trigger.focus();
    fireEvent.click(trigger);
    expect(isOpen()).toBe(true);
    expect(screen.getByTestId("jobs-loading").textContent).toMatch(/loading/i);
    expect(list).toHaveBeenCalledTimes(2);
    await act(async () => {
      second.resolve([JOB_2]);
    });
    expect(screen.getAllByTestId("job-row").map((row) => row.textContent)).toEqual([
      "job-2 Research mro sweep (queued)",
    ]);
    expect(screen.queryByTestId("jobs-loading")).toBeNull();
  });

  it("keeps a late pending completion after Escape-close from overwriting the reopened drawer", async () => {
    const stale = deferred<JobRow[]>();
    const fresh = deferred<JobRow[]>();
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise);
    render(<JobsDrawer client={{ list }} />);
    const trigger = openFromFocusedTrigger();
    expect(pressEscape(trigger)).toBe(true);
    assertClosedWithTriggerFocus();
    trigger.focus();
    fireEvent.click(trigger);
    expect(isOpen()).toBe(true);
    // The stale read resolves after the close that abandoned it.
    await act(async () => {
      stale.resolve([JOB_1]);
    });
    expect(screen.queryByTestId("job-row")).toBeNull();
    expect(screen.getByTestId("jobs-loading").textContent).toMatch(/loading/i);
    await act(async () => {
      fresh.resolve([JOB_2]);
    });
    expect(screen.getAllByTestId("job-row").map((row) => row.textContent)).toEqual([
      "job-2 Research mro sweep (queued)",
    ]);
  });
});
