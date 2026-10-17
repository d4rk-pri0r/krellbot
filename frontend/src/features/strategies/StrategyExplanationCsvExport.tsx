import type { JSX } from "react";
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
  };

  return (
    <button
      type="button"
      className="kbot-strategy-explanation__action"
      data-testid="strategies-explanation-csv-export"
      onClick={handleClick}
      disabled={!canExport}
    >
      Export explanation
    </button>
  );
}
