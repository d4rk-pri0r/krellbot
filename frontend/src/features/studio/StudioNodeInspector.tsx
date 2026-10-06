import { useEffect, useMemo, useState, type ChangeEvent, type JSX } from "react";

export type StudioNodeInspectorProps = {
  nodeId: string | null;
  pack: Record<string, unknown>;
  onChange: (nextPack: Record<string, unknown>) => void;
};

const MIN_INDICATOR_LEN = 2;
const MAX_INDICATOR_LEN = 600;
const INVALID_LEN_MESSAGE = "Enter a whole number between 2 and 600.";

/**
 * Render a labeled input that lets the operator edit one indicator's
 * ``len`` on the in-memory saved pack. The inspector only mounts
 * when ``nodeId`` is the id of an indicator; clicking an entry/exit
 * node renders nothing so the brief stays strict.
 *
 * ``onChange`` always receives a brand-new pack object: the parent's
 * React state update must be a new reference for downstream
 * ``useMemo`` dependencies to fire. Invalid input (empty, nonnumber,
 * fractional or outside 2..600) never reaches ``onChange``; it shows a
 * field error instead. The input's min/max attributes are a hint only.
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

  const handleChange = (event: ChangeEvent<HTMLInputElement>): void => {
    const next = event.target.value;
    setDraft(next);
    const parsed = parseIndicatorLen(next);
    if (parsed === null) {
      setError(INVALID_LEN_MESSAGE);
      return;
    }
    setError(null);
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

  return (
    <div className="kbot-studio-node-inspector">
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
      />
      {error ? (
        <p
          data-testid="studio-indicator-len-error"
          className="kbot-studio-node-inspector__error"
          role="alert"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}

type IndicatorSpec = {
  name: string;
  len: number;
};

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
    return { name: nodeId, len };
  }, [pack, nodeId]);
}