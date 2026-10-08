import { useCallback, type JSX } from "react";
import type { JobRow } from "../../shell/JobsDrawer";
import { exportJobsCsvFilename, jobsCsvBody } from "./jobsCsv";

export type JobsDrawerCsvExportProps = {
  jobs: ReadonlyArray<JobRow>;
  disabled?: boolean;
};

function utcTimestamp(): string {
  return new Date()
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\.\d{3}/, "");
}

export function JobsDrawerCsvExport({
  jobs,
  disabled = false,
}: JobsDrawerCsvExportProps): JSX.Element {
  const download = useCallback((): void => {
    const blob = new Blob([jobsCsvBody(jobs)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = exportJobsCsvFilename(utcTimestamp());
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }, [jobs]);

  return (
    <button
      type="button"
      data-testid="jobs-drawer-csv-export"
      className="kbot-jobs__export"
      disabled={disabled || jobs.length === 0}
      onClick={download}
    >
      Export CSV
    </button>
  );
}
