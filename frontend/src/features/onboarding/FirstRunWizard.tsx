/**
 * Full-screen Krell first-run wizard shell (M26.3 / KRELL-SIGNAL-20261010).
 *
 * ≤5 steps; one visual; ≤1 short sentence; one big sage CTA; quiet Skip
 * setup after welcome; persist complete/skip so users are never re-trapped.
 * App gate (unmount WorkstationShell) is M26.4 — this component is mountable
 * alone. Paper-arm wiring is M26.5.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type JSX,
} from "react";
import {
  CONSUMER_STARTER_CARD_ORDER,
  CONSUMER_STARTER_CARDS,
} from "../strategies/consumerStarterCopy";
import {
  FIRST_RUN_WIZARD_STORAGE_KEY,
  isFirstRunWizardDismissed,
  readFirstRunWizardState,
  writeFirstRunWizardState,
  type FirstRunWizardPersisted,
  type FirstRunWizardStepId,
} from "./firstRunWizardPersistence";
import { WIZARD_STEP_VISUALS } from "./wizardAssets";
import "./FirstRunWizard.signal.css";

export type FirstRunWizardStep = {
  id: FirstRunWizardStepId;
  sentence: string;
  primaryLabel: string;
};

export const DEFAULT_FIRST_RUN_WIZARD_STEPS: ReadonlyArray<FirstRunWizardStep> =
  [
    {
      id: "welcome",
      sentence:
        "Let’s set up a pretend trading bot on this computer — no real money.",
      primaryLabel: "Let’s go",
    },
    {
      id: "choose",
      sentence: "Pick one free strategy to try.",
      primaryLabel: "Use",
    },
    {
      id: "start_paper",
      sentence:
        "Start it with pretend money so you can see how it behaves.",
      primaryLabel: "Start paper run",
    },
    {
      id: "status",
      sentence:
        "It’s running on this computer (paper only — not live trading).",
      primaryLabel: "Looks good",
    },
    {
      id: "win",
      sentence: "You’re set. Here’s your workspace.",
      primaryLabel: "Open Krellbot",
    },
  ];

export type FirstRunWizardProps = {
  storageKey?: string;
  steps?: ReadonlyArray<FirstRunWizardStep>;
  /**
   * When true, show even if persisted as skipped (tests / explicit resume).
   * Completed stays hidden unless forceShow is set.
   */
  forceShow?: boolean;
  onStepChange?: (stepId: FirstRunWizardStepId) => void;
  onSkip?: () => void;
  onComplete?: () => void;
  /**
   * Fired when the step primary is pressed. Return false to keep the step
   * (M26.5 wiring can advance only after the real action).
   */
  onPrimaryAction?: (stepId: FirstRunWizardStepId) => boolean | void;
  /**
   * Fired when a starter tile Use is pressed on the choose step.
   * Return false to keep the choose step (M26.5).
   */
  onSelectStarter?: (starterId: string) => boolean | void;
  /**
   * When this value changes, re-read persisted wizard state.
   */
  syncKey?: number | string;
};

function stepIndexOf(
  steps: ReadonlyArray<FirstRunWizardStep>,
  stepId: FirstRunWizardStepId,
): number {
  const index = steps.findIndex((step) => step.id === stepId);
  return index < 0 ? 0 : index;
}

