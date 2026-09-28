import { useState, type JSX } from "react";

type View = "workstation" | "strategies" | "research";

const VIEWS: ReadonlyArray<{ id: View; label: string }> = [
  { id: "workstation", label: "Workstation" },
  { id: "strategies", label: "Strategies" },
  { id: "research", label: "Research" },
];

export function Navigation(): JSX.Element {
  const [active, setActive] = useState<View>("workstation");
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
          onClick={() => setActive(view.id)}
        >
          {view.label}
        </button>
      ))}
    </nav>
  );
}
