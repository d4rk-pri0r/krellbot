import { useCallback, useState, type JSX } from "react";
import {
  createHomeExportHttpClient,
  type HomeExportClient,
} from "./homeExportClient";
import "./HomeExportPanel.signal.css";

const PANEL_TITLE = "Home export";
const HELPER_TEXT =
  "Download a local backup archive of this workstation home. Export stays available when the store is down; the archive never leaves this machine.";
const EXPORT_LABEL = "Download home backup";
const BUSY_LABEL = "Creating backup…";
const SUCCESS_TEXT = "Backup downloaded.";
const CLIENT_UNAVAILABLE = "Home export client unavailable.";

export type HomeExportPanelProps = {
  client?: HomeExportClient;
  /** Test seam: override browser download trigger. */
  triggerDownload?: (blob: Blob, filename: string) => void;
};

function defaultTriggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

export function HomeExportPanel({
  client,
  triggerDownload = defaultTriggerDownload,
}: HomeExportPanelProps): JSX.Element {
  const resolved = client ?? createHomeExportHttpClient();
  const hasClient = typeof resolved.exportHome === "function";
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const handleExport = useCallback(async (): Promise<void> => {
    if (!hasClient || pending) {
      return;
    }
    setPending(true);
    setError(null);
    setFeedback(null);
    try {
      const result = await resolved.exportHome();
      triggerDownload(result.blob, result.filename);
      setFeedback(SUCCESS_TEXT);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    } finally {
      setPending(false);
    }
  }, [hasClient, pending, resolved, triggerDownload]);

  return (
    <div className="kbot-ops__home-export" data-testid="ops-home-export">
      <div className="kbot-ops__home-export-head">
        <h2 className="kbot-ops__panel-title" id="ops-home-export-title">
          {PANEL_TITLE}
        </h2>
      </div>
      <p className="kbot-ops__home-export-helper">{HELPER_TEXT}</p>

      {!hasClient ? (
        <p
          className="kbot-ops__home-export-error"
          role="alert"
          data-testid="ops-home-export-unavailable"
        >
          {CLIENT_UNAVAILABLE}
        </p>
      ) : null}

      {error !== null ? (
        <p
          className="kbot-ops__home-export-error"
          role="alert"
          data-testid="ops-home-export-error"
        >
          {error}
        </p>
      ) : null}

      {feedback !== null ? (
        <p
          className="kbot-ops__home-export-feedback"
          role="status"
          data-testid="ops-home-export-feedback"
        >
          {feedback}
        </p>
      ) : null}

      <button
        type="button"
        className="kbot-ops__home-export-button"
        data-testid="ops-home-export-download"
        disabled={!hasClient || pending}
        aria-busy={pending || undefined}
        onClick={() => {
          void handleExport();
        }}
      >
        {pending ? BUSY_LABEL : EXPORT_LABEL}
      </button>
    </div>
  );
}
