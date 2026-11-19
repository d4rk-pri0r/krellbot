/**
 * Brief first-win celebrate toast (M25.8 / KRELL-SIGNAL-20261010).
 *
 * Shown once after the first successful paper arm. Auto-dismisses; never
 * re-traps. No soft Studio tips — silence after.
 */
import { useEffect, type JSX } from "react";
import "./FirstWinCelebrate.signal.css";

export const FIRST_WIN_CELEBRATE_MESSAGE =
  "Paper run is live on this computer";

export const FIRST_WIN_CELEBRATE_AUTO_DISMISS_MS = 4500;

export type FirstWinCelebrateProps = {
  open: boolean;
  onDismiss: () => void;
  /** Override auto-dismiss delay (tests). */
  autoDismissMs?: number;
};

export function FirstWinCelebrate({
  open,
  onDismiss,
  autoDismissMs = FIRST_WIN_CELEBRATE_AUTO_DISMISS_MS,
}: FirstWinCelebrateProps): JSX.Element | null {
  useEffect(() => {
    if (!open) {
      return;
    }
    if (autoDismissMs <= 0) {
      return;
    }
    const timer = window.setTimeout(() => {
      onDismiss();
    }, autoDismissMs);
    return () => window.clearTimeout(timer);
  }, [open, onDismiss, autoDismissMs]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="kbot-first-win-celebrate"
      data-testid="first-win-celebrate"
      role="status"
      aria-live="polite"
    >
      <p className="kbot-first-win-celebrate__eyebrow">First paper run</p>
      <p
        className="kbot-first-win-celebrate__title"
        data-testid="first-win-celebrate-title"
      >
        {FIRST_WIN_CELEBRATE_MESSAGE}
      </p>
      <p className="kbot-first-win-celebrate__body">
        Pause or stop anytime from Run. The guide stays quiet from here.
      </p>
      <button
        type="button"
        className="kbot-first-win-celebrate__dismiss"
        data-testid="first-win-celebrate-dismiss"
        onClick={onDismiss}
      >
        Got it
      </button>
    </div>
  );
}
