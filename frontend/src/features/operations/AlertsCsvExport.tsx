import { useCallback, useRef, type JSX } from "react";
import type { AlertRow } from "./client";

const CSV_HEADER = [
  "id",
  "kind",
  "severity",
  "code",
  "venue",
  "pair",
  "count",
  "first_ts",
  "last_ts",
  "acknowledged",
] as const;

const EMPTY_EXPORT_TEXT = "No alerts to export.";
const FILENAME_PREFIX = "krellbot-alerts-";
const FILENAME_EXTENSION = ".csv";

// RFC 4180: quote only when the field contains a comma, double quote, or newline,
// doubling any embedded quotes.
function csvField(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

function alertFields(alert: AlertRow): string[] {
  return [
    alert.id,
    alert.kind,
    alert.severity,
    alert.code ?? "",
    alert.venue ?? "",
    alert.pair ?? "",
    String(alert.count),
    String(alert.first_ts),
    String(alert.last_ts),
    alert.acknowledged ? "true" : "false",
  ];
}

export function alertsToCsv(alerts: ReadonlyArray<AlertRow>): string {
  const lines = [CSV_HEADER.join(",")];
  for (const alert of alerts) {
    lines.push(alertFields(alert).map(csvField).join(","));
  }
  return `${lines.join("\n")}\n`;
}

function exportTimestamp(): string {
  return new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 14);
}

export type AlertsCsvExportProps = {
  alerts: ReadonlyArray<AlertRow>;
};

export function AlertsCsvExport({ alerts }: AlertsCsvExportProps): JSX.Element {
  // Rapid double-clicks each need their own filename so both downloads land.
  const exportCount = useRef(0);

  const handleExport = useCallback((): void => {
    if (alerts.length === 0) {
      return;
    }
    exportCount.current += 1;
    const collisionSuffix = exportCount.current > 1 ? `-${exportCount.current}` : "";
    const blob = new Blob([alertsToCsv(alerts)], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${FILENAME_PREFIX}${exportTimestamp()}${collisionSuffix}${FILENAME_EXTENSION}`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }, [alerts]);

  return (
    <div className="kbot-ops__alerts-export">
      <button
        type="button"
        data-testid="ops-alerts-csv-export"
        disabled={alerts.length === 0}
        onClick={handleExport}
      >
        Export CSV
      </button>
      {alerts.length === 0 ? (
        <p className="kbot-ops__empty" data-testid="ops-alerts-csv-empty">
          {EMPTY_EXPORT_TEXT}
        </p>
      ) : null}
    </div>
  );
}
