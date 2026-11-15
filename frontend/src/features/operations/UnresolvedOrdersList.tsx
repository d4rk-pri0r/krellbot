import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import "./UnresolvedOrdersList.signal.css";
import type { OperationsClient, UnresolvedOrderRow } from "./client";

const LOADING_TEXT = "Loading unresolved orders…";
const EMPTY_TEXT = "No unresolved orders.";
const LIST_ERROR_PREFIX = "Could not load unresolved orders — check the workstation is running.";
const RETRY_TEXT = "Retry";
const PANEL_TITLE = "Unresolved orders";
const HELPER_TEXT =
  "Orders awaiting reconcile after an unknown venue acknowledgement. Read-only.";
const COL_COID = "Client order ID";
const COL_AGE = "Age";
const COL_LOOKUP = "Last lookup";
const AGE_UNAVAILABLE = "—";
const LOOKUP_LABELS: Readonly<Record<string, string>> = {
  filled: "filled",
  open: "open",
  absent: "absent",
  none: "none",
};

export type UnresolvedOrdersListProps = {
  client: OperationsClient;
};

function rowTestId(clientOrderId: string): string {
  return `ops-unresolved-row-${clientOrderId}`;
}

function formatAge(ageSeconds: number | null): string {
  if (ageSeconds === null || !Number.isFinite(ageSeconds) || ageSeconds < 0) {
    return AGE_UNAVAILABLE;
  }
  const seconds = Math.floor(ageSeconds);
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const rem = seconds % 60;
  if (minutes < 60) {
    return rem === 0 ? `${minutes}m` : `${minutes}m ${rem}s`;
  }
  const hours = Math.floor(minutes / 60);
  const remMin = minutes % 60;
  return remMin === 0 ? `${hours}h` : `${hours}h ${remMin}m`;
}

function lookupLabel(result: string): string {
  return LOOKUP_LABELS[result] ?? result;
}

export function UnresolvedOrdersList({ client }: UnresolvedOrdersListProps): JSX.Element {
  const [rows, setRows] = useState<UnresolvedOrderRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef(0);

  const load = useCallback(async (): Promise<void> => {
    if (typeof client.listUnresolvedOrders !== "function") {
      setRows([]);
      setError(null);
      setLoading(false);
      return;
    }
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const next = await client.listUnresolvedOrders();
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
  }, [client]);

  useEffect(() => {
    void load();
  }, [load]);

  const showEmpty = !loading && error === null && rows !== null && rows.length === 0;
  const showRows = rows !== null && rows.length > 0;

  return (
    <div className="kbot-ops__unresolved" data-testid="ops-unresolved-orders">
      <div className="kbot-ops__unresolved-head">
        <h3 className="kbot-ops__panel-title">{PANEL_TITLE}</h3>
        <button
          type="button"
          className="kbot-ops__unresolved-refresh"
          data-testid="ops-unresolved-refresh"
          disabled={loading}
          aria-busy={loading || undefined}
          onClick={() => {
            void load();
          }}
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      <p className="kbot-ops__unresolved-helper">{HELPER_TEXT}</p>
      {loading && rows === null ? (
        <p className="kbot-ops__empty" data-testid="ops-unresolved-loading">
          {LOADING_TEXT}
        </p>
      ) : null}
      {error !== null ? (
        <p className="kbot-ops__row-result" role="alert" data-testid="ops-unresolved-error">
          {LIST_ERROR_PREFIX} {error}{" "}
          <button
            type="button"
            data-testid="ops-unresolved-retry"
            onClick={() => {
              void load();
            }}
          >
            {RETRY_TEXT}
          </button>
        </p>
      ) : null}
      {showEmpty ? (
        <p className="kbot-ops__empty" data-testid="ops-unresolved-empty">
          {EMPTY_TEXT}
        </p>
      ) : null}
      {showRows ? (
        <div className="kbot-ops__unresolved-scroll" data-testid="ops-unresolved-scroll">
          <table className="kbot-ops__unresolved-table">
            <thead>
              <tr>
                <th scope="col">{COL_COID}</th>
                <th scope="col">{COL_AGE}</th>
                <th scope="col">{COL_LOOKUP}</th>
              </tr>
            </thead>
            <tbody>
              {rows!.map((row) => (
                <tr key={row.client_order_id} data-testid={rowTestId(row.client_order_id)}>
                  <td className="kbot-ops__unresolved-coid">{row.client_order_id}</td>
                  <td className="kbot-ops__unresolved-age">{formatAge(row.age_seconds)}</td>
                  <td className="kbot-ops__unresolved-lookup">
                    {lookupLabel(row.last_lookup_result)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
