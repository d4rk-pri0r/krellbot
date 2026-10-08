import type { JSX } from "react";
import type { PaperStatus } from "./client";

export type { PaperStatus } from "./client";

export type PaperStatusCsvExportProps = {
  status: PaperStatus | null;
};

const CSV_COLUMNS = [
  "schema_version",
  "armed",
  "venue",
  "pair",
  "entries_paused",
  "mode",
  "pack_id",
] as const;

// Same UTC ISO→yyyymmddHHMMSS shape as the alerts CSV export slice.
export function exportTimestamp(date: Date = new Date()): string {
  return date.toISOString().replace(/[-:TZ.]/g, "").slice(0, 14);
}

function csvField(value: string): string {
  if (/[",\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

export function toPaperStatusCsv(status: PaperStatus): string {
  const cells = CSV_COLUMNS.map((column) => {
    const value = status[column];
    if (value === undefined || value === null) {
      return "";
    }
    return csvField(String(value));
  });
  return `${CSV_COLUMNS.join(",")}\n${cells.join(",")}`;
}

function downloadCsv(csv: string, filename: string): void {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

export function PaperStatusCsvExport({
  status,
}: PaperStatusCsvExportProps): JSX.Element | null {
  if (
    status === null ||
    status.armed !== true ||
    !status.venue ||
    !status.pair ||
    status.mode !== "paper"
  ) {
    return null;
  }

  const handleClick = (): void => {
    const csv = toPaperStatusCsv(status);
    downloadCsv(csv, `krellbot-paper-status-${exportTimestamp()}.csv`);
  };

  return (
    <button
      type="button"
      id="paper-status-csv-export"
      data-testid="paper-status-csv-export"
      className="kbot-paper-status__action"
      onClick={handleClick}
    >
      Export CSV
    </button>
  );
}
