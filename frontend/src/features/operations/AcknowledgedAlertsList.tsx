import { useCallback, useEffect, useState, type JSX } from "react";
import type { AlertRow } from "./client";
import { createAcknowledgedAlertsHttpClient } from "./acknowledgedAlertsClient";
import { severityOptions } from "./AlertsFilter";

export const NO_ACKNOWLEDGED_ALERTS_TEXT = "No acknowledged alerts.";
export const ACKNOWLEDGED_LOADING_TEXT = "Loading…";
export const ACKNOWLEDGED_FAILED_TEXT = "Failed to load acknowledged alerts.";

type ListSource = {
  listAcknowledged(): Promise<ReadonlyArray<AlertRow>>;
};

type ClientWithOptionalList = {
  listAcknowledged?(): Promise<ReadonlyArray<AlertRow>>;
};

function resolveListSource(client: unknown): ListSource {
  if (
    client &&
    typeof client === "object" &&
    typeof (client as ClientWithOptionalList).listAcknowledged === "function"
  ) {
    return client as ListSource;
  }
  return createAcknowledgedAlertsHttpClient();
}

function rowTestId(id: string): string {
  return `ops-acknowledged-alert-${id}`;
}

function severityTestId(id: string): string {
  return `ops-ack-severity-${id}`;
}

function detailTestId(id: string): string {
  return `ops-ack-detail-${id}`;
}

function formatTs(ts: number): string {
  return new Date(ts * 1000).toISOString().replace("T", " ").slice(0, 19);
}

// Same sentinel value AlertsFilter.severityOptions() hardcodes as its first option.
const ALL_SEVERITIES = "all";
const ACK_FILTERED_EMPTY_TEXT = "No acknowledged alerts match the current filters.";
const ACK_CLEAR_TEXT = "Clear filters";
const ACK_ALL_SEVERITIES_LABEL = "All severities";

export type AcknowledgedAlertsListProps = {
  client: unknown;
};

export function AcknowledgedAlertsList({ client }: AcknowledgedAlertsListProps): JSX.Element {
  const [rows, setRows] = useState<ReadonlyArray<AlertRow> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [severity, setSeverity] = useState<string>(ALL_SEVERITIES);
  const [query, setQuery] = useState<string>("");

  const list = resolveListSource(client);

  const refresh = useCallback(async (): Promise<void> => {
    try {
      const next = await list.listAcknowledged();
      // Defensive: the acknowledged-alerts client already filters server-side rows,
      // but a stub or future caller may hand back the full list.
      setRows(next.filter((alert) => alert.acknowledged === true));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [list]);

  useEffect(() => {
    void refresh();
  }, [refresh, nonce]);

  const visibleRows = rows === null ? null : rows.filter((alert) => {
    if (severity !== ALL_SEVERITIES && alert.severity !== severity) return false;
    const needle = query.trim().toLowerCase();
    if (needle === "") return true;
    return [alert.id, alert.kind, alert.code ?? "", alert.venue ?? "", alert.pair ?? ""].some(
      (field) => String(field).toLowerCase().includes(needle),
    );
  });
  const isEmpty = rows !== null && visibleRows !== null && rows.length > 0 && visibleRows.length === 0;
  const filtersActive = severity !== ALL_SEVERITIES || query !== "";

  return (
    <section
      className="kbot-ops__panel"
      data-testid="ops-acknowledged-alerts"
      aria-label="Acknowledged alerts"
    >
      <div className="kbot-ops__panel-head">
        <h3 className="kbot-ops__panel-title">Acknowledged alerts</h3>
        <button
          type="button"
          data-testid="ops-acknowledged-refresh"
          onClick={() => {
            setNonce((n) => n + 1);
          }}
        >
          Refresh
        </button>
        <label
          className="kbot-ops__panel-head-filter"
          id="ops-acknowledged-filter-severity-label"
          htmlFor="ops-acknowledged-filter-severity-input"
        >
          Severity
          <select
            id="ops-acknowledged-filter-severity-input"
            aria-label="Filter acknowledged alerts by severity"
            aria-describedby={isEmpty ? "ops-acknowledged-empty" : undefined}
            data-testid="ops-acknowledged-filter-severity"
            value={severity}
            onChange={(event) => setSeverity(event.target.value)}
          >
            {severityOptions(rows ?? []).map((option) => (
              <option key={option} value={option}>
                {option === ALL_SEVERITIES ? ACK_ALL_SEVERITIES_LABEL : option}
              </option>
            ))}
          </select>
        </label>
        <label
          className="kbot-ops__panel-head-filter"
          id="ops-acknowledged-filter-query-label"
          htmlFor="ops-acknowledged-filter-query-input"
        >
          Search
          <input
            id="ops-acknowledged-filter-query-input"
            aria-label="Search acknowledged alerts by id, kind, code, venue or pair"
            aria-describedby={isEmpty ? "ops-acknowledged-empty" : undefined}
            data-testid="ops-acknowledged-filter-query"
            type="text"
            value={query}
            placeholder="Filter by id, kind, code, venue or pair"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        {filtersActive ? (
          <button
            type="button"
            data-testid="ops-acknowledged-filter-clear"
            onClick={() => {
              setSeverity(ALL_SEVERITIES);
              setQuery("");
            }}
          >
            {ACK_CLEAR_TEXT}
          </button>
        ) : null}
      </div>
      {error !== null ? (
        <p className="kbot-ops__empty" role="alert">
          {ACKNOWLEDGED_FAILED_TEXT} {error}
        </p>
      ) : rows === null ? (
        <p className="kbot-ops__empty">{ACKNOWLEDGED_LOADING_TEXT}</p>
      ) : rows.length === 0 ? (
        <p className="kbot-ops__empty">{NO_ACKNOWLEDGED_ALERTS_TEXT}</p>
      ) : (
        <table className="kbot-ops__table" data-testid="ops-acknowledged-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Kind</th>
              <th>Code</th>
              <th>Venue</th>
              <th>Pair</th>
              <th>Count</th>
              <th>First ts</th>
              <th>Last ts</th>
              <th>Severity</th>
            </tr>
          </thead>
          <tbody>
            {(visibleRows ?? []).map((alert: AlertRow) => (
              <tr
                key={alert.id}
                data-testid={rowTestId(alert.id)}
                onClick={() => {
                  setOpenId((prev) => (prev === alert.id ? null : alert.id));
                }}
              >
                <td>{alert.id}</td>
                <td>{alert.kind}</td>
                <td>{alert.code ?? "-"}</td>
                <td>{alert.venue ?? "-"}</td>
                <td>{alert.pair ?? "-"}</td>
                <td>×{alert.count}</td>
                <td>{formatTs(alert.first_ts)}</td>
                <td>{formatTs(alert.last_ts)}</td>
                <td>
                  <span
                    className={`kbot-ops__alert-severity kbot-ops__alert--${alert.severity}`}
                    data-testid={severityTestId(alert.id)}
                  >
                    {alert.severity}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {isEmpty ? (
        <p className="kbot-ops__alerts-empty" data-testid="ops-acknowledged-empty">
          {ACK_FILTERED_EMPTY_TEXT}
        </p>
      ) : null}
      {error === null && rows !== null && openId !== null
        ? rows
            .filter((alert) => alert.id === openId)
            .map((alert) => (
              <p
                key={alert.id}
                className="kbot-ops__row-result"
                data-testid={detailTestId(alert.id)}
              >
                {alert.kind} — code: {alert.code ?? "-"} message: - (no message field on this
                alert)
              </p>
            ))
        : null}
    </section>
  );
}
