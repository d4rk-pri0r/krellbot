import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import "./ForwardPaperLedgerPanel.signal.css";
import type {
  ForwardPaperLedgerClient,
  ForwardPaperLedgerEvent,
} from "./client";

const PANEL_TITLE = "Forward paper ledger";
const LOCAL_PREVIEW_BADGE = "Local preview";
const HELPER_TEXT =
  "Chronological paper evidence (arms, ticks, fills, refusals) for outsider reproduction. Not live P&L.";
const LOADING_TEXT = "Loading paper ledger…";
const EMPTY_TEXT = "No paper ledger events yet.";
const LIST_ERROR_PREFIX =
  "Could not load paper ledger — check the workstation is running.";
const RETRY_TEXT = "Retry";
const REFRESH_LABEL = "Refresh";
const REFRESH_BUSY_LABEL = "Refreshing…";
const COL_TS = "Time (UTC)";
const COL_KIND = "Kind";
const COL_VENUE = "Venue";
const COL_PACK = "Pack";
const COL_PAIR = "Pair";
const COL_DETAIL = "Detail";

export type ForwardPaperLedgerPanelProps = {
  client: ForwardPaperLedgerClient;
};

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

function formatDetail(detail: unknown): string {
  if (detail === null || detail === undefined) {
    return "—";
  }
  if (typeof detail === "string") {
    return detail;
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

function rowKey(row: ForwardPaperLedgerEvent, index: number): string {
  return `${row.ts}-${row.kind}-${row.venue}-${row.pack}-${row.pair ?? ""}-${index}`;
}

export function ForwardPaperLedgerPanel({
  client,
}: ForwardPaperLedgerPanelProps): JSX.Element {
  const [rows, setRows] = useState<ForwardPaperLedgerEvent[] | null>(null);
  const [disclaimer, setDisclaimer] = useState<string>(HELPER_TEXT);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef(0);

  const load = useCallback(async (): Promise<void> => {
    if (typeof client.listForwardLedger !== "function") {
      setRows([]);
      setError(null);
      setLoading(false);
      return;
    }
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const next = await client.listForwardLedger();
      if (requestId !== requestRef.current) {
        return;
      }
      setRows(next.events);
      if (next.disclaimer) {
        setDisclaimer(next.disclaimer);
      }
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
  }, [client]);

  useEffect(() => {
    void load();
  }, [load]);

  const showEmpty = !loading && error === null && rows !== null && rows.length === 0;
  const showRows = rows !== null && rows.length > 0;

  return (
    <div className="kbot-paper-ledger" data-testid="paper-forward-ledger">
      <div className="kbot-paper-ledger__head">
        <h3 className="kbot-paper-ledger__title">{PANEL_TITLE}</h3>
        <p className="kbot-paper-ledger__preview-badge">{LOCAL_PREVIEW_BADGE}</p>
        <button
          type="button"
          className="kbot-paper-ledger__refresh"
          data-testid="paper-forward-ledger-refresh"
          disabled={loading}
          aria-busy={loading || undefined}
          onClick={() => {
            void load();
          }}
        >
          {loading ? REFRESH_BUSY_LABEL : REFRESH_LABEL}
        </button>
      </div>
      <p className="kbot-paper-ledger__helper" data-testid="paper-forward-ledger-disclaimer">
        {disclaimer}
      </p>
      {loading && rows === null ? (
        <p className="kbot-paper-ledger__empty" data-testid="paper-forward-ledger-loading">
          {LOADING_TEXT}
        </p>
      ) : null}
      {error !== null ? (
        <p className="kbot-paper-ledger__error" role="alert" data-testid="paper-forward-ledger-error">
          {LIST_ERROR_PREFIX} {error}{" "}
          <button
            type="button"
            data-testid="paper-forward-ledger-retry"
            onClick={() => {
              void load();
            }}
          >
            {RETRY_TEXT}
          </button>
        </p>
      ) : null}
      {showEmpty ? (
        <p className="kbot-paper-ledger__empty" data-testid="paper-forward-ledger-empty">
          {EMPTY_TEXT}
        </p>
      ) : null}
      {showRows ? (
        <div className="kbot-paper-ledger__scroll" data-testid="paper-forward-ledger-scroll">
          <table className="kbot-paper-ledger__table">
            <thead>
              <tr>
                <th scope="col">{COL_TS}</th>
                <th scope="col">{COL_KIND}</th>
                <th scope="col">{COL_VENUE}</th>
                <th scope="col">{COL_PACK}</th>
                <th scope="col">{COL_PAIR}</th>
                <th scope="col">{COL_DETAIL}</th>
              </tr>
            </thead>
            <tbody>
              {rows!.map((row, index) => (
                <tr key={rowKey(row, index)} data-testid={`paper-forward-ledger-row-${index}`}>
                  <td className="kbot-paper-ledger__ts">{formatTs(row.ts)}</td>
                  <td className="kbot-paper-ledger__kind">{row.kind}</td>
                  <td className="kbot-paper-ledger__venue">{row.venue || "—"}</td>
                  <td className="kbot-paper-ledger__pack">{row.pack || "—"}</td>
                  <td className="kbot-paper-ledger__pair">{row.pair || "—"}</td>
                  <td className="kbot-paper-ledger__detail">{formatDetail(row.detail)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
