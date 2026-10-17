import type { JSX } from "react";
import type { DraftSummary, Pack } from "./client";

export type EditorCsvExportProps = {
  lastSummary: DraftSummary | null;
  currentPack: Pack | null;
};

const CSV_HEADER = [
  "revision_id",
  "state",
  "error_count",
  "label",
  "parameter_count",
  "kind_count",
];

function csvField(value: string): string {
  return /[",\n]/.test(value)
    ? `"${value.replace(/"/g, '""')}"`
    : value;
}

// Same UTC compact timestamp shape as the alerts/trace CSV export slices.
export function exportTimestamp(now: Date = new Date()): string {
  return now.toISOString().replace(/[-:TZ.]/g, "").slice(0, 14);
}

function countPackKeys(pack: Pack | null): {
  parameters: number;
  kinds: number;
} {
  // Top-level keys excluding `label`: scalar values count as parameters,
  // structured values (objects/arrays) count as kinds.
  let parameters = 0;
  let kinds = 0;
  if (pack) {
    for (const key of Object.keys(pack)) {
      if (key === "label") {
        continue;
      }
      const value = pack[key];
      if (value !== null && typeof value === "object") {
        kinds += 1;
      } else {
        parameters += 1;
      }
    }
  }
  return { parameters, kinds };
}

function buildCsv(summary: DraftSummary, pack: Pack | null): string {
  const { parameters, kinds } = countPackKeys(pack);
  const label = typeof pack?.label === "string" ? pack.label : "";
  const row = [
    summary.revision_id,
    summary.state,
    String((summary.errors ?? []).length),
    label,
    String(parameters),
    String(kinds),
  ];
  return [CSV_HEADER.map(csvField).join(","), row.map(csvField).join(",")].join(
    "\n",
  );
}

export function EditorCsvExport({
  lastSummary,
  currentPack,
}: EditorCsvExportProps): JSX.Element {
  const handleExportCsv = (): void => {
    if (!lastSummary) {
      return;
    }
    const blob = new Blob([buildCsv(lastSummary, currentPack)], {
      type: "text/csv",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `krellbot-revision-${
      lastSummary.revision_id || "unknown"
    }-${exportTimestamp()}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <button
        type="button"
        className="kbot-strategy-editor__action"
        data-testid="strategies-editor-csv-export"
        onClick={handleExportCsv}
        disabled={!lastSummary}
      >
        Export CSV
      </button>
      {lastSummary === null ? (
        <p
          className="kbot-strategy-editor__revision"
          data-testid="strategies-editor-csv-empty"
        >
          Save revision first.
        </p>
      ) : null}
    </>
  );
}
