import { useEffect, useState, type JSX } from "react";
import {
  ACTIVATION_CHECKLIST_STORAGE_KEY,
  deriveActivationChecklistItems,
  isActivationChecklistComplete,
  noteActivationPaperStatusVisible,
  recordActivationPaperRunStarted,
  recordActivationStarterChosen,
  type ActivationChecklistFacts,
  type ActivationChecklistItem,
} from "./activationChecklistPersistence";
import "./ActivationChecklist.signal.css";

export type ActivationChecklistProps = {
  storageKey?: string;
  /** Live facts merge over persisted progress. */
  facts?: ActivationChecklistFacts;
  /**
   * When true, render nothing so an active FirstRunCoach step owns the
   * chrome (checklist **or** coach — not both competing).
   */
  suppressed?: boolean;
  /** Incomplete setup: reopen coach / guided path. */
  onResumeSetup?: () => void;
  /** Optional heading override (AppHome keeps “Your next steps”). */
  title?: string;
  /** Compact lede; omit for a tighter strip. */
  lede?: string | null;
  className?: string;
  "data-testid"?: string;
};

function itemsEqual(
  left: ReadonlyArray<ActivationChecklistItem>,
  right: ReadonlyArray<ActivationChecklistItem>,
): boolean {
  if (left.length !== right.length) {
    return false;
  }
  return left.every(
    (item, index) =>
      item.id === right[index]?.id && item.done === right[index]?.done,
  );
}

/**
 * Compact ≤3-item activation checklist (M25.4): one pre-checked
 * (“Installed locally”), persist progress, tie remaining items to real
 * starter / paper-run state. Signal tokens only (KRELL-SIGNAL-20261010).
 */
export function ActivationChecklist({
  storageKey = ACTIVATION_CHECKLIST_STORAGE_KEY,
  facts,
  suppressed = false,
  onResumeSetup,
  title = "Your next steps",
  lede = "Choose a free strategy, start a paper run, and watch status on this machine.",
  className,
  "data-testid": testId = "activation-checklist",
}: ActivationChecklistProps): JSX.Element | null {
  const [items, setItems] = useState<ReadonlyArray<ActivationChecklistItem>>(
    () => deriveActivationChecklistItems(facts, storageKey),
  );

  useEffect(() => {
    const next = deriveActivationChecklistItems(facts, storageKey);
    setItems((current) => (itemsEqual(current, next) ? current : next));
  }, [facts, storageKey]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    function sync(): void {
      const next = deriveActivationChecklistItems(facts, storageKey);
      setItems((current) => (itemsEqual(current, next) ? current : next));
    }
    window.addEventListener("storage", sync);
    window.addEventListener("krellbot:activation-checklist", sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener("krellbot:activation-checklist", sync);
    };
  }, [facts, storageKey]);

  if (suppressed) {
    return null;
  }

  const complete = isActivationChecklistComplete(items);
  const showResume = !complete && typeof onResumeSetup === "function";
  const titleId = `${testId}-title`;

  return (
    <section
      className={
        className
          ? `kbot-activation-checklist ${className}`
          : "kbot-activation-checklist"
      }
      data-testid={testId}
      data-complete={complete ? "1" : "0"}
      aria-labelledby={titleId}
      role="region"
    >
      <h2 className="kbot-activation-checklist__title" id={titleId}>
        {title}
      </h2>
      {lede ? (
        <p className="kbot-activation-checklist__lede" data-testid={`${testId}-lede`}>
          {lede}
        </p>
      ) : null}
      <ul className="kbot-activation-checklist__list" data-testid={`${testId}-list`}>
        {items.map((item) => (
          <li
            key={item.id}
            className="kbot-activation-checklist__item"
            data-testid={`${testId}-item-${item.id}`}
            data-done={item.done ? "1" : "0"}
            data-item-id={item.id}
          >
            <span
              className="kbot-activation-checklist__mark"
              aria-hidden="true"
              data-testid={`${testId}-mark-${item.id}`}
            >
              {item.done ? (
                <span className="kbot-activation-checklist__mark-glyph">✓</span>
              ) : null}
            </span>
            <p className="kbot-activation-checklist__label">{item.label}</p>
          </li>
        ))}
      </ul>
      {showResume ? (
        <button
          type="button"
          className="kbot-activation-checklist__resume"
          data-testid={`${testId}-resume`}
          onClick={onResumeSetup}
        >
          Resume setup
        </button>
      ) : null}
    </section>
  );
}

export {
  ACTIVATION_CHECKLIST_STORAGE_KEY,
  DEFAULT_ACTIVATION_CHECKLIST_STATE,
  deriveActivationChecklistItems,
  isActivationChecklistComplete,
  noteActivationPaperStatusVisible,
  readActivationChecklistState,
  recordActivationPaperRunStarted,
  recordActivationStarterChosen,
  writeActivationChecklistState,
} from "./activationChecklistPersistence";

/** Notify same-tab listeners after a persistence write. */
export function notifyActivationChecklistChanged(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new Event("krellbot:activation-checklist"));
}

export function markActivationStarterChosen(ready: {
  revisionId: string;
  label: string;
}): ReturnType<typeof recordActivationStarterChosen> {
  const next = recordActivationStarterChosen(ready);
  notifyActivationChecklistChanged();
  return next;
}

export function markActivationPaperRunStarted(): ReturnType<
  typeof recordActivationPaperRunStarted
> {
  const next = recordActivationPaperRunStarted();
  notifyActivationChecklistChanged();
  return next;
}

export function markActivationPaperStatusVisible(
  armed: boolean,
): ReturnType<typeof noteActivationPaperStatusVisible> {
  const next = noteActivationPaperStatusVisible(armed);
  if (armed) {
    notifyActivationChecklistChanged();
  }
  return next;
}
