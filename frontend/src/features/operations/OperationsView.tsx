import { useCallback, useEffect, useState, type JSX } from "react";
import "./OperationsView.signal.css";
import { AlertsFilter } from "./AlertsFilter";
import { DeploymentHistory } from "./DeploymentHistory";
import { summarizeOperationMode } from "./operationModeLabel";
import { summarizeDeploymentRefused } from "./deploymentRefusedSummary";
import { DeploymentsCsvExport } from "./DeploymentsCsvExport";
import { AlertsCsvExport } from "./AlertsCsvExport";
import { AcknowledgedAlertsList } from "./AcknowledgedAlertsList";
import { summarizeAlertKind } from "./alertKindLabel";
import { useOperationsRefresh } from "./useOperationsRefresh";
import { summarizeAlertCode } from "./alertCodeLabel";
import type { AlertRow, OperationsClient, OperationsViewModel } from "./client";
import { summarizeAlertSeverity } from "./alertSeverityLabel";

const DISABLED_BANNER =
  "Live trading is disabled in this build (KRELLBOT_ENABLE_LIVE is not 1).";
const NO_GRANTS_BANNER =
  "Live trading is not authorized: no operator grant on file.";
const PROMO_DEFERRED_TEXT = "Promotion to live is owner-deferred.";
const KILL_RELEASED_TEXT = "Kill switch: released";
const KILL_HELPER =
  "Engaging stops new entries and all live sends. It does not sell or disarm.";
const NO_ALERTS_TEXT = "No alerts.";
const NO_DEPLOYMENTS_TEXT = "No deployments.";
const PROMO_REVISION_ID = "deployment";
const STALE_PREFIX = "Operations state may be stale";
const STALE_SUFFIX =
  "showing last known state from the previous successful read — not current server state";
const UNKNOWN_OUTCOME_TEXT =
  "outcome unknown: the command may not have been sent or applied — check state before retrying";
const LAST_READ_NEVER_TEXT =
  "Last successful read from this dashboard server: never — nothing has been read yet";
const LAST_READ_PREFIX = "Last successful read from this dashboard server:";
const LAST_READ_QUALIFIER =
  "local server read age only — not exchange-candle freshness and not proof the bot is trading";
const MANUAL_REFRESH_LABEL = "Refresh now";
const MANUAL_REFRESH_BUSY_LABEL = "Refreshing…";
const LOADING_TEXT = "Loading operations…";
const LOAD_FAILURE_PREFIX = "Failed to load operations view: ";
const PACK_LABEL = "Pack";
const MARKET_LABEL = "Market";
const MODE_LABEL = "Mode";
const ENTRIES_LABEL = "Entries";

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

