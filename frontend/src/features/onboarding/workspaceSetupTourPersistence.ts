/**
 * Workspace setup tour persistence (KRELL-SIGNAL-20261010).
 *
 * The tour arms only when the intro wizard is finished or skipped. Skip
 * and complete survive reloads so the cockpit is never re-trapped.
 * Idle (the default) stays hidden, including shell renders that never
 * passed through the wizard.
 */

export const WORKSPACE_SETUP_TOUR_STORAGE_KEY = "krellbot.home.setupTour";

export const WORKSPACE_SETUP_TOUR_STEPS = [
  "workspace",
  "keys",
  "strategy",
  "run",
] as const;

export type WorkspaceSetupTourStepId =
  (typeof WORKSPACE_SETUP_TOUR_STEPS)[number];

export type WorkspaceSetupTourStatus =
  | "idle"
  | "active"
  | "skipped"
  | "completed";

export type WorkspaceSetupTourPersisted = {
  status: WorkspaceSetupTourStatus;
  stepId: WorkspaceSetupTourStepId;
};

export const DEFAULT_WORKSPACE_SETUP_TOUR_STATE: WorkspaceSetupTourPersisted =
  {
    status: "idle",
    stepId: "workspace",
  };

function isStepId(value: unknown): value is WorkspaceSetupTourStepId {
  return (
    typeof value === "string" &&
    (WORKSPACE_SETUP_TOUR_STEPS as ReadonlyArray<string>).includes(value)
  );
}

function isStatus(value: unknown): value is WorkspaceSetupTourStatus {
  return (
    value === "idle" ||
    value === "active" ||
    value === "skipped" ||
    value === "completed"
  );
}

export function readWorkspaceSetupTourState(
  storageKey: string = WORKSPACE_SETUP_TOUR_STORAGE_KEY,
): WorkspaceSetupTourPersisted {
  if (typeof window === "undefined") {
    return { ...DEFAULT_WORKSPACE_SETUP_TOUR_STATE };
  }
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      return { ...DEFAULT_WORKSPACE_SETUP_TOUR_STATE };
    }
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === "object" &&
      isStatus((parsed as WorkspaceSetupTourPersisted).status) &&
      isStepId((parsed as WorkspaceSetupTourPersisted).stepId)
    ) {
      return {
        status: (parsed as WorkspaceSetupTourPersisted).status,
        stepId: (parsed as WorkspaceSetupTourPersisted).stepId,
      };
    }
    return { ...DEFAULT_WORKSPACE_SETUP_TOUR_STATE };
  } catch {
    return { ...DEFAULT_WORKSPACE_SETUP_TOUR_STATE };
  }
}

export function writeWorkspaceSetupTourState(
  next: WorkspaceSetupTourPersisted,
  storageKey: string = WORKSPACE_SETUP_TOUR_STORAGE_KEY,
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

/** True only while a handoff or replay left the tour open. */
export function isWorkspaceSetupTourActive(
  state: WorkspaceSetupTourPersisted = readWorkspaceSetupTourState(),
): boolean {
  return state.status === "active";
}

/**
 * Arm the tour after the intro wizard exits. A prior skip or complete
 * stays dismissed so a later reload cannot trap the cockpit again.
 */
export function armWorkspaceSetupTour(
  storageKey: string = WORKSPACE_SETUP_TOUR_STORAGE_KEY,
): WorkspaceSetupTourPersisted {
  const current = readWorkspaceSetupTourState(storageKey);
  if (current.status === "skipped" || current.status === "completed") {
    return current;
  }
  const next: WorkspaceSetupTourPersisted = {
    status: "active",
    stepId: current.status === "active" ? current.stepId : "workspace",
  };
  writeWorkspaceSetupTourState(next, storageKey);
  return next;
}

/** Opt-in reopen from the workspace. Always starts at the first step. */
export function replayWorkspaceSetupTour(
  storageKey: string = WORKSPACE_SETUP_TOUR_STORAGE_KEY,
): WorkspaceSetupTourPersisted {
  const next: WorkspaceSetupTourPersisted = {
    status: "active",
    stepId: "workspace",
  };
  writeWorkspaceSetupTourState(next, storageKey);
  return next;
}

export function adjacentSetupTourStep(
  stepId: WorkspaceSetupTourStepId,
  direction: 1 | -1,
): WorkspaceSetupTourStepId {
  const index = WORKSPACE_SETUP_TOUR_STEPS.indexOf(stepId);
  const next = index + direction;
  if (next < 0 || next >= WORKSPACE_SETUP_TOUR_STEPS.length) {
    return stepId;
  }
  return WORKSPACE_SETUP_TOUR_STEPS[next] ?? stepId;
}
