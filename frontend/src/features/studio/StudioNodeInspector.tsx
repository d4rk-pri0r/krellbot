import { useEffect, useMemo, useState, type ChangeEvent, type JSX } from "react";

export type StudioNodeInspectorProps = {
  nodeId: string | null;
  pack: Record<string, unknown>;
  onChange: (nextPack: Record<string, unknown>) => void;
};

/**
 * Render a labeled input that lets the operator edit one indicator's
 * ``len`` on the in-memory saved pack. The inspector only mounts
 * when ``nodeId`` is the id of an indicator; clicking an entry/exit
 * node renders nothing so the brief stays strict.
 *
 * ``onChange`` always receives a brand-new pack object: the parent's
 * React state update must be a new reference for downstream
 * ``useMemo`` dependencies to fire.
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

  // Reset the draft whenever the selected indicator changes.
  useEffect(() => {
    setDraft(String(initialLen));
  }, [indicatorName, initialLen]);

  if (!indicatorSpec) {
    return null;
  }

  const handleChange = (event: ChangeEvent<HTMLInputElement>): void => {
    const next = event.target.value;
    setDraft(next);
    const parsed = Number(next);
    if (!Number.isFinite(parsed)) {
      return;
    }
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
        min={2}
        max={600}
        value={draft}
        onChange={handleChange}
      />
    </div>
  );
}

type IndicatorSpec = {
  name: string;
  len: number;
};

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