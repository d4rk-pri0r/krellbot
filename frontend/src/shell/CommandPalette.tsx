import {
  useEffect,
  useRef,
  type JSX,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import "./CommandPalette.signal.css";

type CommandPaletteProps = {
  open: boolean;
  onClose: () => void;
};

function isOwnedPlainTabKeydown(event: KeyboardEvent): boolean {
  return (
    event.key === "Tab" &&
    !event.ctrlKey &&
    !event.altKey &&
    !event.metaKey &&
    !event.isComposing &&
    event.keyCode !== 229
  );
}

export function CommandPalette({
  open,
  onClose,
}: CommandPaletteProps): JSX.Element | null {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const returnFocusToRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    returnFocusToRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    inputRef.current?.focus();
    return () => {
      returnFocusToRef.current?.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const handleCommandInputKeyDown = (
    event: ReactKeyboardEvent<HTMLInputElement>,
  ) => {
    const nativeEvent = event.nativeEvent;
    if (!isOwnedPlainTabKeydown(nativeEvent)) {
      return;
    }
    if (nativeEvent.defaultPrevented) {
      return;
    }
    if (document.activeElement !== inputRef.current) {
      return;
    }
    event.preventDefault();
  };

  if (!open) {
    return null;
  }

  return (
    <div
      className="kbot-palette kbot-shell__palette-root"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      aria-keyshortcuts="Escape"
      data-testid="command-palette"
    >
      <div className="kbot-palette__box kbot-shell__palette-box">
        <p className="kbot-shell__palette-meta">
          <span
            className="kbot-shell__palette-badge"
            data-testid="command-palette-badge"
          >
            Local preview
          </span>
        </p>
        <label
          className="kbot-palette__label kbot-shell__palette-label"
          htmlFor="kbot-palette-input"
        >
          Find an action, strategy, or view — local preview only.
        </label>
        <input
          id="kbot-palette-input"
          ref={inputRef}
          className="kbot-palette__input kbot-shell__palette-input"
          type="text"
          autoComplete="off"
          spellCheck={false}
          placeholder="Type to search actions, strategies, or views"
          aria-label="Command input"
          onKeyDown={handleCommandInputKeyDown}
        />
        <p className="kbot-palette__hint kbot-shell__palette-hint">
          Press Esc to close · Ctrl+K from anywhere
        </p>
      </div>
    </div>
  );
}
