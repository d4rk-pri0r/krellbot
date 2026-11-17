import {
  useEffect,
  useId,
  useState,
  type JSX,
  type ReactNode,
} from "react";
import "./DisclosureSection.signal.css";

export type DisclosureSectionProps = {
  title: string;
  /** One-line collapsed context (counts, mode, honesty notes). */
  summary?: string;
  /** Optional pill next to the title (e.g. Advanced). */
  badge?: string;
  badgeTone?: "default" | "caution" | "advanced";
  defaultOpen?: boolean;
  /** Persist open/closed across reloads in localStorage. */
  storageKey?: string;
  /** Keep open and show a caution badge when true (validation/errors). */
  forceOpen?: boolean;
  /** When true, omit the panel chrome (for nesting inside an existing panel). */
  bare?: boolean;
  className?: string;
  "data-testid"?: string;
  children: ReactNode;
};

function readStoredOpen(storageKey: string | undefined): boolean | null {
  if (!storageKey || typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (raw === "1") return true;
    if (raw === "0") return false;
    return null;
  } catch {
    return null;
  }
}

function writeStoredOpen(storageKey: string | undefined, open: boolean): void {
  if (!storageKey || typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(storageKey, open ? "1" : "0");
  } catch {
    // Best-effort only.
  }
}

/**
 * Progressive disclosure: children stay mounted so form values and
 * validation survive collapse. forceOpen surfaces errors while closed.
 */
export function DisclosureSection({
  title,
  summary,
  badge,
  badgeTone = "default",
  defaultOpen = false,
  storageKey,
  forceOpen = false,
  bare = false,
  className,
  "data-testid": testId,
  children,
}: DisclosureSectionProps): JSX.Element {
  const reactId = useId();
  const bodyId = `${reactId}-body`;
  const [open, setOpen] = useState(() => {
    const stored = readStoredOpen(storageKey);
    return stored ?? defaultOpen;
  });

  useEffect(() => {
    if (forceOpen && !open) {
      setOpen(true);
    }
  }, [forceOpen, open]);

  const effectiveOpen = forceOpen || open;
  const effectiveBadge =
    forceOpen && !badge ? "Needs attention" : badge;
  const effectiveTone =
    forceOpen && (!badge || badgeTone === "default")
      ? "caution"
      : badgeTone;

  return (
    <section
      className={
        "kbot-disclosure" +
        (bare ? " kbot-disclosure--bare" : "") +
        (className ? ` ${className}` : "")
      }
      data-testid={testId}
      data-open={effectiveOpen ? "1" : "0"}
    >
      <button
        type="button"
        className="kbot-disclosure__summary"
        aria-expanded={effectiveOpen}
        aria-controls={bodyId}
        data-testid={testId ? `${testId}-toggle` : undefined}
        onClick={() => {
          setOpen((current) => {
            const next = forceOpen ? true : !current;
            writeStoredOpen(storageKey, next);
            return next;
          });
        }}
      >
        <span className="kbot-disclosure__summary-copy">
          <span className="kbot-disclosure__title-row">
            <span className="kbot-disclosure__title">{title}</span>
            {effectiveBadge ? (
              <span
                className={
                  "kbot-disclosure__badge" +
                  (effectiveTone === "caution"
                    ? " kbot-disclosure__badge--caution"
                    : effectiveTone === "advanced"
                      ? " kbot-disclosure__badge--advanced"
                      : "")
                }
              >
                {effectiveBadge}
              </span>
            ) : null}
          </span>
          {summary ? (
            <span className="kbot-disclosure__lede">{summary}</span>
          ) : null}
        </span>
        <span className="kbot-disclosure__chevron" aria-hidden="true">
          ▸
        </span>
      </button>
      <div
        id={bodyId}
        className="kbot-disclosure__body"
        role="region"
        aria-label={title}
        hidden={!effectiveOpen}
        data-testid={testId ? `${testId}-body` : undefined}
      >
        {children}
      </div>
    </section>
  );
}
