import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import type { View } from "./Navigation";
import "./CommandPalette.signal.css";

type CommandPaletteProps = {
  open: boolean;
  onClose: () => void;
  /** Navigate to a shell view. Required for real actions; optional in unit isolation. */
  onNavigate?: (view: View) => void;
};

export type PaletteActionKind = "view" | "paper-entry";

export type PaletteAction = {
  id: string;
  label: string;
  group: "Views" | "Paper";
  kind: PaletteActionKind;
  /** Extra terms matched by the filter (not shown). */
  keywords: string;
  view: View;
};

const VIEW_ACTIONS: ReadonlyArray<PaletteAction> = [
  {
    id: "view-home",
    label: "Go to Workspace",
    group: "Views",
    kind: "view",
    keywords: "home overview",
    view: "home",
  },
  {
    id: "view-workstation",
    label: "Go to Run",
    group: "Views",
    kind: "view",
    keywords: "paper bot runs workstation",
    view: "workstation",
  },
  {
    id: "view-strategies",
    label: "Go to Strategies",
    group: "Views",
    kind: "view",
    keywords: "library editor",
    view: "strategies",
  },
  {
    id: "view-packs",
    label: "Go to Packs",
    group: "Views",
    kind: "view",
    keywords: "packs catalogue install library store",
    view: "packs",
  },
  {
    id: "view-research",
    label: "Go to Research",
    group: "Views",
    kind: "view",
    keywords: "backtest jobs",
    view: "research",
  },
  {
    id: "view-studio",
    label: "Go to Strategy studio",
    group: "Views",
    kind: "view",
    keywords: "graph canvas",
    view: "studio",
  },
  {
    id: "view-operations",
    label: "Go to Operations",
    group: "Views",
    kind: "view",
    keywords: "alerts kill switch",
    view: "operations",
  },
  {
    id: "view-deployments",
    label: "Go to Deploy",
    group: "Views",
    kind: "view",
    keywords: "preflight live",
    view: "deployments",
  },
];

/**
 * Beginner default path — home mounts Chooser A (M24.2–M24.3). Power
 * paper controls remain below as Run destinations.
 */
const BEGINNER_ENTRY_ACTIONS: ReadonlyArray<PaletteAction> = [
  {
    id: "start-free-paper-strategy",
    label: "Start free paper strategy",
    group: "Paper",
    kind: "paper-entry",
    keywords: "starter free paper strategy chooser home begin",
    view: "home",
  },
];

/**
 * Paper arm/disarm entry points only — they open Run where the real
 * controls live. Live arming is not offered (local preview / PAPER_ONLY).
 */
const PAPER_ENTRY_ACTIONS: ReadonlyArray<PaletteAction> = [
  {
    id: "paper-arm",
    label: "Start paper run…",
    group: "Paper",
    kind: "paper-entry",
    keywords: "arm paper pack fund start run workstation",
    view: "workstation",
  },
  {
    id: "paper-disarm",
    label: "Stop paper run…",
    group: "Paper",
    kind: "paper-entry",
    keywords: "disarm paper pack stop run workstation",
    view: "workstation",
  },
  {
    id: "paper-pause",
    label: "Pause new buys…",
    group: "Paper",
    kind: "paper-entry",
    keywords: "pause entries resume buys workstation",
    view: "workstation",
  },
];

export const PALETTE_ACTIONS: ReadonlyArray<PaletteAction> = [
  ...BEGINNER_ENTRY_ACTIONS,
  ...VIEW_ACTIONS,
  ...PAPER_ENTRY_ACTIONS,
];

function matchesQuery(action: PaletteAction, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === "") {
    return true;
  }
  const haystack = `${action.label} ${action.group} ${action.keywords}`.toLowerCase();
  return haystack.includes(q);
}

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
  onNavigate,
}: CommandPaletteProps): JSX.Element | null {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const returnFocusToRef = useRef<HTMLElement | null>(null);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const filtered = useMemo(
    () => PALETTE_ACTIONS.filter((action) => matchesQuery(action, query)),
    [query],
  );

  useEffect(() => {
    if (!open) {
      return;
    }
    returnFocusToRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setQuery("");
    setActiveIndex(0);
    inputRef.current?.focus();
    return () => {
      returnFocusToRef.current?.focus();
    };
  }, [open]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    if (filtered.length === 0) {
      return;
    }
    if (activeIndex >= filtered.length) {
      setActiveIndex(filtered.length - 1);
    }
  }, [filtered.length, activeIndex]);

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

  const runAction = (action: PaletteAction): void => {
    onNavigate?.(action.view);
    onClose();
  };

  const handleCommandInputKeyDown = (
    event: ReactKeyboardEvent<HTMLInputElement>,
  ) => {
    const nativeEvent = event.nativeEvent;
    if (isOwnedPlainTabKeydown(nativeEvent)) {
      if (nativeEvent.defaultPrevented) {
        return;
      }
      if (document.activeElement !== inputRef.current) {
        return;
      }
      event.preventDefault();
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (filtered.length === 0) {
        return;
      }
      setActiveIndex((index) => (index + 1) % filtered.length);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (filtered.length === 0) {
        return;
      }
      setActiveIndex(
        (index) => (index - 1 + filtered.length) % filtered.length,
      );
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const action = filtered[activeIndex];
      if (action) {
        runAction(action);
      }
    }
  };

  if (!open) {
    return null;
  }

  const activeId =
    filtered.length > 0
      ? `command-palette-option-${filtered[activeIndex]?.id}`
      : undefined;

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
          aria-controls="command-palette-results"
          aria-activedescendant={activeId}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={handleCommandInputKeyDown}
        />
        <ul
          id="command-palette-results"
          className="kbot-shell__palette-results"
          role="listbox"
          aria-label="Palette actions"
          data-testid="command-palette-results"
        >
          {filtered.length === 0 ? (
            <li
              className="kbot-shell__palette-empty"
              data-testid="command-palette-empty"
              role="presentation"
            >
              No matching actions.
            </li>
          ) : (
            filtered.map((action, index) => {
              const selected = index === activeIndex;
              return (
                <li key={action.id} role="presentation">
                  <button
                    type="button"
                    id={`command-palette-option-${action.id}`}
                    role="option"
                    aria-selected={selected}
                    data-testid={`command-palette-action-${action.id}`}
                    data-palette-kind={action.kind}
                    data-palette-group={action.group}
                    className={
                      "kbot-shell__palette-action" +
                      (selected ? " kbot-shell__palette-action--active" : "")
                    }
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => runAction(action)}
                  >
                    <span className="kbot-shell__palette-action-label">
                      {action.label}
                    </span>
                    <span className="kbot-shell__palette-action-group">
                      {action.group}
                    </span>
                  </button>
                </li>
              );
            })
          )}
        </ul>
        <p className="kbot-palette__hint kbot-shell__palette-hint">
          Press Esc to close · Ctrl+K from anywhere
        </p>
      </div>
    </div>
  );
}
