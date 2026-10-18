import { useEffect, useId, useState, type JSX } from "react";
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
  const descId = useId();
  const [exporting, setExporting] = useState<boolean>(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    if (exporting || status === "") return;
    // Commit completion before clearing it in a separate render.
    const timer = setTimeout(() => setStatus(""), 0);
    return () => clearTimeout(timer);
  }, [exporting, status]);

  if (spec === null) {
    return null;
  }
  const stamp = timestamp ?? new Date()
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\.\d{3}Z$/, "Z");
  const handleClick = (): void => {
    setExporting(true);
    setStatus(`Exporting spec ${spec.name}…`);
    const blob = new Blob([indicatorSpecToJson(spec)], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = indicatorSpecFilename(spec.name, stamp);
    anchor.click();
    URL.revokeObjectURL(url);
    queueMicrotask(() => {
      setExporting(false);
      setStatus(`Export complete for spec ${spec.name}`);
    });
  };
  return (
    <>
      <button
        type="button"
        data-testid="studio-indicator-spec-export"
        className="kbot-studio-node-inspector__export"
        onClick={handleClick}
        aria-busy={exporting || undefined}
        aria-keyshortcuts="Enter Space"
        aria-label={"Export spec JSON for indicator " + (spec.name ?? "unknown")}
        aria-describedby={exporting ? descId : undefined}
      >
        Export spec JSON
      </button>
      <p
        data-testid="studio-indicator-spec-export-status"
        id={descId}
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="kbot-palette__label"
      >
        {status}
      </p>
    </>
  );
}