function pauseErrorId(venue: string, pair: string): string {
  return `ops-pause-error-${venue}-${pair}`.replace(/\//g, "-");
}

function resumeErrorId(venue: string, pair: string): string {
  return `ops-resume-error-${venue}-${pair}`.replace(/\//g, "-");
}

function ackId(alertId: string): string {
  return `ops-alert-ack-${alertId}`;
}

function alertRowId(alertId: string): string {
  return `ops-alert-${alertId}`;
}

function severityGroupId(severity: string): string {
  return `ops-severity-group-${severity}`;
}

function clearRowEntry<T>(
  setter: (update: (prev: Record<string, T>) => Record<string, T>) => void,
  key: string,
): void {
  setter((prev) => {
    if (!(key in prev)) {
      return prev;
    }
    const next = { ...prev };
    delete next[key];
    return next;
  });
}

function killStateText(engaged: boolean, reason: string | null): string {
  if (!engaged) {
    return KILL_RELEASED_TEXT;
  }
  return `Kill switch: engaged — ${reason ?? "(no reason)"}`;
}

function formatReadAge(ageMs: number): string {
  const seconds = Math.floor(ageMs / 1000);
  if (seconds < 60) {
    return `${seconds}s ago`;
  }
  const minutes = Math.floor(seconds / 60);
  const rem = seconds % 60;
  return `${minutes}m ${rem}s ago`;
}

// Severity band order for the grouped alerts panel: the two known bands
// first (critical above warning, matching the server's own sort), then any
// future/unknown severity in first-appearance order so no band is dropped.
function severityBandOrder(severities: readonly string[]): string[] {
  const seen = new Set<string>();
  const ordered: string[] = [];
  for (const severity of severities) {
    if (!seen.has(severity)) {
      seen.add(severity);
      ordered.push(severity);
    }
  }
  const rank = (severity: string): number => {
    if (severity === "critical") {
      return 0;
    }
    if (severity === "warning") {
      return 1;
    }
    return 2;
  };
  return ordered
    .map((severity, index) => ({ severity, index }))
    .sort((a, b) => {
      const byBand = rank(a.severity) - rank(b.severity);
      return byBand !== 0 ? byBand : a.index - b.index;
    })
    .map((entry) => entry.severity);
}

function distinctModes(
  deployments: ReadonlyArray<OperationsViewModel["deployments"][number]>,
): string[] {
  const seen = new Set<string>();
  const modes: string[] = [];
  for (const deployment of deployments) {
    if (!seen.has(deployment.mode)) {
      seen.add(deployment.mode);
      modes.push(deployment.mode);
    }
  }
  return modes;
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
  const [promoteErrors, setPromoteErrors] = useState<Record<string, string>>({});
  const [pauseErrors, setPauseErrors] = useState<Record<string, string>>({});
  const [resumeErrors, setResumeErrors] = useState<Record<string, string>>({});
  const [ackErrors, setAckErrors] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<Set<string>>(new Set());

  const { view, fetchError, refreshing, lastSuccessAgeMs, refresh } =
    useOperationsRefresh(client);

  const handlePromote = useCallback(
    async (venue: string, pair: string): Promise<void> => {
      const key = promoteButtonId(venue, pair);
      if (pending.has(key)) {
        return;
      }
      setPending((prev) => new Set(prev).add(key));
      clearRowEntry(setPromoteResults, key);
      try {
        const result = await client.promote(venue, pair, PROMO_REVISION_ID);
        const code = typeof result.code === "string" ? result.code : "refused";
        const message = typeof result.message === "string" ? result.message : "live promotion refused";
        setPromoteResults((prev) => ({ ...prev, [key]: { code, message } }));
        clearRowEntry(setPromoteErrors, key);
      } catch (err) {
        setPromoteErrors((prev) => ({
          ...prev,
          [key]: `Promote failed: ${err instanceof Error ? err.message : String(err)}`,
        }));
      } finally {
        await refresh();
        setPending((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }
    },
    [client, refresh, pending],
  );

  const handlePause = useCallback(
    async (venue: string, pair: string): Promise<void> => {
      const key = pauseButtonId(venue, pair);
      if (pending.has(key)) {
        return;
      }
      setPending((prev) => new Set(prev).add(key));
      // A new explicit attempt supersedes the previous outcome for this row/action.
      clearRowEntry(setPauseResults, key);
      clearRowEntry(setPauseErrors, key);
      try {
        const result = await client.pauseEntries(venue, pair);
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
      } catch (err) {
        // The outcome is unknown, not refused: keep the last known view and any
        // earlier server-confirmed refusal instead of guessing server state.
        setPauseErrors((prev) => ({
          ...prev,
          [key]: `Pause entries failed: ${
            err instanceof Error ? err.message : String(err)
          } — ${UNKNOWN_OUTCOME_TEXT}`,
        }));
      } finally {
        setPending((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }
    },
    [client, refresh, pending],
  );

  const handleResume = useCallback(
    async (venue: string, pair: string): Promise<void> => {
      const key = resumeButtonId(venue, pair);
      if (pending.has(key)) {
        return;
      }
      setPending((prev) => new Set(prev).add(key));
      // A new explicit attempt supersedes the previous outcome for this row/action.
      clearRowEntry(setResumeResults, key);
      clearRowEntry(setResumeErrors, key);
      try {
        const result = await client.resumeEntries(venue, pair);
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
      } catch (err) {
        setResumeErrors((prev) => ({
          ...prev,
          [key]: `Resume entries failed: ${
            err instanceof Error ? err.message : String(err)
          } — ${UNKNOWN_OUTCOME_TEXT}`,
        }));
      } finally {
        setPending((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }
    },
    [client, refresh, pending],
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
      try {
        await client.ackAlert(alertId);
        clearRowEntry(setAckErrors, alertId);
      } catch (err) {
        setAckErrors((prev) => ({
          ...prev,
          [alertId]: `Acknowledge failed: ${
            err instanceof Error ? err.message : String(err)
          }`,
        }));
      } finally {
        await refresh();
      }
    },
    [client, refresh],
  );

  if (view === null && fetchError === null) {
    return (
      <section className="kbot-ops" data-testid="operations-view">
        <p className="kbot-ops__empty">{LOADING_TEXT}</p>
      </section>
    );
  }

  if (view === null) {
    return (
      <section className="kbot-ops" data-testid="operations-view">
        <p className="kbot-ops__empty" role="alert">
          {LOAD_FAILURE_PREFIX}
          {fetchError}
        </p>
      </section>
    );
  }

  const killEngaged = view.live.kill_switch.engaged;
  const modes = distinctModes(view.deployments);

  return (
    <section className="kbot-ops" data-testid="operations-view">
      <header className="kbot-ops__head">
        <div className="kbot-ops__head-titles">
          <h2 className="kbot-ops__title">Operations</h2>
          <p className="kbot-ops__read-age" data-testid="ops-last-read-age">
            {lastSuccessAgeMs === null
              ? LAST_READ_NEVER_TEXT
              : `${LAST_READ_PREFIX} ${formatReadAge(lastSuccessAgeMs)} (${LAST_READ_QUALIFIER})`}
          </p>
        </div>
        <button
          type="button"
          className="kbot-ops__refresh"
          data-testid="ops-refresh"
          disabled={refreshing}
          aria-busy={refreshing || undefined}
          onClick={() => {
            void refresh();
          }}
        >
          {refreshing ? MANUAL_REFRESH_BUSY_LABEL : MANUAL_REFRESH_LABEL}
        </button>
      </header>
      {fetchError !== null ? (
        <p className="kbot-ops__stale" role="alert" data-testid="ops-stale-warning">
          {STALE_PREFIX} — refresh failed: {fetchError}; {STALE_SUFFIX}.
        </p>
      ) : null}
      <div className="kbot-ops__body">
        <div className="kbot-ops__status" data-testid="ops-status-banner">
          <section
            className="kbot-ops__panel kbot-ops__panel--status"
            aria-label="Live status"
          >
            <h3 className="kbot-ops__panel-title">Live status</h3>
            {renderLiveBanner(view.live)}
          </section>

          <section
            className="kbot-ops__panel kbot-ops__panel--kill"
            aria-label="Kill switch"
            data-testid="ops-kill"
          >
            <h3 className="kbot-ops__panel-title">Kill switch</h3>
            <p className="kbot-ops__kill-state" data-testid="ops-kill-state">
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
        </div>

        <section
          className="kbot-ops__panel"
          aria-label="Deployments"
          data-testid="ops-deployments-panel"
        >
          <div className="kbot-ops__panel-head">
            <h3 className="kbot-ops__panel-title">Deployments</h3>
            <div className="kbot-ops__mode-header" data-testid="ops-mode-header">
              {modes.map((mode: string) => (
                <span key={mode} className="kbot-ops__mode-chip">
                  {summarizeOperationMode(mode).label}
                </span>
              ))}
            </div>
            <DeploymentsCsvExport deployments={view.deployments} />
          </div>
          <div className="kbot-ops__scroll" data-testid="ops-deployments-scroll">
            <ul className="kbot-ops__deployments" data-testid="ops-deployments">
              {view.deployments.length === 0 ? (
                <li className="kbot-ops__empty">{NO_DEPLOYMENTS_TEXT}</li>
              ) : (
                view.deployments.map((deployment: OperationsViewModel["deployments"][number]) => {
                  const key = `${deployment.venue}-${deployment.pair}`;
                  const promoKey = promoteButtonId(deployment.venue, deployment.pair);
                  const promoteResult = promoteResults[promoKey];
                  const pauseKey = pauseButtonId(deployment.venue, deployment.pair);
                  const pauseResult = pauseResults[pauseKey];
                  const resumeKey = resumeButtonId(deployment.venue, deployment.pair);
                  const resumeResult = resumeResults[resumeKey];
                  const pausePending = pending.has(pauseKey);
                  const resumePending = pending.has(resumeKey);
                  return (
                    <li
                      key={key}
                      className="kbot-ops__deployment"
                      data-testid={rowId(deployment.venue, deployment.pair)}
                    >
                      <div className="kbot-ops__deployment-identity">
                        <div className="kbot-ops__deployment-fact">
                          <span className="kbot-ops__fact-label">{PACK_LABEL}</span>
                          <span className="kbot-ops__deployment-pack">{deployment.pack_id}</span>
                        </div>
                        <div className="kbot-ops__deployment-fact">
                          <span className="kbot-ops__fact-label">{MARKET_LABEL}</span>
                          <span className="kbot-ops__deployment-market">
                            {deployment.venue} · {deployment.pair}
                          </span>
                        </div>
                      </div>
                      <div className="kbot-ops__deployment-facts">
                        <div className="kbot-ops__deployment-fact">
                          <span className="kbot-ops__fact-label">{MODE_LABEL}</span>
                          <span className="kbot-ops__deployment-mode">
                            {summarizeOperationMode(deployment.mode).label}
                          </span>
                        </div>
                        <div className="kbot-ops__deployment-fact">
                          <span className="kbot-ops__fact-label">{ENTRIES_LABEL}</span>
                          <span
                            className={`kbot-ops__deployment-entries${
                              deployment.entries_paused
                                ? " kbot-ops__deployment-entries--paused"
                                : ""
                            }`}
                          >
                            {deployment.entries_paused ? "paused" : "active"}
                          </span>
                        </div>
                      </div>
                      <div className="kbot-ops__row-actions">
                        <button
                          type="button"
                          data-testid={pauseButtonId(deployment.venue, deployment.pair)}
                          disabled={pausePending}
                          onClick={() => {
                            void handlePause(deployment.venue, deployment.pair);
                          }}
                        >
                          Pause entries
                        </button>
                        <button
                          type="button"
                          data-testid={resumeButtonId(deployment.venue, deployment.pair)}
                          disabled={resumePending}
                          onClick={() => {
                            void handleResume(deployment.venue, deployment.pair);
                          }}
                        >
                          Resume entries
                        </button>
                        <button
                          type="button"
                          data-testid={promoteButtonId(deployment.venue, deployment.pair)}
                          disabled={pending.has(promoKey)}
                          onClick={() => {
                            void handlePromote(deployment.venue, deployment.pair);
                          }}
                        >
                          Promote to live candidate
                        </button>
                      </div>
                      {promoteErrors[promoKey] ? (
                        <p className="kbot-ops__row-result" role="alert" data-testid="ops-promote-error">
                          {promoteErrors[promoKey]}
                        </p>
                      ) : null}
                      {promoteResult ? (
                          <p
                            className="kbot-ops__row-result"
                            role="status"
                            data-testid={promoteResultId(deployment.venue, deployment.pair)}
                          >
                            Refused: {summarizeDeploymentRefused(promoteResult.code, promoteResult.message).label} — {promoteResult.message}
                          </p>
                        ) : null}
                        {pauseResult && !pauseResult.ok ? (
                          <p
                            className="kbot-ops__row-result"
                            role="status"
                            data-testid={pauseResultId(deployment.venue, deployment.pair)}
                          >
                            Refused: {summarizeDeploymentRefused(pauseResult.code, pauseResult.message).label} — {pauseResult.message}
                          </p>
                        ) : null}
                        {pauseErrors[pauseKey] ? (
                          <p
                            className="kbot-ops__row-result"
                            role="alert"
                            data-testid={pauseErrorId(deployment.venue, deployment.pair)}
                          >
                            {pauseErrors[pauseKey]}
                          </p>
                        ) : null}
                        {resumeResult && !resumeResult.ok ? (
                          <p
                            className="kbot-ops__row-result"
                            role="status"
                            data-testid={resumeResultId(deployment.venue, deployment.pair)}
                          >
                            Refused: {summarizeDeploymentRefused(resumeResult.code, resumeResult.message).label} — {resumeResult.message}
                          </p>
                        ) : null}
                        {resumeErrors[resumeKey] ? (
                          <p
                            className="kbot-ops__row-result"
                            role="alert"
                            data-testid={resumeErrorId(deployment.venue, deployment.pair)}
                          >
                            {resumeErrors[resumeKey]}
                          </p>
                        ) : null}
                    </li>
                  );
                })
              )}
            </ul>
          </div>
        </section>

        <section
          className="kbot-ops__panel"
          aria-label="Deployment history"
          data-testid="ops-deployment-history"
        >
          <div className="kbot-ops__scroll" data-testid="ops-history-scroll">
            <DeploymentHistory client={client} />
          </div>
        </section>

        <section
          className="kbot-ops__panel"
          aria-label="Alerts"
          data-testid="ops-alerts-panel"
        >
          <h3 className="kbot-ops__panel-title">Alerts</h3>
          <AlertsFilter alerts={view.alerts}>
            {(visible: OperationsViewModel["alerts"]) => (
              <div className="kbot-ops__alert-groups" data-testid="ops-alert-groups">
                <ul className="kbot-ops__alerts" data-testid="ops-alerts">
                {view.alerts.length === 0 ? (
                  <li className="kbot-ops__empty">{NO_ALERTS_TEXT}</li>
                ) : (
                  severityBandOrder(visible.map((alert: AlertRow) => alert.severity)).map(
                    (severity: string) => {
                      const rows = visible.filter(
                        (alert: AlertRow) => alert.severity === severity,
                      );
                      return (
                        <li key={severity} className="kbot-ops__alert-group">
                          <div
                            className="kbot-ops__alert-group-head"
                            data-testid={severityGroupId(severity)}
                          >
                            <span className="kbot-ops__alert-group-title">
                              {summarizeAlertSeverity(severity).label}
                            </span>
                            <span className="kbot-ops__alert-group-count">
                              {rows.length === 1 ? "1 alert" : `${rows.length} alerts`}
                            </span>
                          </div>
                          <ul className="kbot-ops__alert-group-rows">
                            {rows.map((alert: OperationsViewModel["alerts"][number]) => (
                              <li
                                key={alert.id}
                                className={`kbot-ops__alert kbot-ops__alert--${alert.severity}`}
                                data-testid={alertRowId(alert.id)}
                              >
                                <div className="kbot-ops__alert-line">
                                  <span className="kbot-ops__alert-kind">
                                    {summarizeAlertKind(alert.kind).label}
                                  </span>
                                  <span className="kbot-ops__alert-severity">
                                    {summarizeAlertSeverity(alert.severity).label}
                                  </span>
                                  <span className="kbot-ops__alert-code">
                                    {summarizeAlertCode(alert.code).label}
                                  </span>
                                </div>
                                <div className="kbot-ops__alert-meta">
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
                                </div>
                                {ackErrors[alert.id] ? (
                                  <p
                                    className="kbot-ops__row-result"
                                    data-testid="ops-alert-ack-error"
                                    role="alert"
                                  >
                                    {ackErrors[alert.id]}
                                  </p>
                                ) : null}
                              </li>
                            ))}
                          </ul>
                        </li>
                      );
                    },
                  )
                )}
                </ul>
              </div>
            )}
          </AlertsFilter>
          <AlertsCsvExport alerts={view.alerts} />
        </section>

        <AcknowledgedAlertsList client={client} />
      </div>
    </section>
  );
}