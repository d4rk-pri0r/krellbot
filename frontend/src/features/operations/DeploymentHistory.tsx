import { Fragment, useCallback, useEffect, useRef, useState, type JSX } from "react";
import "./DeploymentHistory.signal.css";
import type { DeploymentRecordRow, OperationsClient } from "./client";

const HISTORY_REFRESHING_LABEL = "Refreshing history…";
const HISTORY_REFRESH_COMPLETE_LABEL = "Refresh complete";
const LOADING_TEXT = "Loading deployments…";
const DETAIL_LOADING_TEXT = "Loading deployment…";
const EMPTY_TEXT = "No deployments yet. Local preview only — live trading unavailable.";
const LIST_ERROR_PREFIX = "Could not load deployments — check the workstation is running.";
const DETAIL_ERROR_PREFIX = "Could not load deployment — check the workstation is running.";
const RETRY_TEXT = "Retry";
const LOCAL_PREVIEW_BADGE = "Local preview";
const CLIENT_UNAVAILABLE = "history client is unavailable in this build";
const READ_ONLY_HELPER =
  "Read-only: historical records can be inspected but not edited, started, or promoted.";

export type DeploymentHistoryProps = {
  client: OperationsClient;
};

function rowTestId(deploymentId: string): string {
  return `ops-history-row-${deploymentId}`;
}

function detailTestId(deploymentId: string): string {
  return `ops-history-detail-${deploymentId}`;
}

function formatTs(createdAtMs: number): string {
  return new Date(createdAtMs).toISOString().replace("T", " ").slice(0, 19);
}

function subsetEntries(
  subset: Readonly<Record<string, string | number | boolean>>,
): Array<[string, string]> {
  return Object.entries(subset).map(([key, value]) => [key, String(value)]);
}

function renderDetailPanel(
  detail: DeploymentRecordRow,
  pending: boolean,
  error: string | null,
): JSX.Element {
  const configEntries = subsetEntries(detail.config);
  const scheduleEntries = subsetEntries(detail.schedule);
  return (
    <div className="kbot-ops__history-detail" data-testid={detailTestId(detail.deployment_id)}>
      {pending ? (
        <p className="kbot-ops__empty" data-testid="ops-history-detail-loading">
          {DETAIL_LOADING_TEXT}
        </p>
      ) : null}
      {error ? (
        <p className="kbot-ops__row-result" role="alert" data-testid="ops-history-detail-error">
          {DETAIL_ERROR_PREFIX} {error}
        </p>
      ) : null}
      {!pending && !error ? (
        <>
          <dl className="kbot-ops__history-facts">
            <dt>Config</dt>
            <dd data-testid="ops-history-detail-config">
              {configEntries.length === 0
                ? "—"
                : configEntries.map(([key, value]) => `${key}: ${value}`).join(" · ")}
            </dd>
            <dt>Schedule</dt>
            <dd data-testid="ops-history-detail-schedule">
              {scheduleEntries.length === 0
                ? "—"
                : scheduleEntries.map(([key, value]) => `${key}: ${value}`).join(" · ")}
            </dd>
            <dt>Last execution</dt>
            <dd data-testid="ops-history-detail-summary">
              {detail.last_execution_summary === "" ? "—" : detail.last_execution_summary}
            </dd>
          </dl>
        </>
      ) : null}
    </div>
  );
}

