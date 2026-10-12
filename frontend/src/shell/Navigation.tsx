import type { JSX } from "react";
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

export function Navigation({ active, onChange }: NavigationProps): JSX.Element {
  return (
    <nav
      className="kbot-nav kbot-shell__nav-root"
      role="navigation"
      aria-label="Workstation navigation"
      data-testid="kbot-nav"
    >
      {VIEWS.map((view) => (
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
          onClick={() => onChange(view.id)}
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

