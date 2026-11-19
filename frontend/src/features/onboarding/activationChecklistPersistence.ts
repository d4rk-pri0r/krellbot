/**
 * First-run activation checklist persistence (M25.4).
 *
 * Three items max; "Installed locally" is always done (unfinished-task pull).
 * Remaining items are persisted and also accept live facts from the shell.
 */

export const ACTIVATION_CHECKLIST_STORAGE_KEY =
  "krellbot.home.activationChecklist";

export type ActivationChecklistPersisted = {
  starterChosen: boolean;
  starterRevisionId?: string;
  starterLabel?: string;
  paperRunStarted: boolean;
};

export const DEFAULT_ACTIVATION_CHECKLIST_STATE: ActivationChecklistPersisted = {
  starterChosen: false,
  paperRunStarted: false,
};

export type ActivationChecklistItemId =
  | "installed"
  | "chose_starter"
  | "paper_run";

export type ActivationChecklistItem = {
  id: ActivationChecklistItemId;
  label: string;
  done: boolean;
};

export type ActivationChecklistFacts = {
  starterChosen?: boolean;
  paperRunStarted?: boolean;
  paperArmed?: boolean;
  statusVisible?: boolean;
};

function isPersisted(value: unknown): value is ActivationChecklistPersisted {
  if (!value || typeof value !== "object") {
    return false;
  }
  const record = value as ActivationChecklistPersisted;
  return (
    typeof record.starterChosen === "boolean" &&
    typeof record.paperRunStarted === "boolean"
  );
}

export function readActivationChecklistState(
  storageKey: string = ACTIVATION_CHECKLIST_STORAGE_KEY,
): ActivationChecklistPersisted {
  if (typeof window === "undefined") {
    return { ...DEFAULT_ACTIVATION_CHECKLIST_STATE };
  }
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      return { ...DEFAULT_ACTIVATION_CHECKLIST_STATE };
    }
    const parsed: unknown = JSON.parse(raw);
    if (!isPersisted(parsed)) {
      return { ...DEFAULT_ACTIVATION_CHECKLIST_STATE };
    }
    return {
      starterChosen: parsed.starterChosen,
      paperRunStarted: parsed.paperRunStarted,
      ...(typeof parsed.starterRevisionId === "string"
        ? { starterRevisionId: parsed.starterRevisionId }
        : {}),
      ...(typeof parsed.starterLabel === "string"
        ? { starterLabel: parsed.starterLabel }
        : {}),
    };
  } catch {
    return { ...DEFAULT_ACTIVATION_CHECKLIST_STATE };
  }
}

export function writeActivationChecklistState(
  next: ActivationChecklistPersisted,
  storageKey: string = ACTIVATION_CHECKLIST_STORAGE_KEY,
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

export function recordActivationStarterChosen(
  ready: { revisionId: string; label: string },
  storageKey: string = ACTIVATION_CHECKLIST_STORAGE_KEY,
): ActivationChecklistPersisted {
  const current = readActivationChecklistState(storageKey);
  const next: ActivationChecklistPersisted = {
    ...current,
    starterChosen: true,
    starterRevisionId: ready.revisionId,
    starterLabel: ready.label,
  };
  writeActivationChecklistState(next, storageKey);
  return next;
}

export function recordActivationPaperRunStarted(
  storageKey: string = ACTIVATION_CHECKLIST_STORAGE_KEY,
): ActivationChecklistPersisted {
  const current = readActivationChecklistState(storageKey);
  if (current.paperRunStarted) {
    return current;
  }
  const next: ActivationChecklistPersisted = {
    ...current,
    paperRunStarted: true,
  };
  writeActivationChecklistState(next, storageKey);
  return next;
}

/** Mark paper-run item when a confirmed armed status is visible. */
export function noteActivationPaperStatusVisible(
  armed: boolean,
  storageKey: string = ACTIVATION_CHECKLIST_STORAGE_KEY,
): ActivationChecklistPersisted {
  if (!armed) {
    return readActivationChecklistState(storageKey);
  }
  return recordActivationPaperRunStarted(storageKey);
}

export function deriveActivationChecklistItems(
  facts: ActivationChecklistFacts = {},
  storageKey: string = ACTIVATION_CHECKLIST_STORAGE_KEY,
): ReadonlyArray<ActivationChecklistItem> {
  const stored = readActivationChecklistState(storageKey);
  const starterDone =
    facts.starterChosen === true || stored.starterChosen === true;
  const paperDone =
    facts.paperRunStarted === true ||
    facts.paperArmed === true ||
    facts.statusVisible === true ||
    stored.paperRunStarted === true;

  return [
    {
      id: "installed",
      label: "Installed locally",
      done: true,
    },
    {
      id: "chose_starter",
      label: "Chose a free paper strategy",
      done: starterDone,
    },
    {
      id: "paper_run",
      label: "Started a paper run",
      done: paperDone,
    },
  ];
}

export function isActivationChecklistComplete(
  items: ReadonlyArray<ActivationChecklistItem> = deriveActivationChecklistItems(),
): boolean {
  return items.every((item) => item.done);
}
