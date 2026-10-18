import { useEffect, useId, useRef, useState, type CSSProperties, type JSX } from "react";
import type { ExplainResult } from "./explainPack";
import {
  explanationCsvBody,
  explanationIndicatorRows,
  explanationMarketRows,
  explanationMetadataRows,
} from "./strategyExplanationCsv";

export type StrategyExplanationCsvExportProps = {
  result: ExplainResult;
  disabled?: boolean;
};

const screenReaderOnly: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  overflow: "hidden",
  clipPath: "inset(50%)",
  whiteSpace: "nowrap",
};

const CSV_MIME_TYPE = "text/csv;charset=utf-8";

// ISO timestamp without colons so the name is filesystem-safe: YYYY-MM-DDTHH-MM-SS.
export function exportTimestamp(now: Date = new Date()): string {
  return now.toISOString().slice(0, 19).replace(/:/g, "-");
}

function hasExportableRows(result: ExplainResult): boolean {
  return result.metadata.label !== null ||
    result.metadata.packId !== null ||
    result.metadata.version !== null ||
    result.metadata.author !== null ||
    result.metadata.origin !== null;
}

export function StrategyExplanationCsvExport({
  result,
  disabled = false,
}: StrategyExplanationCsvExportProps): JSX.Element {
  const canExport = !disabled && hasExportableRows(result);
  const descriptionId = useId();
  const previousCanExport = useRef<boolean | undefined>(undefined);
  const [status, setStatus] = useState<{ label: string; key: number }>({ label: "", key: 0 });
  const unavailableLabel = !hasExportableRows(result)
    ? "Export unavailable: no exportable rows in this explanation"
    : "Export unavailable: this explanation is disabled";

  useEffect(() => {
    if (previousCanExport.current !== canExport) {
      previousCanExport.current = canExport;
      setStatus(previous => ({
        label: canExport ? "Export now available" : unavailableLabel,
        key: previous.key + 1,
      }));
    }
  }, [canExport, unavailableLabel]);

  const handleClick = (): void => {
    if (!canExport) {
      return;
    }
    const rows = [
      ...explanationMetadataRows(result.metadata),
      ...explanationIndicatorRows(result.indicators),
      ...explanationMarketRows(result.markets),
    ];
    const blob = new Blob([explanationCsvBody(rows)], { type: CSV_MIME_TYPE });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `strategy-explanation-${exportTimestamp()}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
    setStatus(previous => ({
      label: "Strategy explanation CSV download started",
      key: previous.key + 1,
    }));
  };

  return (
    <>
      <button
        type="button"
        className="kbot-strategy-explanation__action"
        data-testid="strategies-explanation-csv-export"
        onClick={handleClick}
        onKeyDown={event => {
          if (event.key !== "Enter" && event.key !== " ") return;
          // Cancel the native click, including repeated keydowns, before delegating.
          event.preventDefault();
          if (!canExport || event.repeat) return;
          handleClick();
          event.currentTarget.focus();
        }}
        aria-label="Export explanation: strategy explanation CSV"
        aria-describedby={descriptionId}
        aria-disabled={!canExport}
        disabled={!canExport}
      >
        Export explanation
      </button>
      <span id={descriptionId} style={screenReaderOnly}>
        Downloads strategy-explanation-YYYY-MM-DDTHH-MM-SS.csv with the same CSV bytes as clicking.
        {!canExport ? ` ${unavailableLabel}.` : ""}
      </span>
      <p
        data-testid="strategies-explanation-csv-status"
        role="status"
        aria-live="polite"
        aria-atomic="true"
        style={screenReaderOnly}
      >
        {status.label ? <span key={status.key}>{status.label}</span> : null}
      </p>
    </>
  );
}
