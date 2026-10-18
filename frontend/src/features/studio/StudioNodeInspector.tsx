import "./StudioNodeInspector.signal.css";
import { useEffect, useMemo, useState, type ChangeEvent, type JSX } from "react";
import { IndicatorSpecJsonExport } from "./IndicatorSpecJsonExport";

export type StudioNodeInspectorProps = {
  nodeId: string | null;
  pack: Record<string, unknown>;
  onChange: (nextPack: Record<string, unknown>) => void;
};

const MIN_INDICATOR_LEN = 2;
const MAX_INDICATOR_LEN = 600;
const INVALID_LEN_MESSAGE = "Enter a whole number between 2 and 600.";

/**
 * Render the readable Signal inspector that lets the operator edit one
 * indicator's ``len`` on the in-memory saved pack. The inspector only
 * mounts when ``nodeId`` is the id of an indicator; clicking an entry/exit
 * node renders nothing so the brief stays strict.
 *
 * ``onChange`` always receives a brand-new pack object: the parent's
 * React state update must be a new reference for downstream
 * ``useMemo`` dependencies to fire. Invalid input (empty, nonnumber,
 * fractional or outside 2..600) never reaches ``onChange``; it shows a
 * field error instead. The input's min/max attributes are a hint only.
 *
 * The header (eyebrow, node id title and badge, indicator-context
 * label), the integer current-value display, the text status and the
 * explicit Apply affordance (disabled while the draft is invalid) are
 * presentation only: Apply re-runs the exact same validation and
 * new-reference emit path as typing — no new save, refresh or
 * validation rule.
 */
export function StudioNodeInspector({
  nodeId,
  pack,
  onChange,
}: StudioNodeInspectorProps): JSX.Element | null {
  const indicatorSpec = useIndicator(pack, nodeId);
  const indicatorName = indicatorSpec?.name ?? null;
  const initialLen = indicatorSpec?.len ?? 0;
  const [draft, setDraft] = useState<string>(String(initialLen));
  const [error, setError] = useState<string | null>(null);

  // Reset the draft whenever the selected indicator changes.
  useEffect(() => {
    setDraft(String(initialLen));
    setError(null);
  }, [indicatorName, initialLen]);

  if (!indicatorSpec) {
    return null;
  }

  const emitLenChange = (parsed: number): void => {
    const indicators = pack.indicators;
    if (!indicators || typeof indicators !== "object" || Array.isArray(indicators)) {
      return;
    }
    const nextIndicators: Record<string, unknown> = {};
    for (const [name, spec] of Object.entries(
      indicators as Record<string, unknown>,
    )) {
      if (name === indicatorName) {
        if (spec && typeof spec === "object" && !Array.isArray(spec)) {
          nextIndicators[name] = { ...(spec as Record<string, unknown>), len: parsed };
          continue;
        }
        nextIndicators[name] = { len: parsed };
        continue;
      }
      nextIndicators[name] = spec;
    }
    onChange({ ...pack, indicators: nextIndicators });
  };

  const handleChange = (event: ChangeEvent<HTMLInputElement>): void => {
    const next = event.target.value;
    setDraft(next);
    const parsed = parseIndicatorLen(next);
    if (parsed === null) {
      setError(INVALID_LEN_MESSAGE);
      return;
    }
    setError(null);
    emitLenChange(parsed);
  };

  // Manual affordance over the current draft: identical validation and
  // new-reference emit path as typing. Disabled while invalid; adds no
  // save, refresh or validation rule of its own.
  const handleApply = (): void => {
    const parsed = parseIndicatorLen(draft);
    if (parsed === null) {
      setError(INVALID_LEN_MESSAGE);
      return;
    }
    setError(null);
    emitLenChange(parsed);
  };

  return (
    <div className="kbot-studio-node-inspector">
      <header
        data-testid="studio-node-inspector-header"
        className="kbot-studio-node-inspector__header"
      >
        <p className="kbot-studio-node-inspector__eyebrow">Selected node</p>
        <div className="kbot-studio-node-inspector__title-row">
          <h3
            data-testid="studio-node-inspector-title"
            className="kbot-studio-node-inspector__title"
          >
            {indicatorSpec.name}
          </h3>
          <span
            data-testid="studio-node-inspector-node-id"
            className="kbot-studio-node-inspector__node-id"
          >
            {indicatorSpec.name}
          </span>
        </div>
        <p
          data-testid="studio-node-inspector-context"
          className="kbot-studio-node-inspector__context"
        >
          {indicatorContextLabel(indicatorSpec)}
        </p>
      </header>
      <div className="kbot-studio-node-inspector__summary">
        <p className="kbot-studio-node-inspector__summary-label">Current length</p>
        <p
          data-testid="studio-node-inspector-value"
          className="kbot-studio-node-inspector__summary-value"
        >
          {currentLenText(indicatorSpec.len)}
        </p>
        <p
          data-testid="studio-node-inspector-status"
          role="status"
          className={
            error === null
              ? "kbot-studio-node-inspector__status kbot-studio-node-inspector__status--valid"
              : "kbot-studio-node-inspector__status kbot-studio-node-inspector__status--invalid"
          }
        >
          {error === null ? "Valid" : "Invalid"}
        </p>
      </div>
      <div className="kbot-studio-node-inspector__field">
        <label
          htmlFor="studio-indicator-len"
          className="kbot-studio-node-inspector__label"
        >
          Indicator length ({indicatorName})
        </label>
        <input
          id="studio-indicator-len"
          data-testid="studio-indicator-len"
          className="kbot-studio-node-inspector__input"
          type="number"
          min={MIN_INDICATOR_LEN}
          max={MAX_INDICATOR_LEN}
          value={draft}
          onChange={handleChange}
          aria-invalid={error !== null}
          aria-describedby={
            error !== null
              ? "studio-node-inspector-len-error"
              : "studio-indicator-len-hint"
          }
        />
        <p
          id="studio-indicator-len-hint"
          className="kbot-studio-node-inspector__context"
        >
          Whole number between 2 and{" "}
          <span>600</span>
        </p>
        {error ? (
          <p
            id="studio-node-inspector-len-error"
            data-testid="studio-node-inspector-len-error"
            className="kbot-studio-node-inspector__error"
            role="alert"
          >
            {error}
          </p>
        ) : null}
        <div className="kbot-studio-node-inspector__actions">
          <button
            type="button"
            data-testid="studio-node-inspector-apply"
            className="kbot-studio-node-inspector__apply"
            disabled={error !== null}
            onClick={handleApply}
          >
            Apply length
          </button>
          <IndicatorSpecJsonExport
            spec={
              indicatorSpec ? { name: indicatorSpec.name, len: indicatorSpec.len } : null
            }
          />
        </div>
      </div>
    </div>
  );
}

