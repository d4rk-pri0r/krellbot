import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import "./JournalBrowsePanel.signal.css";
import type { JournalBrowseQuery, JournalRecordRow, OperationsClient } from "./client";

const PANEL_TITLE = "Journal";
const LOCAL_PREVIEW_BADGE = "Local preview";
const HELPER_TEXT =
  "Browse journal events (tail or since 24h/14d). Filter paper vs live when live rows exist. Read-only evidence — local preview only.";
const LOADING_TEXT = "Loading journal…";
const EMPTY_TEXT = "No journal records for this filter.";
const LIST_ERROR_PREFIX = "Could not load journal — check the workstation is running.";
const RETRY_TEXT = "Retry";
const REFRESH_LABEL = "Refresh";
const REFRESH_BUSY_LABEL = "Refreshing…";
const FILTER_LABEL = "Show";
const MODE_LABEL = "Mode";
const COL_TS = "Time (UTC)";
const COL_MODE = "Mode";
const COL_KIND = "Kind";
const COL_VENUE = "Venue";
const COL_PACK = "Pack";
const COL_DETAIL = "Detail";

type FilterMode = "tail-5" | "tail-20" | "tail-50" | "since-24h" | "since-14d";
type ExecutionModeFilter = "all" | "paper" | "live";

const FILTER_OPTIONS: ReadonlyArray<{ value: FilterMode; label: string }> = [
  { value: "tail-5", label: "Last 5" },
  { value: "tail-20", label: "Last 20" },
  { value: "tail-50", label: "Last 50" },
  { value: "since-24h", label: "Last 24 hours" },
  { value: "since-14d", label: "Last 14 days" },
];

const MODE_OPTIONS: ReadonlyArray<{ value: ExecutionModeFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "paper", label: "Paper" },
  { value: "live", label: "Live" },
];

export type JournalBrowsePanelProps = {
  client: OperationsClient;
};

function queryForFilters(filter: FilterMode, mode: ExecutionModeFilter): JournalBrowseQuery {
  const base: JournalBrowseQuery = (() => {
    switch (filter) {
      case "tail-20":
        return { tail: 20 };
      case "tail-50":
        return { tail: 50 };
      case "since-24h":
        return { since: "24h" };
      case "since-14d":
        return { since: "14d" };
      case "tail-5":
      default:
        return { tail: 5 };
    }
  })();
  if (mode === "paper" || mode === "live") {
    return { ...base, mode };
  }
  return base;
}

function formatTs(ts: number): string {
  if (!Number.isFinite(ts)) {
    return "—";
  }
  const date = new Date(ts * 1000);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return date.toISOString().replace("T", " ").slice(0, 19);
}

