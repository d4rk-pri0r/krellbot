import { useState, type ReactNode } from "react";
import type { AlertRow } from "./client";
import { summarizeAlertKind } from "./alertKindLabel";

const ALL_SEVERITIES = "all";
const ALL_KINDS = "all";
const ALL_SEVERITY_LABEL = "All severities";
const ALL_KIND_LABEL = "All kinds";
const CLEAR_TEXT = "Clear filters";
const EMPTY_TEXT = "No alerts match the current filters.";

export type AlertsFilterProps = {
  alerts: readonly AlertRow[];
  children: (visible: AlertRow[], isEmpty: boolean) => ReactNode;
};

export function severityOptions(alerts: readonly AlertRow[]): string[] {
  return [ALL_SEVERITIES, ...Array.from(new Set(alerts.map((a) => a.severity)))];
}

export function kindOptions(alerts: readonly AlertRow[]): string[] {
  return [ALL_KINDS, ...Array.from(new Set(alerts.map((a) => a.kind)))];
}

/** Unacknowledged alerts — the honest unread count for Operations. */
export function unreadAlertCount(alerts: readonly AlertRow[]): number {
  return alerts.reduce(
    (count, alert) => count + (alert.acknowledged === true ? 0 : 1),
    0,
  );
}

export function unreadAlertLabel(count: number): string {
  return count === 1 ? "1 unread" : `${count} unread`;
}

export function AlertsFilter({ alerts, children }: AlertsFilterProps) {
  const [severity, setSeverity] = useState<string>(ALL_SEVERITIES);
  const [kind, setKind] = useState<string>(ALL_KINDS);
  const [query, setQuery] = useState("");

  // Keep an explicitly selected severity/kind represented even after a
  // refresh drops the last row of that value, so the select always
  // describes the filter actually applied.
  const severities = severityOptions(alerts);
  if (severity !== ALL_SEVERITIES && !severities.includes(severity)) {
    severities.push(severity);
  }
  const kinds = kindOptions(alerts);
  if (kind !== ALL_KINDS && !kinds.includes(kind)) {
    kinds.push(kind);
  }

  const needle = query.trim().toLowerCase();
  const visible = alerts.filter((alert) => {
    if (severity !== ALL_SEVERITIES && alert.severity !== severity) {
      return false;
    }
    if (kind !== ALL_KINDS && alert.kind !== kind) {
      return false;
    }
    if (needle === "") {
      return true;
    }
    const code = (alert.code ?? "").toLowerCase();
    const venue = (alert.venue ?? "").toLowerCase();
    const kindNeedle = alert.kind.toLowerCase();
    return (
      code.includes(needle) ||
      venue.includes(needle) ||
      kindNeedle.includes(needle)
    );
  });
  const isEmpty = alerts.length > 0 && visible.length === 0;
  const filtersActive =
    severity !== ALL_SEVERITIES || kind !== ALL_KINDS || query !== "";
  const unread = unreadAlertCount(alerts);

  return (
    <div className="kbot-ops__alerts-filter" data-testid="ops-alerts-filter">
      <p
        className="kbot-ops__alerts-unread"
        data-testid="ops-alerts-unread-count"
        aria-live="polite"
      >
        {unreadAlertLabel(unread)}
      </p>
      <label id="ops-alerts-filter-severity-label" htmlFor="ops-alerts-filter-severity-input">
        Severity
        <select
          id="ops-alerts-filter-severity-input"
          aria-label="Filter alerts by severity"
          aria-describedby={isEmpty ? "ops-alerts-empty-id" : undefined}
          data-testid="ops-alerts-filter-severity"
          value={severity}
          onChange={(event) => setSeverity(event.target.value)}
        >
          {severities.map((option) => (
            <option key={option} value={option}>
              {option === ALL_SEVERITIES ? ALL_SEVERITY_LABEL : option}
            </option>
          ))}
        </select>
      </label>
      <label id="ops-alerts-filter-kind-label" htmlFor="ops-alerts-filter-kind-input">
        Kind
        <select
          id="ops-alerts-filter-kind-input"
          aria-label="Filter alerts by kind"
          aria-describedby={isEmpty ? "ops-alerts-empty-id" : undefined}
          data-testid="ops-alerts-filter-kind"
          value={kind}
          onChange={(event) => setKind(event.target.value)}
        >
          {kinds.map((option) => (
            <option key={option} value={option}>
              {option === ALL_KINDS
                ? ALL_KIND_LABEL
                : summarizeAlertKind(option).label}
            </option>
          ))}
        </select>
      </label>
      <label id="ops-alerts-filter-query-label" htmlFor="ops-alerts-filter-query-input">
        Search
        <input
          id="ops-alerts-filter-query-input"
          aria-label="Search alerts by code, venue, or kind"
          aria-describedby={isEmpty ? "ops-alerts-empty-id" : undefined}
          data-testid="ops-alerts-filter-query"
          type="text"
          value={query}
          placeholder="Filter by code, venue, or kind"
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      {filtersActive ? (
        <button
          type="button"
          data-testid="ops-alerts-filter-clear"
          onClick={() => {
            setSeverity(ALL_SEVERITIES);
            setKind(ALL_KINDS);
            setQuery("");
          }}
        >
          {CLEAR_TEXT}
        </button>
      ) : null}
      {isEmpty ? (
        <p id="ops-alerts-empty-id" className="kbot-ops__alerts-empty" data-testid="ops-alerts-empty">
          {EMPTY_TEXT}
        </p>
      ) : null}
      {children(visible, isEmpty)}
    </div>
  );
}
