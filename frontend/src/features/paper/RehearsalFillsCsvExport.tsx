import { useRef, useState, type JSX } from "react";
import { exportTimestamp } from "./PaperStatusCsvExport";
import type { RehearsalFill } from "./rehearsalClient";

/**
 * Client-side CSV export for the fills the rehearsal panel has actually
 * read (issue 106). The file contains exactly those ``recent_fills``
 * rows — coid, side, the exact ``ts_ms`` and the qty/price strings as
 * supplied (numeric precision preserved byte-for-byte) — plus an
 * explicit simulated-data provenance cell on every row. It is never a
 * full-history claim: rows the panel has not read are not exported.
 */

export type RehearsalFillsCsvExportProps = {
  fills: ReadonlyArray<RehearsalFill>;
};

const CSV_COLUMNS = ["coid", "side", "ts_ms", "qty", "price", "provenance"] as const;
const PROVENANCE = "simulated-rehearsal";

// RFC 4180: quote only when the field contains a comma, double quote or
// newline, doubling any embedded quotes.
function csvField(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

// Spreadsheet-formula neutralization for the free-form string fields
// (coid, side): a leading =, +, -, @, tab or CR would otherwise be
// interpreted as a formula by spreadsheet apps. The numeric fields
// (ts_ms, qty, price) are exported verbatim so their precision and
// value are exactly as provided.
const FORMULA_PREFIX = /^[=+\-@\t\r]/;

function guardFormula(value: string): string {
  return FORMULA_PREFIX.test(value) ? `'${value}` : value;
}

export function toRehearsalFillsCsv(
  fills: ReadonlyArray<RehearsalFill>,
): string {
  const lines = [CSV_COLUMNS.join(",")];
  for (const fill of fills) {
    lines.push(
      [
        csvField(guardFormula(fill.coid)),
        csvField(guardFormula(fill.side)),
        csvField(String(fill.ts_ms)),
        csvField(fill.qty),
        csvField(fill.price),
        PROVENANCE,
      ].join(","),
    );
  }
  return `${lines.join("\n")}\n`;
}

function transportDetail(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

type ExportOutcome =
  | { kind: "idle" }
  | { kind: "complete" }
  | { kind: "failed"; message: string };

const IDLE_STATUS =
  "Exports the simulated fills shown in this panel — not full history";

function busyStatusText(outcome: ExportOutcome): string {
  if (outcome.kind === "complete") {
    return "Simulated fills export complete";
  }
  if (outcome.kind === "failed") {
    return "Simulated fills export failed — no file downloaded";
  }
  return IDLE_STATUS;
}

export function RehearsalFillsCsvExport({
  fills,
}: RehearsalFillsCsvExportProps): JSX.Element {
  const [outcome, setOutcome] = useState<ExportOutcome>({ kind: "idle" });
  const inFlightRef = useRef(false);

  const handleClick = (): void => {
    if (fills.length === 0 || inFlightRef.current) {
      return;
    }
    inFlightRef.current = true;
    let url: string | null = null;
    try {
      // Build the complete CSV before creating any download artifact, so
      // a failure can never leave a partial file behind.
      const csv = toRehearsalFillsCsv(fills);
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `krellbot-rehearsal-fills-${exportTimestamp()}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
    } catch (reason) {
      if (url !== null) {
        URL.revokeObjectURL(url);
      }
      setOutcome({
        kind: "failed",
        message: `Visible fills export failed: ${transportDetail(
          reason,
        )}. No complete file was offered.`,
      });
      return;
    } finally {
      inFlightRef.current = false;
    }
    URL.revokeObjectURL(url);
    setOutcome({ kind: "complete" });
  };

  return (
    <>
      <button
        type="button"
        className="kbot-rehearsal__action"
        aria-keyshortcuts="Enter Space"
        disabled={fills.length === 0}
        data-testid="rehearsal-fills-csv-export"
        onClick={handleClick}
      >
        Export visible fills
      </button>
      <p
        role="status"
        aria-live="polite"
        data-testid="rehearsal-fills-csv-export-busy-status"
      >
        {busyStatusText(outcome)}
      </p>
      {outcome.kind === "failed" ? (
        <p
          className="kbot-rehearsal__error"
          role="alert"
          data-testid="rehearsal-fills-csv-export-error"
        >
          {outcome.message}
        </p>
      ) : null}
    </>
  );
}
