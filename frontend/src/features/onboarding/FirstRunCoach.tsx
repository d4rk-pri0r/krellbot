import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  type CSSProperties,
  type JSX,
} from "react";
import {
  FIRST_RUN_COACH_STORAGE_KEY,
  isFirstRunCoachDismissed,
  readFirstRunCoachState,
  writeFirstRunCoachState,
  type FirstRunCoachPersisted,
  type FirstRunCoachStepId,
} from "./firstRunCoachPersistence";
import "./FirstRunCoach.signal.css";

export type FirstRunCoachStep = {
  id: FirstRunCoachStepId;
  title: string;
  body: string;
  /** Matches `[data-coach-anchor="<id>"]` for spotlight. */
  anchor?: string;
  primaryLabel: string;
};

export const DEFAULT_FIRST_RUN_STEPS: ReadonlyArray<FirstRunCoachStep> = [
  {
    id: "welcome",
    title: "Take the guided paper setup",
    body: "Pick a free starter, start a paper run, and see honest status — no exchange key.",
    primaryLabel: "Start",
  },
  {
    id: "choose_starter",
    title: "Choose a free paper strategy",
    body: "Use the sage button to open three plain starter cards.",
    anchor: "choose_starter",
    primaryLabel: "Open starters",
  },
  {
    id: "arm_paper",
    title: "Start your paper run",
    body: "Arm the strategy you picked with pretend money on this machine.",
    anchor: "arm_paper",
    primaryLabel: "Show Start paper run",
  },
  {
    id: "status",
    title: "Read honest status",
    body: "Armed, waiting, or paper-only — never invented live performance.",
    anchor: "status",
    primaryLabel: "Continue",
  },
  {
    id: "win",
    title: "Paper run is live on this computer",
    body: "You can pause or stop from Run anytime. The guide stays out of the way now.",
    primaryLabel: "Done",
  },
];

export type FirstRunCoachProps = {
  storageKey?: string;
  steps?: ReadonlyArray<FirstRunCoachStep>;
  /** Document/root used to find `[data-coach-anchor]`. */
  root?: ParentNode | Document | null;
  /**
   * When true, show even if persisted as skipped (tests / explicit resume).
   * Completed stays hidden unless forceShow is set.
   */
  forceShow?: boolean;
  onStepChange?: (stepId: FirstRunCoachStepId) => void;
  onSkip?: () => void;
  onComplete?: () => void;
  /**
   * Fired when the step primary is pressed. Return false to keep the step
   * (M25.3 wiring can advance only after the real action).
   */
  onPrimaryAction?: (stepId: FirstRunCoachStepId) => boolean | void;
  /**
   * When this value changes, re-read persisted coach state (external
   * advances from starter ready / paper arm).
   */
  syncKey?: number | string;
};

type SpotlightBox = {
  top: number;
  left: number;
  width: number;
  height: number;
};

function stepIndexOf(
  steps: ReadonlyArray<FirstRunCoachStep>,
  stepId: FirstRunCoachStepId,
): number {
  const index = steps.findIndex((step) => step.id === stepId);
  return index < 0 ? 0 : index;
}

/**
 * Interactive first-run coach shell (M25.2): spotlight one control, step
 * chrome, Skip guide after open, persist skip/complete so power users are
 * never re-trapped. Signal tokens only (KRELL-SIGNAL-20261010).
 */
