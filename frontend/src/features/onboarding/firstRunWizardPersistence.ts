/**
 * First-run wizard persistence (M26.3).
 *
 * Survives reloads so complete/skip never re-traps. App gate mounting is
 * M26.4 — this module only owns the dismissed state for the shell.
 */

export const FIRST_RUN_WIZARD_STORAGE_KEY = "krellbot.home.firstRunWizard";

export type FirstRunWizardStatus =
  | "idle"
  | "active"
  | "skipped"
  | "completed";

export type FirstRunWizardStepId =
  | "welcome"
  | "choose"
  | "start_paper"
  | "status"
  | "win";

export type FirstRunWizardPersisted = {
  status: FirstRunWizardStatus;
  stepId: FirstRunWizardStepId;
  /** Consumer starter id chosen on step 2. */
  selectedStarterId?: string | null;
  /**
   * Draft revision from a successful starter validate. Omitted until the
   * paper clients save one, so older stub state stays unchanged.
   */
  revisionId?: string;
};

export const DEFAULT_FIRST_RUN_WIZARD_STATE: FirstRunWizardPersisted = {
  status: "idle",
  stepId: "welcome",
  selectedStarterId: null,
};

const STEP_IDS: ReadonlySet<string> = new Set([
  "welcome",
  "choose",
  "start_paper",
  "status",
  "win",
]);

function isStepId(value: unknown): value is FirstRunWizardStepId {
  return typeof value === "string" && STEP_IDS.has(value);
}

function isStatus(value: unknown): value is FirstRunWizardStatus {
  return (
    value === "idle" ||
    value === "active" ||
    value === "skipped" ||
    value === "completed"
  );
}

export function readFirstRunWizardState(
  storageKey: string = FIRST_RUN_WIZARD_STORAGE_KEY,
): FirstRunWizardPersisted {
  if (typeof window === "undefined") {
    return { ...DEFAULT_FIRST_RUN_WIZARD_STATE };
  }
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      return { ...DEFAULT_FIRST_RUN_WIZARD_STATE };
    }
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === "object" &&
      isStatus((parsed as FirstRunWizardPersisted).status) &&
      isStepId((parsed as FirstRunWizardPersisted).stepId)
    ) {
      const record = parsed as FirstRunWizardPersisted;
      const selected = record.selectedStarterId;
      const next: FirstRunWizardPersisted = {
        status: record.status,
        stepId: record.stepId,
        selectedStarterId:
          typeof selected === "string" || selected === null ? selected : null,
      };
      if (typeof record.revisionId === "string" && record.revisionId.length > 0) {
        next.revisionId = record.revisionId;
      }
      return next;
    }
    return { ...DEFAULT_FIRST_RUN_WIZARD_STATE };
  } catch {
    return { ...DEFAULT_FIRST_RUN_WIZARD_STATE };
  }
}

export function writeFirstRunWizardState(
  next: FirstRunWizardPersisted,
  storageKey: string = FIRST_RUN_WIZARD_STORAGE_KEY,
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
export function isFirstRunWizardDismissed(
  state: FirstRunWizardPersisted = readFirstRunWizardState(),
): boolean {
  return state.status === "skipped" || state.status === "completed";
}
