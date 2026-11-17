import { useCallback, useId, useState, type JSX } from "react";
import {
  createHomeRestoreHttpClient,
  type HomeRestoreClient,
  type HomeRestoreResult,
} from "./homeRestoreClient";
import "./HomeRestorePanel.signal.css";

const PANEL_TITLE = "Home restore";
const HELPER_TEXT =
  "Restore a local home backup into an empty workstation home. A successful restore engages the kill switch and pauses live entries. While this paper-only release is active, restore never makes the workstation live-ready. Corrupt archives are refused without destroying a good home.";
const FENCE_TEXT =
  "Restore fence: entries paused and kill switch engaged until you release them. Never live-ready after restore on a paper-only release.";
const CHOOSE_LABEL = "Choose backup archive";
const RESTORE_LABEL = "Restore home backup";
const BUSY_LABEL = "Restoring…";
const CLIENT_UNAVAILABLE = "Home restore client unavailable.";

export type HomeRestorePanelProps = {
  client?: HomeRestoreClient;
};

function summarizeResult(result: HomeRestoreResult): string {
  if (result.applied && result.ok) {
    return `Restored. Fence engaged${result.kill_reason ? `: ${result.kill_reason}` : ""}. Not live-ready.`;
  }
  if (result.code === "home_not_empty") {
    return result.message;
  }
  return result.message || `Restore refused (${result.code}).`;
}

export function HomeRestorePanel({
  client,
}: HomeRestorePanelProps): JSX.Element {
  const resolved = client ?? createHomeRestoreHttpClient();
  const hasClient = typeof resolved.restoreHome === "function";
  const inputId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [liveReadyClaim, setLiveReadyClaim] = useState(false);

  const handleRestore = useCallback(async (): Promise<void> => {
    if (!hasClient || pending || file === null) {
      return;
    }
    setPending(true);
    setError(null);
    setFeedback(null);
    setLiveReadyClaim(false);
    try {
      const result = await resolved.restoreHome(file);
      setLiveReadyClaim(result.live_ready === true);
      if (result.ok && result.applied) {
        setFeedback(summarizeResult(result));
      } else if (result.code === "home_not_empty") {
        setFeedback(summarizeResult(result));
      } else {
        setError(summarizeResult(result));
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    } finally {
      setPending(false);
    }
  }, [file, hasClient, pending, resolved]);

  return (
    <div className="kbot-ops__home-restore" data-testid="ops-home-restore">
      <div className="kbot-ops__home-restore-head">
        <h2 className="kbot-ops__panel-title" id="ops-home-restore-title">
          {PANEL_TITLE}
        </h2>
      </div>
      <p className="kbot-ops__home-restore-helper">{HELPER_TEXT}</p>
      <p
        className="kbot-ops__home-restore-fence"
        data-testid="ops-home-restore-fence-copy"
      >
        {FENCE_TEXT}
      </p>

      {!hasClient ? (
        <p
          className="kbot-ops__home-restore-error"
          role="alert"
          data-testid="ops-home-restore-unavailable"
        >
          {CLIENT_UNAVAILABLE}
        </p>
      ) : null}

      {error !== null ? (
        <p
          className="kbot-ops__home-restore-error"
          role="alert"
          data-testid="ops-home-restore-error"
        >
          {error}
        </p>
      ) : null}

      {feedback !== null ? (
        <p
          className="kbot-ops__home-restore-feedback"
          role="status"
          data-testid="ops-home-restore-feedback"
        >
          {feedback}
        </p>
      ) : null}

      <p
        className="kbot-ops__home-restore-live-ready"
        data-testid="ops-home-restore-live-ready"
        hidden={liveReadyClaim}
      >
        Live-ready after restore: no
      </p>

      <label className="kbot-ops__home-restore-file-label" htmlFor={inputId}>
        {CHOOSE_LABEL}
        <input
          id={inputId}
          className="kbot-ops__home-restore-file"
          data-testid="ops-home-restore-file"
          type="file"
          accept=".tar.gz,application/gzip"
          disabled={!hasClient || pending}
          onChange={(event) => {
            const next = event.target.files?.[0] ?? null;
            setFile(next);
            setError(null);
            setFeedback(null);
          }}
        />
      </label>

      <button
        type="button"
        className="kbot-ops__home-restore-button"
        data-testid="ops-home-restore-submit"
        disabled={!hasClient || pending || file === null}
        aria-busy={pending || undefined}
        onClick={() => {
          void handleRestore();
        }}
      >
        {pending ? BUSY_LABEL : RESTORE_LABEL}
      </button>
    </div>
  );
}