export function FirstRunCoach({
  storageKey = FIRST_RUN_COACH_STORAGE_KEY,
  steps = DEFAULT_FIRST_RUN_STEPS,
  root = typeof document !== "undefined" ? document : null,
  forceShow = false,
  onStepChange,
  onSkip,
  onComplete,
  onPrimaryAction,
  syncKey = 0,
}: FirstRunCoachProps): JSX.Element | null {
  const [state, setState] = useState<FirstRunCoachPersisted>(() =>
    readFirstRunCoachState(storageKey),
  );
  const [spotlight, setSpotlight] = useState<SpotlightBox | null>(null);

  useEffect(() => {
    setState(readFirstRunCoachState(storageKey));
  }, [storageKey, syncKey]);

  const persist = useCallback(
    (next: FirstRunCoachPersisted) => {
      writeFirstRunCoachState(next, storageKey);
      setState(next);
    },
    [storageKey],
  );

  const dismissed = isFirstRunCoachDismissed(state);
  const visible = forceShow || !dismissed;

  const activeStep = useMemo(() => {
    const index = stepIndexOf(steps, state.stepId);
    return steps[index] ?? steps[0]!;
  }, [steps, state.stepId]);

  const measureSpotlight = useCallback(() => {
    const anchor = activeStep.anchor;
    if (!anchor || !root) {
      setSpotlight(null);
      return;
    }
    const safeAnchor = anchor.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    const el = root.querySelector(`[data-coach-anchor="${safeAnchor}"]`);
    if (!(el instanceof HTMLElement)) {
      setSpotlight(null);
      return;
    }
    const rect = el.getBoundingClientRect();
    setSpotlight({
      top: rect.top + window.scrollY - 6,
      left: rect.left + window.scrollX - 6,
      width: rect.width + 12,
      height: rect.height + 12,
    });
  }, [activeStep.anchor, root]);

  useLayoutEffect(() => {
    if (!visible) {
      setSpotlight(null);
      return;
    }
    measureSpotlight();
    window.addEventListener("resize", measureSpotlight);
    window.addEventListener("scroll", measureSpotlight, true);
    return () => {
      window.removeEventListener("resize", measureSpotlight);
      window.removeEventListener("scroll", measureSpotlight, true);
    };
  }, [visible, measureSpotlight, state.stepId]);

  useEffect(() => {
    if (!visible) {
      return;
    }
    onStepChange?.(activeStep.id);
  }, [activeStep.id, onStepChange, visible]);

  if (!visible) {
    return null;
  }

  const showSkip = state.status === "active" || state.stepId !== "welcome";
  const stepNumber = stepIndexOf(steps, activeStep.id) + 1;

  function handleStartOrAdvance(): void {
    const gate = onPrimaryAction?.(activeStep.id);
    if (gate === false) {
      return;
    }
    if (activeStep.id === "welcome") {
      const next: FirstRunCoachPersisted = {
        status: "active",
        stepId: "choose_starter",
      };
      persist(next);
      return;
    }
    if (activeStep.id === "win") {
      persist({ status: "completed", stepId: "win" });
      onComplete?.();
      return;
    }
    const index = stepIndexOf(steps, activeStep.id);
    const nextStep = steps[index + 1];
    if (!nextStep) {
      persist({ status: "completed", stepId: "win" });
      onComplete?.();
      return;
    }
    persist({ status: "active", stepId: nextStep.id });
  }

  function handleSkip(): void {
    persist({ status: "skipped", stepId: activeStep.id });
    onSkip?.();
  }

  /** Public advance for M25.3 wiring (real CTA / arm / status). */
  // Exported via imperative pattern below — also callable through primary.

  const spotlightStyle: CSSProperties | undefined = spotlight
    ? {
        top: spotlight.top,
        left: spotlight.left,
        width: spotlight.width,
        height: spotlight.height,
      }
    : undefined;

  return (
    <div
      className="kbot-first-run-coach"
      data-testid="first-run-coach"
      data-coach-status={state.status}
      data-coach-step={activeStep.id}
      role="dialog"
      aria-modal={activeStep.anchor ? true : undefined}
      aria-labelledby="kbot-first-run-coach-title"
    >
      {spotlight ? (
        <div
          className="kbot-first-run-coach__spotlight"
          data-testid="first-run-coach-spotlight"
          style={spotlightStyle}
          aria-hidden="true"
        />
      ) : null}
      <div
        className={
          activeStep.anchor
            ? "kbot-first-run-coach__scrim"
            : "kbot-first-run-coach__scrim kbot-first-run-coach__scrim--soft"
        }
        data-testid="first-run-coach-scrim"
        aria-hidden="true"
      />
      <div
        className={
          activeStep.id === "welcome" || activeStep.id === "win"
            ? "kbot-first-run-coach__card kbot-first-run-coach__card--center"
            : "kbot-first-run-coach__card"
        }
        data-testid="first-run-coach-card"
      >
        <p className="kbot-first-run-coach__progress" data-testid="first-run-coach-progress">
          Step {stepNumber} of {steps.length}
        </p>
        <h2
          id="kbot-first-run-coach-title"
          className="kbot-first-run-coach__title"
          data-testid="first-run-coach-title"
        >
          {activeStep.title}
        </h2>
        <p className="kbot-first-run-coach__body" data-testid="first-run-coach-body">
          {activeStep.body}
        </p>
        <div className="kbot-first-run-coach__actions">
          <button
            type="button"
            className="kbot-first-run-coach__primary"
            data-testid="first-run-coach-primary"
            onClick={handleStartOrAdvance}
          >
            {activeStep.primaryLabel}
          </button>
          {showSkip ? (
            <button
              type="button"
              className="kbot-first-run-coach__skip"
              data-testid="first-run-coach-skip"
              onClick={handleSkip}
            >
              Skip guide
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/** Advance the persisted coach to a step (wiring helper for M25.3). */
export function advanceFirstRunCoachTo(
  stepId: FirstRunCoachStepId,
  storageKey: string = FIRST_RUN_COACH_STORAGE_KEY,
): FirstRunCoachPersisted {
  const next: FirstRunCoachPersisted = {
    status: stepId === "win" ? "completed" : "active",
    stepId,
  };
  writeFirstRunCoachState(next, storageKey);
  return next;
}

export function skipFirstRunCoach(
  storageKey: string = FIRST_RUN_COACH_STORAGE_KEY,
): FirstRunCoachPersisted {
  const current = readFirstRunCoachState(storageKey);
  const next: FirstRunCoachPersisted = {
    status: "skipped",
    stepId: current.stepId,
  };
  writeFirstRunCoachState(next, storageKey);
  return next;
}

export {
  DEFAULT_FIRST_RUN_COACH_STATE,
  FIRST_RUN_COACH_STORAGE_KEY,
  isFirstRunCoachDismissed,
  readFirstRunCoachState,
  resumeFirstRunCoachState,
  writeFirstRunCoachState,
} from "./firstRunCoachPersistence";
