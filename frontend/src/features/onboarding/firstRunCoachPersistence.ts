/**
 * First-run coach persistence (M25.2).
 *
 * Survives reloads so skip/complete never re-traps. Resume is opt-in for
 * incomplete setup (checklist) — not automatic after skip/complete.
 */

export const FIRST_RUN_COACH_STORAGE_KEY = "krellbot.home.firstRunCoach";

export type FirstRunCoachStatus =
  | "idle"
  | "active"
  | "skipped"
  | "completed";

export type FirstRunCoachStepId =
  | "welcome"
  | "choose_starter"
  | "arm_paper"
  | "status"
  | "win";

export type FirstRunCoachPersisted = {
  status: FirstRunCoachStatus;
  stepId: FirstRunCoachStepId;
};

export const DEFAULT_FIRST_RUN_COACH_STATE: FirstRunCoachPersisted = {
  status: "idle",
  stepId: "welcome",
};

const STEP_IDS: ReadonlySet<string> = new Set([
  "welcome",
  "choose_starter",
  "arm_paper",
  "status",
  "win",
]);

function isStepId(value: unknown): value is FirstRunCoachStepId {
  return typeof value === "string" && STEP_IDS.has(value);
}

function isStatus(value: unknown): value is FirstRunCoachStatus {
  return (
    value === "idle" ||
    value === "active" ||
    value === "skipped" ||
    value === "completed"
  );
}

export function readFirstRunCoachState(
  storageKey: string = FIRST_RUN_COACH_STORAGE_KEY,
): FirstRunCoachPersisted {
  if (typeof window === "undefined") {
    return { ...DEFAULT_FIRST_RUN_COACH_STATE };
  }
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      return { ...DEFAULT_FIRST_RUN_COACH_STATE };
    }
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === "object" &&
      isStatus((parsed as FirstRunCoachPersisted).status) &&
      isStepId((parsed as FirstRunCoachPersisted).stepId)
    ) {
      return {
        status: (parsed as FirstRunCoachPersisted).status,
        stepId: (parsed as FirstRunCoachPersisted).stepId,
      };
    }
    return { ...DEFAULT_FIRST_RUN_COACH_STATE };
  } catch {
    return { ...DEFAULT_FIRST_RUN_COACH_STATE };
  }
}

export function writeFirstRunCoachState(
  next: FirstRunCoachPersisted,
  storageKey: string = FIRST_RUN_COACH_STORAGE_KEY,
): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(next));
  } catch {
    // Best-effort only.
  }
}

/** Auto-show is suppressed after skip or complete. */
export function isFirstRunCoachDismissed(
  state: FirstRunCoachPersisted = readFirstRunCoachState(),
): boolean {
  return state.status === "skipped" || state.status === "completed";
}

/**
 * Opt-in reopen for incomplete setup (checklist). Does not reopen after
 * completed. May reopen after skipped when the caller explicitly resumes.
 */
export function resumeFirstRunCoachState(
  storageKey: string = FIRST_RUN_COACH_STORAGE_KEY,
): FirstRunCoachPersisted {
  const current = readFirstRunCoachState(storageKey);
  if (current.status === "completed") {
    return current;
  }
  const next: FirstRunCoachPersisted = {
    status: "active",
    stepId:
      current.stepId === "welcome" || current.stepId === "win"
        ? "choose_starter"
        : current.stepId,
  };
  writeFirstRunCoachState(next, storageKey);
  return next;
}
