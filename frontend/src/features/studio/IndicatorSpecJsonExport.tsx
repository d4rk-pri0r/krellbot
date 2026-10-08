import type { JSX } from "react";
import {
  indicatorSpecFilename,
  indicatorSpecToJson,
  type IndicatorSpecLike,
} from "./indicatorSpecJson";

export type IndicatorSpecJsonExportProps = {
  spec: IndicatorSpecLike | null;
  timestamp?: string;
};

/**
 * Render the "Export spec JSON" button for the inspector's already
 * validated indicator spec. Clicking downloads a ``{name, len}``
 * snapshot; nothing about indicator behavior, validation or save
 * changes here.
 */
export function IndicatorSpecJsonExport({
  spec,
  timestamp,
}: IndicatorSpecJsonExportProps): JSX.Element | null {
  if (spec === null) {
    return null;
  }
  const stamp = timestamp ?? new Date()
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\.\d{3}Z$/, "Z");
  const handleClick = (): void => {
    const blob = new Blob([indicatorSpecToJson(spec)], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = indicatorSpecFilename(spec.name, stamp);
    anchor.click();
    URL.revokeObjectURL(url);
  };
  return (
    <button
      type="button"
      data-testid="studio-indicator-spec-export"
      className="kbot-studio-node-inspector__export"
      onClick={handleClick}
    >
      Export spec JSON
    </button>
  );
}
