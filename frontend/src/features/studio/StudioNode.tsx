import "./StudioNode.signal.css";
import type { JSX } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { GraphCanvasNodeData } from "./GraphCanvas";
import { studioNodeLabel } from "./studioNodeLabel";

/**
 * Signal-styled Studio graph node (KRELL-SIGNAL-20261010).
 *
 * Replaces the bare white ReactFlow default node that inherited the
 * shell's light ``--text`` and painted white-on-white. Selection uses
 * seafoam; the visible title is a human-readable label, not the raw id.
 */
export function StudioNode({
  id,
  data,
  selected,
}: NodeProps & { data?: GraphCanvasNodeData }): JSX.Element {
  const timeframe =
    typeof data?.timeframe === "string" && data.timeframe !== ""
      ? data.timeframe
      : null;
  const label =
    typeof data?.label === "string" && data.label !== ""
      ? data.label
      : studioNodeLabel(String(id));
  const rootClass = selected
    ? "kbot-studio-node kbot-studio-node--selected"
    : "kbot-studio-node";

  return (
    <div
      className={rootClass}
      data-testid={`studio-node-${id}`}
      data-timeframe={timeframe ?? ""}
      data-selected={selected ? "1" : "0"}
      aria-selected={selected ? true : undefined}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="kbot-studio-node__handle"
      />
      <p className="kbot-studio-node__label">{label}</p>
      {timeframe !== null ? (
        <p className="kbot-studio-node__meta">{timeframe}</p>
      ) : null}
      <Handle
        type="source"
        position={Position.Right}
        className="kbot-studio-node__handle"
      />
    </div>
  );
}
