import { useCallback, useEffect, useState, type JSX } from "react";
import type { OperationsClient, OperationsViewModel } from "./client";

const DISABLED_BANNER =
  "Live trading is disabled in this build (KRELLBOT_ENABLE_LIVE is not 1).";
const NO_GRANTS_BANNER =
  "Live trading is not authorized: no operator grant on file.";
const PROMO_DEFERRED_TEXT = "Promotion to live is owner-deferred.";
const KILL_RELEASED_TEXT = "Kill switch: released";
const KILL_HELPER =
  "Engaging stops new entries and all live sends. It does not sell or disarm.";
const NO_ALERTS_TEXT = "No alerts.";
const PROMO_REVISION_ID = "deployment";

export type { OperationsClient } from "./client";
export type OperationsViewProps = {
  client: OperationsClient;
};

function rowId(venue: string, pair: string): string {
  return `ops-deployment-${venue}-${pair}`.replace(/\//g, "-");
}

function promoteButtonId(venue: string, pair: string): string {
  return `ops-promote-${venue}-${pair}`.replace(/\//g, "-");
}

function promoteResultId(venue: string, pair: string): string {
  return `ops-promote-result-${venue}-${pair}`.replace(/\//g, "-");
}

function pauseButtonId(venue: string, pair: string): string {
  return `ops-pause-${venue}-${pair}`.replace(/\//g, "-");
}

function resumeButtonId(venue: string, pair: string): string {
  return `ops-resume-${venue}-${pair}`.replace(/\//g, "-");
}

function pauseResultId(venue: string, pair: string): string {
  return `ops-pause-result-${venue}-${pair}`.replace(/\//g, "-");
}

function resumeResultId(venue: string, pair: string): string {
  return `ops-resume-result-${venue}-${pair}`.replace(/\//g, "-");
}

function ackId(alertId: string): string {
  return `ops-alert-ack-${alertId}`;
}

function alertRowId(alertId: string): string {
  return `ops-alert-${alertId}`;
}

function killStateText(engaged: boolean, reason: string | null): string {
  if (!engaged) {
    return KILL_RELEASED_TEXT;
  }
  return `Kill switch: engaged — ${reason ?? "(no reason)"}`;
}

function renderLiveBanner(live: OperationsViewModel["live"]): JSX.Element {
  const { live_enabled, authorized } = live;
  if (!live_enabled) {
    return (
      <p data-testid="ops-live-status">
        <span>{DISABLED_BANNER}</span>
        <span> {PROMO_DEFERRED_TEXT}</span>
      </p>
    );
  }
  if (authorized.length === 0) {
    return (
      <p data-testid="ops-live-status">
        <span>{NO_GRANTS_BANNER}</span>
        <span> {PROMO_DEFERRED_TEXT}</span>
      </p>
    );
  }
  return (
    <p data-testid="ops-live-status">
      <span>
        Live trading authorized for{" "}
        {authorized.map((g: { venue: string; pair: string }) => `${g.venue} ${g.pair}`).join(", ")}.
      </span>
      <span> {PROMO_DEFERRED_TEXT}</span>
    </p>
  );
}

export function OperationsView({ client }: OperationsViewProps): JSX.Element {
  const [view, setView] = useState<OperationsViewModel | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [killReason, setKillReason] = useState<string>("");
  const [promoteResults, setPromoteResults] = useState<
    Record<string, { code: string; message: string }>
  >({});
  const [pauseResults, setPauseResults] = useState<
    Record<string, { code: string; ok: boolean; message: string }>
  >({});
  const [resumeResults, setResumeResults] = useState<
    Record<string, { code: string; ok: boolean; message: string }>
  >({});

  const refresh = useCallback(async (): Promise<void> => {
    try {
      const next = await client.getOperations();
      setView(next);
      setFetchError(null);
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : String(err));
    }
  }, [client]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handlePromote = useCallback(
    async (venue: string, pair: string): Promise<void> => {
      const result = await client.promote(venue, pair, PROMO_REVISION_ID);
      const key = promoteButtonId(venue, pair);
      const code = typeof result.code === "string" ? result.code : "refused";
      const message = typeof result.message === "string" ? result.message : "live promotion refused";
      setPromoteResults((prev) => ({ ...prev, [key]: { code, message } }));
      await refresh();
    },
    [client, refresh],
  );

  const handlePause = useCallback(
    async (venue: string, pair: string): Promise<void> => {
      const result = await client.pauseEntries(venue, pair);
      const key = pauseButtonId(venue, pair);
      setPauseResults((prev) => ({
        ...prev,
        [key]: {
          code: typeof result.code === "string" ? result.code : "unknown",
          ok: result.ok === true,
          message:
            typeof result.message === "string" ? result.message : "pause command refused",
        },
      }));
      await refresh();
    },
    [client, refresh],
  );

  const handleResume = useCallback(
    async (venue: string, pair: string): Promise<void> => {
      const result = await client.resumeEntries(venue, pair);
      const key = resumeButtonId(venue, pair);
      setResumeResults((prev) => ({
        ...prev,
        [key]: {
          code: typeof result.code === "string" ? result.code : "unknown",
          ok: result.ok === true,
          message:
            typeof result.message === "string" ? result.message : "resume command refused",
        },
      }));
      await refresh();
    },
    [client, refresh],
  );

  const handleEngage = useCallback(async (): Promise<void> => {
    const trimmed = killReason.trim();
    if (!trimmed) {
      return;
    }
    await client.engageKill(trimmed);
    setKillReason("");
    await refresh();
  }, [client, killReason, refresh]);

  const handleRelease = useCallback(async (): Promise<void> => {
    await client.releaseKill();
    await refresh();
  }, [client, refresh]);

  const handleAck = useCallback(
    async (alertId: string): Promise<void> => {
      await client.ackAlert(alertId);
      await refresh();
    },
    [client, refresh],
  );

  if (view === null && fetchError === null) {
    return (
      <section className="kbot-ops" data-testid="operations-view">
        <p className="kbot-ops__empty">Loading operations…</p>
      </section>
    );
  }

  if (view === null) {
    return (
      <section className="kbot-ops" data-testid="operations-view">
        <p className="kbot-ops__empty" role="alert">
          Failed to load operations view: {fetchError}
        </p>
      </section>
    );
  }

  const killEngaged = view.live.kill_switch.engaged;

  return (
    <section className="kbot-ops" data-testid="operations-view">
      <header className="kbot-ops__head">
        <h2 className="kbot-ops__title">Operations</h2>
      </header>
      <div className="kbot-ops__body">
        <section className="kbot-ops__panel" aria-label="Live status">
          {renderLiveBanner(view.live)}
        </section>

        <section className="kbot-ops__panel" aria-label="Kill switch" data-testid="ops-kill">
          <p className="kbot-ops__kill-state">
            {killStateText(view.live.kill_switch.engaged, view.live.kill_switch.reason)}
          </p>
          <div className="kbot-ops__kill-row">
            <label className="kbot-ops__kill-label" htmlFor="ops-kill-reason-input">
              Reason
            </label>
            <input
              id="ops-kill-reason-input"
              data-testid="ops-kill-reason"
              type="text"
              value={killReason}
              onChange={(event) => setKillReason(event.target.value)}
              placeholder="Operator reason"
            />
          </div>
          <div className="kbot-ops__kill-buttons">
            <button
              type="button"
              data-testid="ops-kill-engage"
              disabled={killReason.trim() === ""}
              onClick={() => {
                void handleEngage();
              }}
            >
              Engage kill switch
            </button>
            {killEngaged ? (
              <button
                type="button"
                data-testid="ops-kill-release"
                onClick={() => {
                  void handleRelease();
                }}
              >
                Release kill switch
              </button>
            ) : null}
          </div>
          <p className="kbot-ops__kill-helper">{KILL_HELPER}</p>
        </section>

        <section className="kbot-ops__panel" aria-label="Deployments">
          <h3 className="kbot-ops__panel-title">Deployments</h3>
          <table className="kbot-ops__table" data-testid="ops-deployments">
            <thead>
              <tr>
                <th>Pack</th>
                <th>Venue</th>
                <th>Pair</th>
                <th>Mode</th>
                <th>Entries</th>
                <th>Controls</th>
              </tr>
            </thead>
            <tbody>
              {view.deployments.length === 0 ? (
                <tr>
                  <td colSpan={6} className="kbot-ops__empty">
                    No deployments.
                  </td>
                </tr>
              ) : (
                view.deployments.map((deployment: OperationsViewModel["deployments"][number]) => {
                  const key = `${deployment.venue}-${deployment.pair}`;
                  const promoKey = promoteButtonId(deployment.venue, deployment.pair);
                  const promoteResult = promoteResults[promoKey];
                  const pauseKey = pauseButtonId(deployment.venue, deployment.pair);
                  const pauseResult = pauseResults[pauseKey];
                  const resumeKey = resumeButtonId(deployment.venue, deployment.pair);
                  const resumeResult = resumeResults[resumeKey];
                  return (
                    <tr key={key} data-testid={rowId(deployment.venue, deployment.pair)}>
                      <td>{deployment.pack_id}</td>
                      <td>{deployment.venue}</td>
                      <td>{deployment.pair}</td>
                      <td>{deployment.mode}</td>
                      <td>{deployment.entries_paused ? "paused" : "active"}</td>
                      <td>
                        <div className="kbot-ops__row-actions">
                          <button
                            type="button"
                            data-testid={pauseButtonId(deployment.venue, deployment.pair)}
                            onClick={() => {
                              void handlePause(deployment.venue, deployment.pair);
                            }}
                          >
                            Pause entries
                          </button>
                          <button
                            type="button"
                            data-testid={resumeButtonId(deployment.venue, deployment.pair)}
                            onClick={() => {
                              void handleResume(deployment.venue, deployment.pair);
                            }}
                          >
                            Resume entries
                          </button>
                          <button
                            type="button"
                            data-testid={promoteButtonId(deployment.venue, deployment.pair)}
                            onClick={() => {
                              void handlePromote(deployment.venue, deployment.pair);
                            }}
                          >
                            Promote to live candidate
                          </button>
                        </div>
                        {promoteResult ? (
                          <p
                            className="kbot-ops__row-result"
                            role="status"
                            data-testid={promoteResultId(deployment.venue, deployment.pair)}
                          >
                            Refused: {promoteResult.code} — {promoteResult.message}
                          </p>
                        ) : null}
                        {pauseResult && !pauseResult.ok ? (
                          <p
                            className="kbot-ops__row-result"
                            role="status"
                            data-testid={pauseResultId(deployment.venue, deployment.pair)}
                          >
                            Refused: {pauseResult.code} — {pauseResult.message}
                          </p>
                        ) : null}
                        {resumeResult && !resumeResult.ok ? (
                          <p
                            className="kbot-ops__row-result"
                            role="status"
                            data-testid={resumeResultId(deployment.venue, deployment.pair)}
                          >
                            Refused: {resumeResult.code} — {resumeResult.message}
                          </p>
                        ) : null}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </section>

        <section className="kbot-ops__panel" aria-label="Alerts">
          <h3 className="kbot-ops__panel-title">Alerts</h3>
          <ul className="kbot-ops__alerts" data-testid="ops-alerts">
            {view.alerts.length === 0 ? (
              <li className="kbot-ops__empty">{NO_ALERTS_TEXT}</li>
            ) : (
              view.alerts.map((alert: OperationsViewModel["alerts"][number]) => (
                <li
                  key={alert.id}
                  className={`kbot-ops__alert kbot-ops__alert--${alert.severity}`}
                  data-testid={alertRowId(alert.id)}
                >
                  <span className="kbot-ops__alert-kind">{alert.kind}</span>
                  <span className="kbot-ops__alert-severity">{alert.severity}</span>
                  <span className="kbot-ops__alert-code">{alert.code ?? "-"}</span>
                  <span className="kbot-ops__alert-target">
                    {alert.venue ?? "-"} {alert.pair ?? ""}
                  </span>
                  <span className="kbot-ops__alert-count">×{alert.count}</span>
                  <span className="kbot-ops__alert-ts">
                    last {new Date(alert.last_ts * 1000).toISOString().replace("T", " ").slice(0, 19)}
                  </span>
                  {alert.acknowledged ? (
                    <span className="kbot-ops__alert-ack">acknowledged</span>
                  ) : (
                    <button
                      type="button"
                      data-testid={ackId(alert.id)}
                      onClick={() => {
                        void handleAck(alert.id);
                      }}
                    >
                      Acknowledge
                    </button>
                  )}
                </li>
              ))
            )}
          </ul>
        </section>
      </div>
    </section>
  );
}