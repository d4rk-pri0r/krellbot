import { useEffect, useRef, useState, type JSX } from "react";
import type { StarterCatalogue, StarterExample } from "./StarterPicker.client";
import { fetchStarters } from "./StarterPicker.client";
import "./StarterPicker.signal.css";

export type StarterPickerProps = {
  onPick: (example: StarterExample) => void;
  /**
   * Loader override for tests. Production callers omit it and the real
   * session fetch (`fetchStarters`) runs.
   */
  loadStarters?: () => Promise<StarterCatalogue>;
};

type LoadState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; examples: StarterExample[] };

/**
 * Free starter examples section.
 *
 * Fetches the shipped read-only catalogue from the backend and offers
 * each example as a one-click seed for the editor's raw JSON. Picking a
 * starter never opens an existing revision and never saves anything by
 * itself: it only hands the pack bytes to the editor, and the editor's
 * existing Save/Validate/Arm flow takes over from there.
 *
 * The catalogue request is lazy on visibility: the strategies view must
 * not perform network I/O merely because the editor mounted (the pack
 * library's no-eager-fetch contract), so loading starts when the
 * section actually enters the viewport. Environments without
 * `IntersectionObserver` (jsdom) stay in the idle/loading state and
 * never touch the network; real browsers load as soon as the section is
 * shown, which is immediately when the Editor opens.
 */
export function StarterPicker({
  onPick,
  loadStarters = fetchStarters,
}: StarterPickerProps): JSX.Element {
  const rootRef = useRef<HTMLElement | null>(null);
  const [state, setState] = useState<LoadState>({ kind: "idle" });
  // Manual recovery counter: bumping it re-runs the effect (and so
  // `loadStarters`) without remounting the section or the editor. It
  // is the only way a second load ever happens; a successful load
  // never bumps it, so nothing refetches on its own.
  const [retryTrigger, setRetryTrigger] = useState(0);

  useEffect(() => {
    const element = rootRef.current;
    if (!element || typeof IntersectionObserver === "undefined") {
      return;
    }
    let cancelled = false;
    const load = (): void => {
      if (cancelled) {
        return;
      }
      setState({ kind: "loading" });
      loadStarters()
        .then((catalogue) => {
          if (cancelled) {
            return;
          }
          // A catalogue that reports version "0" or ships no rows is
          // the explicit empty state — not an error, and never a
          // fallback to hardcoded example rows.
          setState({
            kind: "loaded",
            examples:
              catalogue.catalogue_version === "0" ? [] : catalogue.examples,
          });
        })
        .catch((err: unknown) => {
          if (cancelled) {
            return;
          }
          setState({
            kind: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        });
    };
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            observer.disconnect();
            load();
          }
        }
      },
      { root: null, rootMargin: "0px", threshold: 0 },
    );
    if (retryTrigger > 0) {
      // A retry already proved visibility once; the one-shot observer
      // would never fire again, so the retry attempt runs directly.
      load();
    } else {
      observer.observe(element);
    }
    return () => {
      cancelled = true;
      observer.disconnect();
    };
  }, [loadStarters, retryTrigger]);

  return (
    <section
      ref={rootRef}
      className="kbot-starter-picker"
      data-testid="starter-picker"
      aria-label="Free starter examples"
    >
      <h3 className="kbot-starter-picker__title">Free Starter Examples</h3>
      <p className="kbot-starter-picker__hint">
        Free, read-only educational example packs. Picking one seeds the raw JSON
        below as a fresh editable copy — it is not a reopen of any saved revision.
        Save, Validate, and Arm behave exactly as before.
      </p>
      {state.kind === "error" ? (
        <div className="kbot-starter-picker__error-row">
          <p
            className="kbot-starter-picker__error"
            data-testid="starter-picker-error"
            role="alert"
            aria-live="polite"
          >
            Could not load starter examples: {state.message}
          </p>
          <button
            type="button"
            className="kbot-starter-picker__retry"
            data-testid="starter-picker-retry"
            onClick={() => {
              setRetryTrigger((trigger) => trigger + 1);
            }}
          >
            Retry starter examples
          </button>
        </div>
      ) : null}
      {state.kind === "idle" || state.kind === "loading" ? (
        <p className="kbot-starter-picker__status" data-testid="starter-picker-loading">
          Loading starter examples…
        </p>
      ) : null}
      {state.kind === "loaded" && state.examples.length === 0 ? (
        <p
          className="kbot-starter-picker__empty"
          data-testid="starter-picker-empty"
        >
          No starter examples available
        </p>
      ) : null}
      {state.kind === "loaded" && state.examples.length > 0 ? (
        <ul className="kbot-starter-picker__list">
          {state.examples.map((example) => (
            <li
              key={example.id}
              className="kbot-starter-picker__item"
              data-testid={`starter-picker-item-${example.id}`}
            >
              <span className="kbot-starter-picker__item-label">{example.label}</span>
              <span className="kbot-starter-picker__item-description">
                {example.description}
              </span>
              <button
                type="button"
                className="kbot-starter-picker__action"
                onClick={() => onPick(example)}
              >
                Use {example.label}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
