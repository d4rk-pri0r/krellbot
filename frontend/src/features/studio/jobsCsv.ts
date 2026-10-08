import type { JobRow } from "../../shell/JobsDrawer";

/** RFC 4180 field escaping: quote only when the field needs it. */
export function jobsCsvField(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

export function jobsCsvHeader(): readonly ["id", "kind", "state"] {
  return ["id", "kind", "state"];
}

export function jobsCsvRow(row: JobRow): [string, string, string] {
  return [row.id, row.kind, row.state];
}

export function jobsCsvBody(jobs: ReadonlyArray<JobRow>): string {
  const lines = [jobsCsvHeader().map(jobsCsvField).join(",")];
  for (const job of jobs) {
    lines.push(jobsCsvRow(job).map(jobsCsvField).join(","));
  }
  return lines.join("\n");
}

export function exportJobsCsvFilename(timestamp: string): string {
  return `krellbot-jobs-${timestamp}.csv`;
}