function formatReadableDetail(detail: unknown): string {
  if (detail === null || detail === undefined) {
    return "—";
  }
  if (typeof detail === "string") {
    return detail;
  }
  if (typeof detail !== "object" || Array.isArray(detail)) {
    try {
      return JSON.stringify(detail);
    } catch {
      return String(detail);
    }
  }
  const d = detail as Record<string, unknown>;
  const reason = typeof d.reason === "string" ? d.reason : "";
  const pair = typeof d.pair === "string" ? d.pair : "";
  const code = typeof d.code === "string" ? d.code : "";
  const entryQty = String(d.entry_qty ?? "0");
  const exitQty = String(d.exit_qty ?? "0");
  const stopQty = String(d.stop_qty ?? "0");

  if (reason === "live_refused") {
    return `live refused: ${code || "refused"}${pair ? ` (${pair})` : ""}`;
  }
  if (reason === "live_fenced") {
    return `live fenced: ${code || "fenced"}${pair ? ` (${pair})` : ""}`;
  }
  if (reason === "store_refused") {
    return `refused: ${code || "store_refused"}${pair ? ` (${pair})` : ""}`;
  }
  if (d.intent_refused) {
    return `refused: ${String(d.intent_refused)}${pair ? ` (${pair})` : ""}`;
  }
  if (reason === "entry" && entryQty !== "0" && entryQty !== "0.0") {
    return `bought ${entryQty}, protective stop resting${pair ? ` (${pair})` : ""}`;
  }
  if (reason === "exit" && exitQty !== "0" && exitQty !== "0.0") {
    return `sold ${exitQty}${pair ? ` (${pair})` : ""}`;
  }
  if (stopQty !== "0" && stopQty !== "0.0") {
    return `stop filled, sold ${stopQty}${pair ? ` (${pair})` : ""}`;
  }
  if (reason) {
    return pair ? `${reason} (${pair})` : reason;
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

function formatDetail(row: JournalRecordRow): string {
  if (typeof row.summary === "string" && row.summary.trim()) {
    return row.summary;
  }
  return formatReadableDetail(row.detail);
}

function modeLabel(row: JournalRecordRow): string {
  if (row.mode === "live" || row.mode === "paper") {
    return row.mode;
  }
  if (row.detail && typeof row.detail === "object" && !Array.isArray(row.detail)) {
    const d = row.detail as Record<string, unknown>;
    if (d.mode === "live" || d.mode === "paper") {
      return String(d.mode);
    }
    if (d.reason === "live_refused" || d.reason === "live_fenced") {
      return "live";
    }
  }
  return "paper";
}

function rowKey(row: JournalRecordRow, index: number): string {
  return `${row.ts}-${row.kind}-${row.venue}-${row.pack}-${index}`;
}

export function JournalBrowsePanel({ client }: JournalBrowsePanelProps): JSX.Element {
  const [filter, setFilter] = useState<FilterMode>("tail-5");
  const [modeFilter, setModeFilter] = useState<ExecutionModeFilter>("all");
  const [rows, setRows] = useState<JournalRecordRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef(0);

  const load = useCallback(
    async (nextFilter: FilterMode, nextMode: ExecutionModeFilter): Promise<void> => {
      if (typeof client.listJournal !== "function") {
        setRows([]);
        setError(null);
        setLoading(false);
        return;
      }
      const requestId = ++requestRef.current;
      setLoading(true);
      setError(null);
      try {
        const next = await client.listJournal(queryForFilters(nextFilter, nextMode));
        if (requestId !== requestRef.current) {
          return;
        }
        setRows(next);
      } catch (err) {
        if (requestId !== requestRef.current) {
          return;
        }
        setError(err instanceof Error ? err.message : String(err));
        setRows((prev) => prev ?? []);
      } finally {
        if (requestId === requestRef.current) {
          setLoading(false);
        }
      }
    },
    [client],
  );

  useEffect(() => {
    void load(filter, modeFilter);
  }, [load, filter, modeFilter]);

  const showEmpty = !loading && error === null && rows !== null && rows.length === 0;
  const showRows = rows !== null && rows.length > 0;

  return (
    <div className="kbot-ops__journal" data-testid="ops-journal-browse">
      <div className="kbot-ops__journal-head">
        <h3 className="kbot-ops__panel-title">{PANEL_TITLE}</h3>
        <p className="kbot-ops__preview-badge">{LOCAL_PREVIEW_BADGE}</p>
        <button
          type="button"
          className="kbot-ops__journal-refresh"
          data-testid="ops-journal-refresh"
          disabled={loading}
          aria-busy={loading || undefined}
          onClick={() => {
            void load(filter, modeFilter);
          }}
        >
          {loading ? REFRESH_BUSY_LABEL : REFRESH_LABEL}
        </button>
      </div>
      <p className="kbot-ops__journal-helper">{HELPER_TEXT}</p>
      <div className="kbot-ops__journal-filters">
        <label className="kbot-ops__journal-filter-label" htmlFor="ops-journal-filter">
          {FILTER_LABEL}
        </label>
        <select
          id="ops-journal-filter"
          className="kbot-ops__journal-filter"
          data-testid="ops-journal-filter"
          value={filter}
          disabled={loading && rows === null}
          onChange={(event) => {
            setFilter(event.target.value as FilterMode);
          }}
        >
          {FILTER_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <label className="kbot-ops__journal-filter-label" htmlFor="ops-journal-mode">
          {MODE_LABEL}
        </label>
        <select
          id="ops-journal-mode"
          className="kbot-ops__journal-filter"
          data-testid="ops-journal-mode"
          value={modeFilter}
          disabled={loading && rows === null}
          onChange={(event) => {
            setModeFilter(event.target.value as ExecutionModeFilter);
          }}
        >
          {MODE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      {loading && rows === null ? (
        <p className="kbot-ops__empty" data-testid="ops-journal-loading">
          {LOADING_TEXT}
        </p>
      ) : null}
      {error !== null ? (
        <p className="kbot-ops__row-result" role="alert" data-testid="ops-journal-error">
          {LIST_ERROR_PREFIX} {error}{" "}
          <button
            type="button"
            data-testid="ops-journal-retry"
            onClick={() => {
              void load(filter, modeFilter);
            }}
          >
            {RETRY_TEXT}
          </button>
        </p>
      ) : null}
      {showEmpty ? (
        <p className="kbot-ops__empty" data-testid="ops-journal-empty">
          {EMPTY_TEXT}
        </p>
      ) : null}
      {showRows ? (
        <div className="kbot-ops__journal-scroll" data-testid="ops-journal-scroll">
          <table className="kbot-ops__journal-table">
            <thead>
              <tr>
                <th scope="col">{COL_TS}</th>
                <th scope="col">{COL_MODE}</th>
                <th scope="col">{COL_KIND}</th>
                <th scope="col">{COL_VENUE}</th>
                <th scope="col">{COL_PACK}</th>
                <th scope="col">{COL_DETAIL}</th>
              </tr>
            </thead>
            <tbody>
              {[...rows!].reverse().map((row, index) => (
                <tr key={rowKey(row, index)} data-testid={`ops-journal-row-${index}`}>
                  <td className="kbot-ops__journal-ts">{formatTs(row.ts)}</td>
                  <td className="kbot-ops__journal-mode" data-testid={`ops-journal-mode-cell-${index}`}>
                    {modeLabel(row)}
                  </td>
                  <td className="kbot-ops__journal-kind">{row.kind}</td>
                  <td className="kbot-ops__journal-venue">{row.venue}</td>
                  <td className="kbot-ops__journal-pack">{row.pack || "—"}</td>
                  <td className="kbot-ops__journal-detail">{formatDetail(row)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
