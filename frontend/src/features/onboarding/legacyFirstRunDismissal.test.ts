/**
 * Prior coach skip/complete dismisses the wizard so a returning install
 * never re-traps. Idle or active coach still owes the wizard.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  FIRST_RUN_COACH_STORAGE_KEY,
  writeFirstRunCoachState,
} from "./firstRunCoachPersistence";
import {
  FIRST_RUN_WIZARD_STORAGE_KEY,
  isFirstRunWizardDismissed,
  readFirstRunWizardState,
  writeFirstRunWizardState,
} from "./firstRunWizardPersistence";
import { adoptLegacyFirstRunDismissal } from "./legacyFirstRunMigration";

beforeEach(() => {
  window.localStorage.clear();
});

describe("prior coach skip or complete dismisses the wizard", () => {
  it("writes a skipped wizard when the coach was skipped and the wizard key is absent", () => {
    writeFirstRunCoachState(
      { status: "skipped", stepId: "choose_starter" },
      FIRST_RUN_COACH_STORAGE_KEY,
    );
    const adopted = adoptLegacyFirstRunDismissal();
    expect(adopted).toEqual({
      status: "skipped",
      stepId: "welcome",
      selectedStarterId: null,
    });
    expect(isFirstRunWizardDismissed()).toBe(true);
    expect(readFirstRunWizardState().status).toBe("skipped");
  });

  it("writes a completed wizard when the coach was completed", () => {
    writeFirstRunCoachState(
      { status: "completed", stepId: "win" },
      FIRST_RUN_COACH_STORAGE_KEY,
    );
    adoptLegacyFirstRunDismissal();
    expect(readFirstRunWizardState()).toEqual({
      status: "completed",
      stepId: "win",
      selectedStarterId: null,
    });
    expect(
      window.localStorage.getItem(FIRST_RUN_WIZARD_STORAGE_KEY),
    ).toMatch(/completed/);
  });

  it("leaves an in-progress wizard alone even if an older coach was skipped", () => {
    writeFirstRunWizardState({
      status: "active",
      stepId: "choose",
      selectedStarterId: "starter-sma-cross",
    });
    writeFirstRunCoachState({ status: "skipped", stepId: "welcome" });
    expect(adoptLegacyFirstRunDismissal()).toBeNull();
    expect(readFirstRunWizardState()).toEqual({
      status: "active",
      stepId: "choose",
      selectedStarterId: "starter-sma-cross",
    });
    expect(isFirstRunWizardDismissed()).toBe(false);
  });

  it("does not dismiss the wizard for an idle or active coach", () => {
    writeFirstRunCoachState({ status: "idle", stepId: "welcome" });
    expect(adoptLegacyFirstRunDismissal()).toBeNull();
    expect(readFirstRunWizardState().status).toBe("idle");
    expect(window.localStorage.getItem(FIRST_RUN_WIZARD_STORAGE_KEY)).toBeNull();

    writeFirstRunCoachState({ status: "active", stepId: "arm_paper" });
    expect(adoptLegacyFirstRunDismissal()).toBeNull();
    expect(isFirstRunWizardDismissed()).toBe(false);
  });
});
