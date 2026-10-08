import { useEffect, useState, type JSX } from "react";
import {
  PaperCommandRefusalError,
  type PaperClient,
  type PaperStatus,
} from "./client";
import { PaperStatusCsvExport } from "./PaperStatusCsvExport";

export type { PaperClient, PaperStatus } from "./client";

export type StatusPanelProps = {
  client: PaperClient;
};

type EntriesSentence = "Entries active" | "Entries paused";

function sentenceFor(entries_paused: boolean | undefined): EntriesSentence {
  return entries_paused ? "Entries paused" : "Entries active";
}

type ExportReason =
  | "not armed"
  | "pack stored in live mode"
  | "venue/pair unavailable"
  | "";

function exportDisabledReason(status: PaperStatus | null): ExportReason {
  if (status === null || !status.armed) {
    return "not armed";
  }
  if (status.mode !== "paper") {
    return "pack stored in live mode";
  }
  if (!status.venue || !status.pair) {
    return "venue/pair unavailable";
  }
  return "";
}

function ExportButton({
  reason,
  pending,
  onExport,
}: {
  reason: ExportReason;
  pending: boolean;
  onExport: () => void;
}): JSX.Element {
  const disabledByStatus = reason !== "";
  return (
    <button
      type="button"
      data-testid="paper-export-btn"
      className="kbot-paper-status__action kbot-paper-status__action--export"
      disabled={disabledByStatus || pending}
      data-reason={disabledByStatus ? reason : undefined}
      onClick={onExport}
    >
      {pending
        ? "Downloading…"
        : disabledByStatus
          ? `Download pack — ${reason}`
          : "Download pack"}
    </button>
  );
}

