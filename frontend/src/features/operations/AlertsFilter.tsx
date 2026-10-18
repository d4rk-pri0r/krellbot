import { useState, type ReactNode } from "react";
import type { AlertRow } from "./client";

const ALL_SEVERITIES = "all";
const ALL_LABEL = "All severities";
const CLEAR_TEXT = "Clear filters";
const EMPTY_TEXT = "No alerts match the current filters.";

export type AlertsFilterProps = {
  alerts: readonly AlertRow[];
  children: (visible: AlertRow[], isEmpty: boolean) => ReactNode;
};

export function severityOptions(alerts: readonly AlertRow[]): string[] {
  return [ALL_SEVERITIES, ...Array.from(new Set(alerts.map((a) => a.severity)))];
}

export function AlertsFilter({ alerts, children }: AlertsFilterProps) {
  const [severity, setSeverity] = useState<string>(ALL_SEVERITIES);
  const [query, setQuery] = useState("");

  const needle = query.trim().toLowerCase();
  const visible = alerts.filter((alert) => {
    if (severity !== ALL_SEVERITIES && alert.severity !== severity) {
      return false;
    }
    if (needle === "") {
      return true;
    }
    const code = (alert.code ?? "").toLowerCase();
    const venue = (alert.venue ?? "").toLowerCase();
    return code.includes(needle) || venue.includes(needle);
  });
  const isEmpty = alerts.length > 0 && visible.length === 0;
  const filtersActive = severity !== ALL_SEVERITIES || query !== "";

  return (
    <div className="kbot-ops__alerts-filter" data-testid="ops-alerts-filter">
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
          {severityOptions(alerts).map((option) => (
            <option key={option} value={option}>
              {option === ALL_SEVERITIES ? ALL_LABEL : option}
            </option>
          ))}
        </select>
      </label>
      <label id="ops-alerts-filter-query-label" htmlFor="ops-alerts-filter-query-input">
        Search
        <input
          id="ops-alerts-filter-query-input"
          aria-label="Search alerts by code or venue"
          aria-describedby={isEmpty ? "ops-alerts-empty-id" : undefined}
          data-testid="ops-alerts-filter-query"
          type="text"
          value={query}
          placeholder="Filter by code or venue"
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      {filtersActive ? (
        <button
          type="button"
          data-testid="ops-alerts-filter-clear"
          onClick={() => {
            setSeverity(ALL_SEVERITIES);
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
