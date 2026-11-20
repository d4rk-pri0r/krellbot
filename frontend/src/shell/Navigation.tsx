import { useEffect, useId, useState, type JSX, type KeyboardEvent } from "react";
import "./Navigation.signal.css";

export type View =
  | "home"
  | "workstation"
  | "strategies"
  | "packs"
  | "settings"
  | "research"
  | "studio"
  | "operations"
  | "deployments";

type NavItem = { id: View; label: string };

/** Primary strip — core destinations plus Settings. */
export const PRIMARY_VIEWS: ReadonlyArray<NavItem> = [
  { id: "home", label: "Workspace" },
  { id: "workstation", label: "Run" },
  { id: "strategies", label: "Strategies" },
  { id: "packs", label: "Packs" },
  { id: "settings", label: "Settings" },
];

/** Overflow under More — power destinations; route ids unchanged. */
export const MORE_VIEWS: ReadonlyArray<NavItem> = [
  { id: "research", label: "Research" },
  { id: "studio", label: "Strategy studio" },
  { id: "operations", label: "Operations" },
  { id: "deployments", label: "Deploy" },
];

const MORE_IDS = new Set<View>(MORE_VIEWS.map((view) => view.id));

export function isMoreView(view: View): boolean {
  return MORE_IDS.has(view);
}

type FocusTarget =
  | { kind: "view"; id: View }
  | { kind: "more" };

type NavigationProps = {
  active: View;
  onChange: (view: View) => void;
};

function focusNavTarget(nav: Element | null, target: FocusTarget): void {
  if (!nav) {
    return;
  }
  if (target.kind === "more") {
    nav
      .querySelector<HTMLButtonElement>('[data-testid="kbot-nav-more-toggle"]')
      ?.focus();
    return;
  }
  for (const button of nav.querySelectorAll<HTMLButtonElement>(
    ".kbot-nav__item",
  )) {
    if (button.dataset.view === target.id) {
      button.focus();
      return;
    }
  }
}

/**
 * Tiered nav: primary tabs + More overflow. Roving tabindex covers primary
 * items, the More toggle, and (when expanded) More destinations. Active
 * views under More force the overflow open and keep aria-current.
 */
export function Navigation({ active, onChange }: NavigationProps): JSX.Element {
  const moreBodyId = useId();
  const activeInMore = isMoreView(active);
  const [moreOpen, setMoreOpen] = useState(activeInMore);

  useEffect(() => {
    setMoreOpen(activeInMore);
  }, [active, activeInMore]);

  const effectiveMoreOpen = activeInMore || moreOpen;

  const focusOrder: FocusTarget[] = [
    ...PRIMARY_VIEWS.map((view) => ({ kind: "view" as const, id: view.id })),
    { kind: "more" },
    ...(effectiveMoreOpen
      ? MORE_VIEWS.map((view) => ({ kind: "view" as const, id: view.id }))
      : []),
  ];

  const handleKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    target: FocusTarget,
  ): void => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
      return;
    }
    const index = focusOrder.findIndex((entry) =>
      entry.kind === "more"
        ? target.kind === "more"
        : target.kind === "view" &&
          entry.kind === "view" &&
          entry.id === target.id,
    );
    if (index < 0) {
      return;
    }
    const nextIndex =
      event.key === "ArrowRight"
        ? Math.min(index + 1, focusOrder.length - 1)
        : event.key === "ArrowLeft"
          ? Math.max(index - 1, 0)
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? focusOrder.length - 1
              : null;
    if (nextIndex === null) {
      return;
    }
    event.preventDefault();
    if (nextIndex === index) {
      return;
    }
    const next = focusOrder[nextIndex];
    if (next.kind === "view") {
      onChange(next.id);
    } else if (!effectiveMoreOpen) {
      setMoreOpen(true);
    }
    const nav = event.currentTarget.closest('[data-testid="kbot-nav"]');
    // Focus immediately: view buttons stay mounted (More children use
    // `hidden`, not unmount), matching the pre-M24 roving pattern.
    focusNavTarget(nav, next);
  };

  const renderViewButton = (view: NavItem): JSX.Element => {
    const isActive = active === view.id;
    return (
      <button
        key={view.id}
        type="button"
        data-view={view.id}
        className={
          "kbot-nav__item kbot-shell__nav-item" +
          (isActive
            ? " kbot-nav__item--active kbot-shell__nav-item--active"
            : "")
        }
        aria-pressed={isActive}
        aria-current={isActive ? "page" : undefined}
        tabIndex={isActive ? 0 : -1}
        onClick={() => {
          if (!isMoreView(view.id)) {
            setMoreOpen(false);
          }
          onChange(view.id);
        }}
        onKeyDown={(event) =>
          handleKeyDown(event, { kind: "view", id: view.id })
        }
      >
        {view.label}
      </button>
    );
  };

  return (
    <nav
      className="kbot-nav kbot-shell__nav-root"
      role="navigation"
      aria-label="Workstation navigation"
      data-testid="kbot-nav"
    >
      <div className="kbot-nav__primary" data-testid="kbot-nav-primary">
        {PRIMARY_VIEWS.map((view) => renderViewButton(view))}
        <button
          type="button"
          className={
            "kbot-nav__more-toggle kbot-shell__nav-item" +
            (effectiveMoreOpen ? " kbot-nav__more-toggle--open" : "") +
            (activeInMore ? " kbot-nav__more-toggle--current" : "")
          }
          aria-expanded={effectiveMoreOpen}
          aria-controls={moreBodyId}
          data-testid="kbot-nav-more-toggle"
          tabIndex={-1}
          onClick={() => {
            if (activeInMore) {
              setMoreOpen(true);
              return;
            }
            setMoreOpen((current) => !current);
          }}
          onKeyDown={(event) => handleKeyDown(event, { kind: "more" })}
        >
          More
        </button>
      </div>
      <div
        id={moreBodyId}
        className="kbot-nav__more"
        role="region"
        aria-label="More destinations"
        hidden={!effectiveMoreOpen}
        data-testid="kbot-nav-more"
        data-open={effectiveMoreOpen ? "1" : "0"}
      >
        {MORE_VIEWS.map((view) => renderViewButton(view))}
      </div>
    </nav>
  );
}