export function StatusPanel({ client }: StatusPanelProps): JSX.Element {
  const [status, setStatus] = useState<PaperStatus | null>(null);
  const [sentence, setSentence] = useState<EntriesSentence>("Entries active");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [exportPending, setExportPending] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const applyStatus = (next: PaperStatus): void => {
    setStatus(next);
    setUnavailable(false);
    if (next.armed) {
      setSentence(sentenceFor(next.entries_paused));
    }
  };

  useEffect(() => {
    let cancelled = false;
    client
      .getStatus()
      .then((next) => {
        if (cancelled) {
          return;
        }
        applyStatus(next);
      })
      .catch(() => {
        if (cancelled) {
          return;
        }
        // A failed lookup means availability is unknown; never manufacture
        // an unarmed response, and never poll automatically.
        setStatus(null);
        setUnavailable(true);
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const handleRetry = async (): Promise<void> => {
    setErrorMessage(null);
    try {
      applyStatus(await client.getStatus());
    } catch {
      setStatus(null);
      setUnavailable(true);
    }
  };

  const refreshSentenceFromServer = async (): Promise<void> => {
    try {
      const next = await client.getStatus();
      applyStatus(next);
    } catch {
      // The sentence keeps its last good value on a transient failure;
      // the workstation is local-loopback so a refresh failure is rare.
    }
  };

  const handlePause = async (): Promise<void> => {
    if (!status?.armed || !status.venue || !status.pair) {
      return;
    }
    setErrorMessage(null);
    const result = await client.pauseEntries(status.venue, status.pair);
    if (result.ok) {
      setSentence("Entries paused");
      await refreshSentenceFromServer();
    } else {
      setErrorMessage(result.message ?? "Pause refused");
      // Refused command does not change the visible sentence.
    }
  };

  const handleResume = async (): Promise<void> => {
    if (!status?.armed || !status.venue || !status.pair) {
      return;
    }
    setErrorMessage(null);
    const result = await client.resumeEntries(status.venue, status.pair);
    if (result.ok) {
      setSentence("Entries active");
      await refreshSentenceFromServer();
    } else {
      setErrorMessage(result.message ?? "Resume refused");
    }
  };

  const handleDisarm = async (): Promise<void> => {
    if (!status?.armed || !status.venue || !status.pair) {
      return;
    }
    setErrorMessage(null);
    const result = await client.disarm(status.venue, status.pair);
    if (result.ok) {
      // After a successful disarm the workstation has no armed pack;
      // the panel hides the controls and clears the entries sentence.
      setStatus({ schema_version: "1", armed: false });
      setSentence("Entries active");
    } else {
      setErrorMessage(result.message ?? "Disarm refused");
    }
  };

  const handleExport = async (): Promise<void> => {
    if (exportPending) {
      return;
    }
    const reason = exportDisabledReason(status);
    if (reason !== "") {
      setExportError(`Download pack — ${reason}`);
      return;
    }
    const venue = status?.venue ?? "";
    const pair = status?.pair ?? "";
    setExportError(null);
    setExportPending(true);
    try {
      const exported = await client.exportPaperPack?.(venue, pair);
      if (!exported) {
        // A client without export support must not pretend a download happened.
        setExportError("paper export is unavailable in this build");
        return;
      }
      const blob = new Blob([exported.bytes], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      // No filename fabrication: the response's pack_id names the file when
      // present; only a response that truly omits it falls back to venue/pair.
      anchor.download =
        exported.filename ?? `krellbot-pack-${venue}-${pair}.json`;
      anchor.rel = "noopener";
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    } catch (thrown) {
      if (thrown instanceof PaperCommandRefusalError) {
        // The backend's own code and message explain the refusal truthfully.
        setExportError(
          `Download refused (${thrown.code}): ${thrown.message}`,
        );
      } else {
        setExportError("Download failed: unexpected error");
      }
    } finally {
      setExportPending(false);
    }
  };

  const paperControls =
    status?.armed === true &&
    status.venue &&
    status.pair &&
    status.mode === "paper";

  return (
    <section
      className="kbot-paper-status"
      role="region"
      aria-label="Paper controls"
      data-testid="paper-status-panel"
    >
      <header className="kbot-paper-status__head">
        <h2 className="kbot-paper-status__title">Paper status</h2>
      </header>
      <div className="kbot-paper-status__body">
        {paperControls ? (
          <>
            <p
              className="kbot-paper-status__entries"
              data-testid="paper-status-entries"
            >
              {sentence}
            </p>
            <p
              className="kbot-paper-status__pack"
              data-testid="paper-status-pack"
            >
              {status?.pack_id} on {status?.venue} {status?.pair}
            </p>
            <div className="kbot-paper-status__actions">
              <button
                type="button"
                className="kbot-paper-status__action"
                onClick={() => {
                  void handlePause();
                }}
              >
                Pause entries
              </button>
              <button
                type="button"
                className="kbot-paper-status__action"
                onClick={() => {
                  void handleResume();
                }}
              >
                Resume entries
              </button>
              <button
                type="button"
                className="kbot-paper-status__action"
                onClick={() => {
                  void handleDisarm();
                }}
              >
                Disarm
              </button>
              <PaperStatusCsvExport status={status} />
            </div>
            <div className="kbot-paper-status__export">
              <ExportButton
                reason={exportDisabledReason(status)}
                pending={exportPending}
                onExport={() => {
                  void handleExport();
                }}
              />
              {exportError !== null ? (
                <p
                  className="kbot-paper-status__error"
                  role="alert"
                  data-testid="paper-export-error"
                >
                  {exportError}
                </p>
              ) : null}
            </div>
            {errorMessage !== null ? (
              <p
                className="kbot-paper-status__error"
                role="alert"
                data-testid="paper-status-error"
              >
                {errorMessage}
              </p>
            ) : null}
          </>
        ) : status?.armed ? (
          <div className="kbot-paper-status__export">
            <p className="kbot-paper-status__empty" data-testid="paper-status-empty">
              Controls unavailable
            </p>
            <ExportButton
              reason={exportDisabledReason(status)}
              pending={exportPending}
              onExport={() => {
                void handleExport();
              }}
            />
            {exportError !== null ? (
              <p
                className="kbot-paper-status__error"
                role="alert"
                data-testid="paper-export-error"
              >
                {exportError}
              </p>
            ) : null}
          </div>
        ) : unavailable ? (
          <>
            <p
              className="kbot-paper-status__empty"
              role="alert"
              data-testid="paper-status-unavailable"
            >
              Paper status unavailable
            </p>
            <div className="kbot-paper-status__actions">
              <button
                type="button"
                className="kbot-paper-status__action"
                onClick={() => {
                  void handleRetry();
                }}
              >
                Retry status
              </button>
            </div>
          </>
        ) : status === null ? (
          // No response yet: availability is unknown, so no unarmed claim
          // and no command controls until a real status arrives.
          <p className="kbot-paper-status__empty" data-testid="paper-status-loading">
            Checking paper status…
          </p>
        ) : (
          <div className="kbot-paper-status__export">
            <p
              className="kbot-paper-status__empty"
              data-testid="paper-status-empty"
            >
              No pack armed
            </p>
            <ExportButton
              reason={exportDisabledReason(status)}
              pending={exportPending}
              onExport={() => {
                void handleExport();
              }}
            />
            {exportError !== null ? (
              <p
                className="kbot-paper-status__error"
                role="alert"
                data-testid="paper-export-error"
              >
                {exportError}
              </p>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}