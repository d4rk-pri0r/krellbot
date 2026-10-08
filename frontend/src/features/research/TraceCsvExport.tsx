import type { JSX } from "react";

export type TraceCsvExportProps = {
  trace: Array<Record<string, unknown>>;
  jobId: string | null;
};

/**
 * Cell rendering for the CSV export. ``null`` (and a missing key) is an
 * empty cell; booleans and numbers stringify plainly; nested objects
 * and arrays are serialized as JSON so their content stays recoverable
 * (and gets CSV-quoted because JSON always contains commas).
 */
function formatCell(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value) ?? "";
    } catch {
      return "";
    }
  }
  return String(value);
}

/** RFC4180 quoting: wrap in quotes (doubling inner quotes) when needed. */
function escapeCell(cell: string): string {
  if (cell.includes(",") || cell.includes('"') || cell.includes("\n") || cell.includes("\r")) {
    return `"${cell.replaceAll('"', '""')}"`;
  }
  return cell;
}

/** Unique, lexicographically sorted union of every row's own keys. */
export function traceCsvColumns(
  trace: Array<Record<string, unknown>>,
): string[] {
  const keys = new Set<string>();
  for (const row of trace) {
    if (row !== null && typeof row === "object") {
      for (const key of Object.keys(row)) {
        keys.add(key);
      }
    }
  }
  return [...keys].sort();
}

export function buildTraceCsv(trace: Array<Record<string, unknown>>): string {
  const columns = traceCsvColumns(trace);
  const lines = [columns.map((column) => escapeCell(column)).join(",")];
  for (const row of trace) {
    const record =
      row !== null && typeof row === "object"
        ? (row as Record<string, unknown>)
        : {};
    lines.push(
      columns.map((column) => escapeCell(formatCell(record[column]))).join(","),
    );
  }
  return `${lines.join("\n")}\n`;
}

function timestampStamp(date: Date): string {
  const pad = (value: number): string => String(value).padStart(2, "0");
  return (
    `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}` +
    `${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`
  );
}

/**
 * Client-side trace CSV export. The columns are the sorted unique key
 * union across the loaded trace rows, missing keys export as empty
 * cells, and the download is produced entirely in the browser.
 */
export function TraceCsvExport({
  trace,
  jobId,
}: TraceCsvExportProps): JSX.Element {
  const hasRows = trace.length > 0;

  const handleClick = (): void => {
    if (!hasRows) {
      return;
    }
    const blob = new Blob([buildTraceCsv(trace)], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `krellbot-trace-${jobId ? jobId : "unk"}-${timestampStamp(new Date())}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  };

  return (
    <>
      {!hasRows ? (
        <p
          className="kbot-research__trace-empty"
          data-testid="research-trace-csv-empty"
        >
          No trace rows to export.
        </p>
      ) : null}
      <button
        type="button"
        className="kbot-research__action"
        data-testid="research-trace-csv-export"
        disabled={!hasRows}
        onClick={handleClick}
      >
        Export CSV
      </button>
    </>
  );
}