export function FirstRunWizard({
  storageKey = FIRST_RUN_WIZARD_STORAGE_KEY,
  steps = DEFAULT_FIRST_RUN_WIZARD_STEPS,
  forceShow = false,
  onStepChange,
  onSkip,
  onComplete,
  onPrimaryAction,
  onSelectStarter,
  syncKey = 0,
}: FirstRunWizardProps): JSX.Element | null {
  const [state, setState] = useState<FirstRunWizardPersisted>(() =>
    readFirstRunWizardState(storageKey),
  );
  const [enterKey, setEnterKey] = useState(0);

  useEffect(() => {
    setState(readFirstRunWizardState(storageKey));
  }, [storageKey, syncKey]);

  const persist = useCallback(
    (next: FirstRunWizardPersisted) => {
      writeFirstRunWizardState(next, storageKey);
      setState(next);
      setEnterKey((key) => key + 1);
    },
    [storageKey],
  );

  const dismissed = isFirstRunWizardDismissed(state);
  const visible = forceShow || !dismissed;

  const activeStep = useMemo(() => {
    const index = stepIndexOf(steps, state.stepId);
    return steps[index] ?? steps[0]!;
  }, [steps, state.stepId]);

  useEffect(() => {
    if (!visible) {
      return;
    }
    onStepChange?.(activeStep.id);
  }, [activeStep.id, onStepChange, visible]);

  if (!visible) {
    return null;
  }

  const showSkip =
    state.status === "active" || activeStep.id !== "welcome";
  const visual = WIZARD_STEP_VISUALS[activeStep.id];
  const stepNumber = stepIndexOf(steps, activeStep.id) + 1;
  const isWin = activeStep.id === "win";

  function advanceTo(nextId: FirstRunWizardStepId): void {
    persist({
      status: "active",
      stepId: nextId,
      selectedStarterId: state.selectedStarterId ?? null,
    });
  }

  function handlePrimary(): void {
    const gate = onPrimaryAction?.(activeStep.id);
    if (gate === false) {
      return;
    }
    if (activeStep.id === "welcome") {
      persist({
        status: "active",
        stepId: "choose",
        selectedStarterId: null,
      });
      return;
    }
    if (activeStep.id === "win") {
      persist({
        status: "completed",
        stepId: "win",
        selectedStarterId: state.selectedStarterId ?? null,
      });
      onComplete?.();
      return;
    }
    // choose advances via tile Use; other steps advance linearly
    if (activeStep.id === "choose") {
      return;
    }
    const index = stepIndexOf(steps, activeStep.id);
    const nextStep = steps[index + 1];
    if (!nextStep) {
      persist({
        status: "completed",
        stepId: "win",
        selectedStarterId: state.selectedStarterId ?? null,
      });
      onComplete?.();
      return;
    }
    advanceTo(nextStep.id);
  }

  function handleSelectStarter(starterId: string): void {
    const gate = onSelectStarter?.(starterId);
    if (gate === false) {
      return;
    }
    persist({
      status: "active",
      stepId: "start_paper",
      selectedStarterId: starterId,
    });
  }

  function handleSkip(): void {
    persist({
      status: "skipped",
      stepId: activeStep.id,
      selectedStarterId: state.selectedStarterId ?? null,
    });
    onSkip?.();
  }

  return (
    <div
      className={
        isWin
          ? "kbot-first-run-wizard kbot-first-run-wizard--win"
          : "kbot-first-run-wizard"
      }
      data-testid="first-run-wizard"
      data-wizard-status={state.status}
      data-wizard-step={activeStep.id}
      role="dialog"
      aria-modal="true"
      aria-labelledby="kbot-first-run-wizard-sentence"
    >
      <div className="kbot-first-run-wizard__chrome">
        <div
          className="kbot-first-run-wizard__progress"
          data-testid="first-run-wizard-progress"
          aria-hidden="true"
        >
          {steps.map((step, index) => (
            <span
              key={step.id}
              className={
                index < stepNumber
                  ? "kbot-first-run-wizard__dot kbot-first-run-wizard__dot--on"
                  : "kbot-first-run-wizard__dot"
              }
              data-testid={`first-run-wizard-dot-${step.id}`}
            />
          ))}
        </div>

        <div
          className="kbot-first-run-wizard__stage"
          key={`${activeStep.id}-${enterKey}`}
          data-testid="first-run-wizard-stage"
        >
          <img
            className="kbot-first-run-wizard__visual"
            data-testid="first-run-wizard-visual"
            data-wizard-visual={visual.name}
            src={visual.src}
            alt=""
          />

          <p
            id="kbot-first-run-wizard-sentence"
            className="kbot-first-run-wizard__sentence"
            data-testid="first-run-wizard-sentence"
          >
            {activeStep.sentence}
          </p>

          {activeStep.id === "choose" ? (
            <ul
              className="kbot-first-run-wizard__tiles"
              data-testid="first-run-wizard-tiles"
            >
              {CONSUMER_STARTER_CARD_ORDER.map((id) => {
                const card = CONSUMER_STARTER_CARDS[id]!;
                return (
                  <li key={id} className="kbot-first-run-wizard__tile">
                    <p className="kbot-first-run-wizard__tile-title">
                      {card.title}
                    </p>
                    <button
                      type="button"
                      className="kbot-first-run-wizard__primary"
                      data-testid={`first-run-wizard-use-${id}`}
                      onClick={() => handleSelectStarter(id)}
                    >
                      Use
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <button
              type="button"
              className="kbot-first-run-wizard__primary"
              data-testid="first-run-wizard-primary"
              onClick={handlePrimary}
            >
              {activeStep.primaryLabel}
            </button>
          )}

          {showSkip ? (
            <button
              type="button"
              className="kbot-first-run-wizard__skip"
              data-testid="first-run-wizard-skip"
              onClick={handleSkip}
            >
              Skip setup
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export {
  DEFAULT_FIRST_RUN_WIZARD_STATE,
  FIRST_RUN_WIZARD_STORAGE_KEY,
  isFirstRunWizardDismissed,
  readFirstRunWizardState,
  writeFirstRunWizardState,
} from "./firstRunWizardPersistence";
