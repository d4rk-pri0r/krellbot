import type { JSX, KeyboardEvent } from "react";
import "./Navigation.signal.css";

export type View =
  | "home"
  | "workstation"
  | "strategies"
  | "research"
  | "studio"
  | "operations"
  | "deployments";

const VIEWS: ReadonlyArray<{ id: View; label: string }> = [
  { id: "home", label: "Home" },
  { id: "workstation", label: "Workstation" },
  { id: "strategies", label: "Strategies" },
  { id: "research", label: "Research" },
  { id: "studio", label: "Studio" },
  { id: "operations", label: "Operations" },
  { id: "deployments", label: "Deploy" },
];

type NavigationProps = {
  active: View;
  onChange: (view: View) => void;
};

// Roving tabindex over the strip: only the active (aria-current="page")
// button is tabbable; every sibling gets tabindex={-1} and is reached with
// ArrowLeft/ArrowRight (clamped at the ends) or Home/End. Focus is moved
// programmatically to the newly active button after onChange fires.
export function Navigation({ active, onChange }: NavigationProps): JSX.Element {
  const handleKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ): void => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
      return;
    }
    const nextIndex =
      event.key === "ArrowRight"
        ? Math.min(index + 1, VIEWS.length - 1)
        : event.key === "ArrowLeft"
          ? Math.max(index - 1, 0)
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? VIEWS.length - 1
              : null;
    if (nextIndex === null) {
      return;
    }
    event.preventDefault();
    if (nextIndex === index) {
      // Clamped at the end of the strip: keep focus put and skip a
      // redundant re-activation of the already active view.
      return;
    }
    const nextView = VIEWS[nextIndex];
    onChange(nextView.id);
    // The controlled parent re-renders with the new active id, so query the
    // DOM for the freshly rendered button rather than caching node refs.
    const nav = event.currentTarget.closest('[data-testid="kbot-nav"]');
    const nextButton = nav?.querySelectorAll<HTMLButtonElement>(
      ".kbot-nav__item",
    )[nextIndex];
    nextButton?.focus();
  };

  return (
    <nav
      className="kbot-nav kbot-shell__nav-root"
      role="navigation"
      aria-label="Workstation navigation"
      data-testid="kbot-nav"
    >
      {VIEWS.map((view, index) => (
        <button
          key={view.id}
          type="button"
          className={
            "kbot-nav__item kbot-shell__nav-item" +
            (active === view.id
              ? " kbot-nav__item--active kbot-shell__nav-item--active"
              : "")
          }
          aria-pressed={active === view.id}
          aria-current={active === view.id ? "page" : undefined}
          tabIndex={active === view.id ? 0 : -1}
          onClick={() => onChange(view.id)}
          onKeyDown={(event) => handleKeyDown(event, index)}
        >
          {view.label}
        </button>
      ))}
      <p className="kbot-shell__nav-note">
        <span
          className="kbot-shell__nav-preview"
          data-testid="nav-local-preview"
        >
          Local preview
        </span>
        <span
          className="kbot-shell__nav-note-text"
          data-testid="nav-local-preview-note"
        >
          Live trading unavailable
        </span>
      </p>
    </nav>
  );
}

