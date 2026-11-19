/**
 * Prior hotspot-coach skip/complete must not re-trap into the wizard.
 *
 * When the wizard key is absent and the coach record is skipped or
 * completed, write an equivalent wizard dismissal. An existing wizard
 * record wins. Idle or active coach does not dismiss the wizard.
 */
import {
  FIRST_RUN_COACH_STORAGE_KEY,
  isFirstRunCoachDismissed,
  readFirstRunCoachState,
} from "./firstRunCoachPersistence";
import {
  FIRST_RUN_WIZARD_STORAGE_KEY,
  writeFirstRunWizardState,
  type FirstRunWizardPersisted,
} from "./firstRunWizardPersistence";

export function adoptLegacyFirstRunDismissal(
  wizardKey: string = FIRST_RUN_WIZARD_STORAGE_KEY,
  coachKey: string = FIRST_RUN_COACH_STORAGE_KEY,
): FirstRunWizardPersisted | null {
  if (typeof window === "undefined") {
    return null;
  }
  let existing: string | null = null;
  try {
    existing = window.localStorage.getItem(wizardKey);
  } catch {
    return null;
  }
  if (existing !== null) {
    return null;
  }
  const coach = readFirstRunCoachState(coachKey);
  if (!isFirstRunCoachDismissed(coach)) {
    return null;
  }
  const next: FirstRunWizardPersisted = {
    status: coach.status === "completed" ? "completed" : "skipped",
    stepId: coach.status === "completed" ? "win" : "welcome",
    selectedStarterId: null,
  };
  writeFirstRunWizardState(next, wizardKey);
  return next;
}
