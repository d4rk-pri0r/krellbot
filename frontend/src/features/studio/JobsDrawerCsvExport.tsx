import { useCallback, useState, type JSX } from "react";
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

const EXPORT_FAILED_STATUS = "Could not start the CSV download. Try again.";

/**
 * Prepare and activate the download anchor, releasing every resource
 * this function actually allocated or attached on every path. Returns
 * whether browser-side download activation completed without throwing.
 */
function activateDownload(jobs: ReadonlyArray<JobRow>): boolean {
  let url: string | null = null;
  let anchor: HTMLAnchorElement | null = null;
  let attached = false;
  try {
    const blob = new Blob([jobsCsvBody(jobs)], { type: "text/csv;charset=utf-8" });
    url = URL.createObjectURL(blob);
    anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = exportJobsCsvFilename(utcTimestamp());
    document.body.appendChild(anchor);
    attached = true;
    anchor.click();
    return true;
  } catch {
    // A generic status only; the thrown value is never surfaced.
    return false;
  } finally {
    if (anchor !== null && attached) {
      try {
        document.body.removeChild(anchor);
      } catch {
        try {
          anchor.remove();
        } catch {
          // Detach is best-effort; never let cleanup rethrow.
        }
      }
    }
    if (url !== null) {
      try {
        URL.revokeObjectURL(url);
      } catch {
        // Revoke is best-effort; never let cleanup rethrow.
      }
    }
  }
}

export function JobsDrawerCsvExport({
  jobs,
  disabled = false,
}: JobsDrawerCsvExportProps): JSX.Element {
  const [failed, setFailed] = useState<boolean>(false);

  const download = useCallback((): void => {
    // Successful activation clears a prior failure; it deliberately
    // claims nothing about the file reaching disk.
    setFailed(!activateDownload(jobs));
  }, [jobs]);

  return (
    <>
      <button
        type="button"
        data-testid="jobs-drawer-csv-export"
        className="kbot-jobs__export"
        disabled={disabled || jobs.length === 0}
        onClick={download}
      >
        Export CSV
      </button>
      <p
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="kbot-palette__label"
      >
        {failed ? EXPORT_FAILED_STATUS : ""}
      </p>
    </>
  );
}
