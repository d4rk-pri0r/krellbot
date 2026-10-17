import type { DeploymentRow } from "./client";

const CSV_MIME_TYPE = "text/csv;charset=utf-8";

export type DeploymentCsvExportRow = {
  pack_id: string;
  venue: string;
  pair: string;
  mode: string;
  entries_paused?: boolean;
};

/**
 * Escape a single CSV field per RFC 4180: quote only when the field contains a
 * comma, a double quote, or a line break, doubling embedded double quotes.
 * Embedded newlines are preserved inside the quoted field.
 */
export function deploymentCsvField(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

/**
 * Column headers for the deployment snapshot export. The Controls column is
 * omitted because its cells are action buttons, not data.
 */
export function deploymentCsvHeader(): string[] {
  return ["pack_id", "venue", "pair", "mode", "entries"];
}

export function deploymentCsvRow(deployment: DeploymentCsvExportRow): string[] {
  return [
    deployment.pack_id,
    deployment.venue,
    deployment.pair,
    deployment.mode,
    deployment.entries_paused === true ? "paused" : "active",
  ];
}

/**
 * Build the full CSV document (header + rows) joined with CRLF line breaks.
 * An empty list yields the empty string so the export control can stay inert.
 */
export function deploymentCsvBody(
  deployments: ReadonlyArray<DeploymentCsvExportRow>,
): string {
  if (deployments.length === 0) {
    return "";
  }
  const lines = [
    deploymentCsvHeader(),
    ...deployments.map((deployment) => deploymentCsvRow(deployment)),
  ];
  return lines
    .map((line) => line.map(deploymentCsvField).join(","))
    .join("\r\n");
}

export function deploymentsCsvBlob(
  deployments: ReadonlyArray<DeploymentCsvExportRow>,
): Blob {
  return new Blob([deploymentCsvBody(deployments)], { type: CSV_MIME_TYPE });
}
