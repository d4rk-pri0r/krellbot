import type { JSX } from "react";

export type View =
  | "workstation"
  | "strategies"
  | "research"
  | "studio"
  | "operations"
  | "deployments";

const VIEWS: ReadonlyArray<{ id: View; label: string }> = [
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
      className="kbot-nav"
      role="navigation"
      aria-label="Workstation navigation"
    >
      {VIEWS.map((view) => (
        <button
          key={view.id}
          type="button"
          className={
            "kbot-nav__item" +
            (active === view.id ? " kbot-nav__item--active" : "")
          }
          aria-pressed={active === view.id}
          aria-current={active === view.id ? "page" : undefined}
          onClick={() => onChange(view.id)}
        >
          {view.label}
        </button>
      ))}
    </nav>
  );
}
