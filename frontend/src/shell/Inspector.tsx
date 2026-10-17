import type { JSX } from "react";
import "./Inspector.signal.css";

/**
 * The subject the shell is currently inspecting, if any. The shell owns
 * selection; the inspector only presents what it is given — it never
 * fetches, never infers, and never invents a subject.
 */
export type InspectorSelection = {
  id: string;
  label?: string;
};

export type InspectorProps = {
  selection?: InspectorSelection | null;
  loading?: boolean;
  error?: string | null;
};

export function Inspector({
  selection = null,
  loading = false,
  error = null,
}: InspectorProps = {}): JSX.Element {
  return (
    <section
      className="kbot-shell__inspector-root"
      role="region"
      aria-label="Inspector"
      data-testid="inspector-root"
    >
      <header className="kbot-inspector__head">
        <h2 className="kbot-inspector__title">Inspector</h2>
      </header>
      <div className="kbot-inspector__body">
        {error ? (
          <p
            className="kbot-inspector__error"
            role="alert"
            data-testid="inspector-error"
          >
            Could not inspect the selection — {error}
          </p>
        ) : null}
        {!error && loading && selection ? (
          <p
            className="kbot-inspector__loading"
            data-testid="inspector-loading"
          >
            Inspecting selection…
          </p>
        ) : null}
        {!error && !loading && selection ? (
          <div
            className="kbot-inspector__selected"
            data-testid="inspector-selection"
          >
            <p className="kbot-inspector__selected-label">Selected</p>
            <p className="kbot-inspector__selected-id">{selection.id}</p>
            {selection.label ? (
              <p className="kbot-inspector__selected-detail">
                {selection.label}
              </p>
            ) : null}
          </div>
        ) : null}
        {!error && !selection ? (
          <p className="kbot-inspector__empty" data-testid="inspector-empty">
            Nothing selected — pick a revision on Strategies or a node in Studio
            to inspect it here.
          </p>
        ) : null}
      </div>
    </section>
  );
}
