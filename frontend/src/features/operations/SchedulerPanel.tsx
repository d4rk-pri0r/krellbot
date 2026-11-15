import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import "./SchedulerPanel.signal.css";
import type { OperationsClient, SchedulerStatus } from "./client";

const PANEL_TITLE = "Scheduler";
const LOADING_TEXT = "Loading scheduler status…";
const LOAD_ERROR_PREFIX =
  "Could not load scheduler status — check the workstation is running.";
const RETRY_TEXT = "Retry";
const INSTALL_LABEL = "Install";
const ENABLE_LABEL = "Enable";
const HELPER_TEXT =
  "Installs the OS hourly tick unit, then enables it on this machine. Paper ticks only in this release.";
const UNAVAILABLE_HEADING = "Platform enable is unavailable on this machine.";
const CLIENT_UNAVAILABLE =
  "Scheduler controls are unavailable in this build.";

export type SchedulerPanelProps = {
  client: OperationsClient;
};

/** True when last_error means this OS cannot enable the scheduler unit. */
export function isPlatformEnableUnavailable(lastError: string | null): boolean {
  if (lastError === null || lastError === "") {
    return false;
  }
  return /unsupported platform/i.test(lastError);
}

function describeStatus(status: SchedulerStatus): string {
  if (!status.installed) {
    return "Not installed.";
  }
  if (status.enabled) {
    return "Installed and enabled.";
  }
  return "Installed, not enabled.";
}

export function SchedulerPanel({ client }: SchedulerPanelProps): JSX.Element {
  const [status, setStatus] = useState<SchedulerStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<"install" | "enable" | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const requestRef = useRef(0);
  const inFlight = useRef(false);

  const hasClient =
    typeof client.getScheduler === "function" &&
    typeof client.installScheduler === "function" &&
    typeof client.enableScheduler === "function";

  const load = useCallback(async (): Promise<void> => {
    if (!hasClient) {
      setStatus(null);
      setError(CLIENT_UNAVAILABLE);
      setLoading(false);
      return;
    }
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const next = await client.getScheduler!();
      if (requestId !== requestRef.current) {
        return;
      }
      setStatus(next);
    } catch (err) {
      if (requestId !== requestRef.current) {
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (requestId === requestRef.current) {
        setLoading(false);
      }
    }
  }, [client, hasClient]);

  useEffect(() => {
    void load();
  }, [load]);

  const platformUnavailable = isPlatformEnableUnavailable(status?.last_error ?? null);
  const busy = pending !== null || loading;

  const handleInstall = useCallback(async (): Promise<void> => {
    if (inFlight.current || !hasClient || typeof client.installScheduler !== "function") {
      return;
    }
    inFlight.current = true;
    setPending("install");
    setFeedback(null);
    try {
      const next = await client.installScheduler();
      setStatus(next);
      if (next.last_error) {
        setFeedback(`Install finished with error: ${next.last_error}`);
      } else if (next.installed) {
        setFeedback("Scheduler unit installed.");
      } else {
        setFeedback("Install did not report installed.");
      }
    } catch (err) {
      setFeedback(`Install failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      inFlight.current = false;
      setPending(null);
    }
  }, [client, hasClient]);

  const handleEnable = useCallback(async (): Promise<void> => {
    if (
      inFlight.current ||
      !hasClient ||
      typeof client.enableScheduler !== "function" ||
      platformUnavailable
    ) {
      return;
    }
    inFlight.current = true;
    setPending("enable");
    setFeedback(null);
    try {
      const next = await client.enableScheduler();
      setStatus(next);
      if (isPlatformEnableUnavailable(next.last_error)) {
        setFeedback(null);
      } else if (next.last_error) {
        setFeedback(`Enable finished with error: ${next.last_error}`);
      } else if (next.enabled) {
        setFeedback("Scheduler enabled.");
      } else {
        setFeedback("Enable did not report enabled.");
      }
    } catch (err) {
      setFeedback(`Enable failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      inFlight.current = false;
      setPending(null);
    }
  }, [client, hasClient, platformUnavailable]);

  const installDisabled = busy || !hasClient || status?.installed === true;
  const enableDisabled =
    busy ||
    !hasClient ||
    status === null ||
    !status.installed ||
    status.enabled ||
    platformUnavailable;

  return (
    <div className="kbot-ops__scheduler" data-testid="ops-scheduler">
      <div className="kbot-ops__scheduler-head">
        <h3 className="kbot-ops__panel-title">{PANEL_TITLE}</h3>
        <button
          type="button"
          className="kbot-ops__scheduler-refresh"
          data-testid="ops-scheduler-refresh"
          disabled={busy}
          aria-busy={loading || undefined}
          onClick={() => {
            void load();
          }}
        >
          {loading ? "Loading…" : RETRY_TEXT}
        </button>
      </div>

      {loading && status === null && error === null ? (
        <p className="kbot-ops__scheduler-status" data-testid="ops-scheduler-loading">
          {LOADING_TEXT}
        </p>
      ) : null}

      {error !== null ? (
        <p className="kbot-ops__scheduler-error" role="alert" data-testid="ops-scheduler-error">
          {error === CLIENT_UNAVAILABLE ? error : `${LOAD_ERROR_PREFIX} (${error})`}
        </p>
      ) : null}

      {status !== null ? (
        <>
          <p className="kbot-ops__scheduler-status" data-testid="ops-scheduler-status">
            {describeStatus(status)}
          </p>

          <dl className="kbot-ops__scheduler-flags" data-testid="ops-scheduler-flags">
            <div>
              <dt>Installed</dt>
              <dd data-testid="ops-scheduler-installed">{status.installed ? "yes" : "no"}</dd>
            </div>
            <div>
              <dt>Enabled</dt>
              <dd data-testid="ops-scheduler-enabled">{status.enabled ? "yes" : "no"}</dd>
            </div>
          </dl>

          {platformUnavailable ? (
            <p
              className="kbot-ops__scheduler-unavailable"
              role="status"
              data-testid="ops-scheduler-unavailable"
            >
              <span data-testid="ops-scheduler-unavailable-heading">{UNAVAILABLE_HEADING}</span>{" "}
              <span data-testid="ops-scheduler-unavailable-reason">{status.last_error}</span>
            </p>
          ) : null}

          {!platformUnavailable && status.last_error !== null ? (
            <p
              className="kbot-ops__scheduler-last-error"
              role="status"
              data-testid="ops-scheduler-last-error"
            >
              Last error: {status.last_error}
            </p>
          ) : null}

          <div className="kbot-ops__scheduler-buttons">
            <button
              type="button"
              className="kbot-ops__scheduler-install"
              data-testid="ops-scheduler-install"
              disabled={installDisabled}
              aria-busy={pending === "install" || undefined}
              onClick={() => {
                void handleInstall();
              }}
            >
              {INSTALL_LABEL}
            </button>
            <button
              type="button"
              className="kbot-ops__scheduler-enable"
              data-testid="ops-scheduler-enable"
              disabled={enableDisabled}
              aria-busy={pending === "enable" || undefined}
              onClick={() => {
                void handleEnable();
              }}
            >
              {ENABLE_LABEL}
            </button>
          </div>

          {feedback !== null ? (
            <p
              className="kbot-ops__scheduler-feedback"
              role="status"
              data-testid="ops-scheduler-feedback"
            >
              {feedback}
            </p>
          ) : null}

          <p className="kbot-ops__scheduler-helper">{HELPER_TEXT}</p>
        </>
      ) : null}
    </div>
  );
}
