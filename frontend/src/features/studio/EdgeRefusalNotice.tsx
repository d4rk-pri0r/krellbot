import { useEffect, useRef, type KeyboardEvent } from "react";
import type { EdgeRefusal } from "./edges";
import { summarizeEdgeRefusal } from "./edgeRefusalLabel";

type EdgeRefusalNoticeProps = {
  reason: EdgeRefusal;
  onDismiss: () => void;
  /**
   * Element that should receive focus once the notice is dismissed
   * (the GraphCanvas container), so a keyboard-only operator keeps
   * working where the refusal happened instead of hunting the page.
   */
  onDismissFocusTarget?: HTMLElement | null;
};

const MESSAGE_ID = "edge-refusal-notice-message";

export function EdgeRefusalNotice({
  reason,
  onDismiss,
  onDismissFocusTarget,
}: EdgeRefusalNoticeProps) {
  const mountedRef = useRef(false);

  // GraphCanvas unmounts this notice as soon as the refusal clears, so
  // the focus return for its journey runs in handleDismiss below. This
  // effect covers parents that keep the notice mounted while clearing
  // ``reason``; the first-render guard keeps a ``reason=null`` mount
  // from stealing focus it never earned.
  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true;
      return;
    }
    if (reason == null) {
      onDismissFocusTarget?.focus({ preventScroll: true });
    }
  }, [reason, onDismissFocusTarget]);

  const handleDismiss = () => {
    onDismiss();
    onDismissFocusTarget?.focus({ preventScroll: true });
  };

  // Enter/Space delegate to the same onClick dismissal so the browser's
  // own key activation cannot fire it a second time.
  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (
      (event.key === "Enter" || event.key === " ") &&
      !event.repeat &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      event.currentTarget.click();
    }
  };

  return (
    <div
      role="alert"
      aria-live="assertive"
      data-testid="edge-refusal-notice"
    >
      <p id={MESSAGE_ID}>{summarizeEdgeRefusal(reason).label}</p>
      <button
        type="button"
        data-testid="edge-refusal-notice-dismiss"
        aria-keyshortcuts="Enter"
        aria-describedby={MESSAGE_ID}
        onClick={handleDismiss}
        onKeyDown={handleKeyDown}
      >
        Dismiss edge refusal
      </button>
    </div>
  );
}