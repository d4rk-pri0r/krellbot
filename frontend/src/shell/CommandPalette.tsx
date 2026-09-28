import { useEffect, useRef, type JSX } from "react";

type CommandPaletteProps = {
  open: boolean;
  onClose: () => void;
};

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

  if (!open) {
    return null;
  }

  return (
    <div
      className="kbot-palette"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      data-testid="command-palette"
    >
      <label className="kbot-palette__label" htmlFor="kbot-palette-input">
        Command
      </label>
      <input
        id="kbot-palette-input"
        ref={inputRef}
        className="kbot-palette__input"
        type="text"
        autoComplete="off"
        spellCheck={false}
        placeholder="Type a command"
        aria-label="Command input"
      />
    </div>
  );
}
