import type { RehearsalStatus } from "./rehearsalClient";

/**
 * Pure view-model for the Synthetic paper rehearsal panel. The status
 * string is classified here so the UI never has to guess: only an
 * explicit backend status counts, and an unrecognized one is surfaced as
 * ``unknown`` rather than folded into a friendlier bucket.
 */

export type RehearsalLifecycle =
  | "idle"
  | "running"
  | "paused"
  | "exited"
  | "stopped"
  | "unknown";

export type RehearsalCommandName =
  | "start"
  | "pause"
  | "resume"
  | "exit"
  | "stop";

const LIFECYCLES: readonly RehearsalLifecycle[] = [
  "idle",
  "running",
  "paused",
  "exited",
  "stopped",
];

export function classifyRehearsalStatus(status: RehearsalStatus | null): RehearsalLifecycle {
  if (status === null) {
    return "unknown";
  }
  const value = status.status;
  return (LIFECYCLES as readonly string[]).includes(value)
    ? (value as RehearsalLifecycle)
    : "unknown";
}

/** True only while the backend says the loop is evaluating bars. */
export function isEvaluating(status: RehearsalStatus | null): boolean {
  return classifyRehearsalStatus(status) === "running";
}

/** A fresh start is a new run only from idle, exited or stopped. */
export function canStart(lifecycle: RehearsalLifecycle): boolean {
  return lifecycle === "idle" || lifecycle === "exited" || lifecycle === "stopped";
}

export function canPause(lifecycle: RehearsalLifecycle): boolean {
  return lifecycle === "running";
}

export function canResume(lifecycle: RehearsalLifecycle): boolean {
  return lifecycle === "paused";
}

/** Exit ends the run but keeps the rehearsal configured for a new start. */
export function canExit(lifecycle: RehearsalLifecycle): boolean {
  return lifecycle === "running" || lifecycle === "paused";
}

/** Stop is the hard halt: no further evaluation until a new start. */
export function canStop(lifecycle: RehearsalLifecycle): boolean {
  return lifecycle !== "stopped" && lifecycle !== "exited";
}

export function lifecycleSentence(lifecycle: RehearsalLifecycle): string {
  switch (lifecycle) {
    case "idle":
      return "Rehearsal idle — not started";
    case "running":
      return "Rehearsal running — evaluating simulated bars";
    case "paused":
      return "Rehearsal paused";
    case "exited":
      return "Rehearsal exited — start again for a new run";
    case "stopped":
      return "Rehearsal stopped — evaluation halted until a new start";
    default:
      return "Rehearsal status unknown";
  }
}

export type RehearsalBalances = {
  entries: { asset: string; amount: string }[];
};

export function rehearsalBalances(status: RehearsalStatus): RehearsalBalances {
  const entries = Object.entries(status.balances).map(([asset, amount]) => ({
    asset,
    amount,
  }));
  entries.sort((a, b) => a.asset.localeCompare(b.asset));
  return { entries };
}

/** e.g. "2026-10-09 12:00:00" in the viewer's local time, or "" never a fake. */
export function formatFillTs(tsMs: number): string {
  if (!Number.isFinite(tsMs) || tsMs <= 0) {
    return "";
  }
  const date = new Date(tsMs);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleString();
}

/** Progress copy that never claims completion the backend did not state. */
export function cursorSentence(status: RehearsalStatus): string {
  return `Bar ${status.cursor} of ${status.total_bars}`;
}

export function positionSentence(status: RehearsalStatus): string {
  return `Position ${status.position}`;
}

export function stopSentence(status: RehearsalStatus): string {
  return status.resting_stop === null
    ? "No resting stop"
    : `Resting stop ${status.resting_stop}`;
}