type IndicatorSpec = {
  name: string;
  len: number;
  fn?: string;
  src?: string;
};

/**
 * Readable indicator context for the header: the real pack spec fields
 * that exist, joined with middle dots. Presentation only — no invented
 * node semantics.
 */
function indicatorContextLabel(spec: IndicatorSpec): string {
  const parts: string[] = ["Indicator"];
  if (typeof spec.fn === "string" && spec.fn !== "") {
    parts.push(`fn ${spec.fn}`);
  }
  if (typeof spec.src === "string" && spec.src !== "") {
    parts.push(`src ${spec.src}`);
  }
  return parts.join(" · ");
}

/**
 * The pack stores whole-number lengths; render the value as an integer
 * (2, never 2.0) without inventing precision the pack does not carry.
 */
function currentLenText(len: number): string {
  return String(len);
}

/**
 * Parse the input the browser actually reports for ``type="number"``.
 * Browsers sanitize bad input (e.g. ``abc``) to the empty string, so an
 * empty draft is always invalid: an empty field must never be read as
 * ``Number("") === 0``.
 */
function parseIndicatorLen(raw: string): number | null {
  if (typeof raw !== "string" || raw.trim() === "") {
    return null;
  }
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || !Number.isInteger(parsed)) {
    return null;
  }
  if (parsed < MIN_INDICATOR_LEN || parsed > MAX_INDICATOR_LEN) {
    return null;
  }
  return parsed;
}

function useIndicator(
  pack: Record<string, unknown>,
  nodeId: string | null,
): IndicatorSpec | null {
  return useMemo(() => {
    if (!nodeId) {
      return null;
    }
    const indicators = pack.indicators;
    if (!indicators || typeof indicators !== "object" || Array.isArray(indicators)) {
      return null;
    }
    const spec = (indicators as Record<string, unknown>)[nodeId];
    if (!spec || typeof spec !== "object" || Array.isArray(spec)) {
      return null;
    }
    const lenRaw = (spec as Record<string, unknown>).len;
    const len = typeof lenRaw === "number" ? lenRaw : Number(lenRaw);
    if (!Number.isFinite(len)) {
      return null;
    }
    const fnRaw = (spec as Record<string, unknown>).fn;
    const srcRaw = (spec as Record<string, unknown>).src;
    return {
      name: nodeId,
      len,
      fn: typeof fnRaw === "string" ? fnRaw : undefined,
      src: typeof srcRaw === "string" ? srcRaw : undefined,
    };
  }, [pack, nodeId]);
}