export function DeploymentHistory({ client }: DeploymentHistoryProps): JSX.Element {
  const [rows, setRows] = useState<DeploymentRecordRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DeploymentRecordRow | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const previousLoading = useRef(true);
  const [hasRefreshed, setHasRefreshed] = useState(false);

  useEffect(() => {
    if (loading && !previousLoading.current) setHasRefreshed(true);
    previousLoading.current = loading;
  }, [loading]);

  const loadRows = useCallback(async (): Promise<void> => {
    const fetchRows = client.listDeploymentRecords;
    if (!fetchRows) {
      setLoading(false);
      setRows([]);
      setError(CLIENT_UNAVAILABLE);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const next = await fetchRows.call(client);
      setRows(next);
    } catch (failure) {
      setRows([]);
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setLoading(false);
    }
  }, [client]);

  useEffect(() => {
    void loadRows();
  }, [loadRows]);

  const handleRowClick = useCallback(
    (row: DeploymentRecordRow): void => {
      if (expandedId === row.deployment_id) {
        setExpandedId(null);
        setDetail(null);
        setDetailError(null);
        setDetailLoading(false);
        return;
      }
      setExpandedId(row.deployment_id);
      setDetail(null);
      setDetailError(null);
      const fetchDetail = client.getDeploymentRecord;
      if (!fetchDetail) {
        setDetailError(CLIENT_UNAVAILABLE);
        return;
      }
      setDetailLoading(true);
      void fetchDetail
        .call(client, row.deployment_id)
        .then((record) => {
          setDetail(record);
        })
        .catch((failure: unknown) => {
          setDetail(null);
          setDetailError(failure instanceof Error ? failure.message : String(failure));
        })
        .finally(() => {
          setDetailLoading(false);
        });
    },
    [client, expandedId],
  );

  return (
    <div className="kbot-ops__history">
      <div className="kbot-ops__history-head">
        <h3 className="kbot-ops__panel-title">Deployment history</h3>
        <p className="kbot-ops__preview-badge" data-testid="ops-history-preview-badge">
          {LOCAL_PREVIEW_BADGE}
        </p>
      </div>
      <div className="kbot-ops__history-toolbar">
        <button
          type="button"
          data-testid="ops-history-refresh"
          disabled={loading}
          aria-busy={loading || undefined}
          aria-keyshortcuts="Enter Space"
          onClick={() => {
            setExpandedId(null);
            setDetail(null);
            setDetailError(null);
            void loadRows();
          }}
        >
          {loading ? HISTORY_REFRESHING_LABEL : "Refresh"}
        </button>
        {loading || hasRefreshed ? (
          <p aria-live="polite" data-testid="ops-history-refresh-status">
            {loading ? HISTORY_REFRESHING_LABEL : HISTORY_REFRESH_COMPLETE_LABEL}
          </p>
        ) : null}
      </div>
      {loading ? (
        <p className="kbot-ops__empty" data-testid="ops-history-loading">
          {LOADING_TEXT}
        </p>
      ) : null}
      {!loading && error ? (
        <p className="kbot-ops__row-result" role="alert" data-testid="ops-history-error">
          {LIST_ERROR_PREFIX} {error}{" "}
          <button
            type="button"
            className="kbot-ops__retry"
            data-testid="ops-history-retry"
            onClick={() => {
              setExpandedId(null);
              setDetail(null);
              setDetailError(null);
              void loadRows();
            }}
          >
            {RETRY_TEXT}
          </button>
        </p>
      ) : null}
      {!loading && !error ? (
        <table className="kbot-ops__table" data-testid="ops-history-table">
          <thead>
            <tr>
              <th>Deployment</th>
              <th>Venue</th>
              <th>Pair</th>
              <th>Created</th>
              <th>State</th>
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).length === 0 ? (
              <tr>
                <td colSpan={5} className="kbot-ops__empty" data-testid="ops-history-empty">
                  {EMPTY_TEXT}
                </td>
              </tr>
            ) : (
              (rows ?? []).map((row: DeploymentRecordRow) => (
                <Fragment key={row.deployment_id}>
                  <tr
                    data-testid={rowTestId(row.deployment_id)}
                    onClick={() => handleRowClick(row)}
                    aria-expanded={expandedId === row.deployment_id}
                  >
                    <td>{row.deployment_id}</td>
                    <td>{row.venue}</td>
                    <td>{row.pair}</td>
                    <td>{formatTs(row.created_at_ms)}</td>
                    <td>{row.state}</td>
                  </tr>
                  {expandedId === row.deployment_id
                    ? renderDetailPanel(
                        detail ?? {
                          deployment_id: row.deployment_id,
                          venue: row.venue,
                          pair: row.pair,
                          created_at_ms: row.created_at_ms,
                          state: row.state,
                          config: {},
                          schedule: {},
                          last_execution_summary: "",
                        },
                        detailLoading,
                        detailError,
                      )
                    : null}
                </Fragment>
              ))
            )}
          </tbody>
        </table>
      ) : null}
      <p className="kbot-ops__kill-helper">{READ_ONLY_HELPER}</p>
    </div>
  );
}
