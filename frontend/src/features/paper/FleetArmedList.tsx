import { useEffect, useRef, useState, type JSX, type KeyboardEvent } from "react";
import "./FleetArmedList.signal.css";
import { UnresolvedOrdersList } from "../operations/UnresolvedOrdersList";
import type { OperationsClient } from "../operations/client";
import type {
  FleetArmedClient,
  FleetArmedDeployment,
  PaperClient,
  PaperCommandResult,
} from "./client";

export type { FleetArmedClient, FleetArmedDeployment } from "./client";

/** Paper commands the fleet list uses for pause / resume / disarm. */
export type FleetArmedCommands = Pick<
  PaperClient,
  "pauseEntries" | "resumeEntries" | "disarm"
>;

export type FleetArmedListProps = {
  client: FleetArmedClient & Partial<FleetArmedCommands>;
  /** Optional navigate hook used by the shell for in-app deep links. */
  onOpenDetail?: (href: string, venue: string, pair: string) => void;
  /**
   * When provided, selecting a fleet row reports the closed armed identity
   * so the Workstation Inspector stays truthful (M7.4 / M16.2).
   */
  onSelectionChange?: (row: FleetArmedDeployment | null) => void;
  /**
   * When provided, the fleet management surface mounts the same
   * UnresolvedOrdersList used on Operations (read-only parity) and shows
   * an unresolved summary count in the fleet header.
   */
  unresolvedClient?: Pick<OperationsClient, "listUnresolvedOrders">;
};

type LoadState =
  | { kind: "loading" }
  | {
      kind: "ready";
      deployments: FleetArmedDeployment[];
      armed_count: number;
    }
  | { kind: "unavailable" };

type RowActionKind = "pause" | "resume" | "disarm";

function rowKey(row: FleetArmedDeployment): string {
  return `${row.venue}:${row.pair}`;
}

function fleetCountLabel(count: number): string {
  return count === 1 ? "1 armed deployment" : `${count} armed deployments`;
}

function unresolvedSummaryLabel(count: number): string {
  return count === 1 ? "1 unresolved order" : `${count} unresolved orders`;
}

function entriesChipTone(entries_paused: boolean): string {
  return entries_paused ? "coral" : "sage";
}

/** UTC ISO stamp; missing/invalid → "—" (never invent a time). */
function formatTickTime(ts_ms: number | null): string {
  if (ts_ms === null || !Number.isFinite(ts_ms)) {
    return "—";
  }
  const date = new Date(ts_ms);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return date.toISOString();
}

function actionLabel(kind: RowActionKind): string {
  if (kind === "pause") {
    return "Pause new buys";
  }
  if (kind === "resume") {
    return "Resume new buys";
  }
  return "Stop paper run";
}

export function FleetArmedList({
  client,
  onOpenDetail,
  onSelectionChange,
  unresolvedClient,
}: FleetArmedListProps): JSX.Element {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [inFlight, setInFlight] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const [rowActionInFlight, setRowActionInFlight] = useState(false);
  const [rowActionKind, setRowActionKind] = useState<RowActionKind | null>(null);
  const [rowActionError, setRowActionError] = useState<string | null>(null);
  /** Row that last started an action — kept after settle so errors stay on that row. */
  const rowActionKeyRef = useRef<string | null>(null);
  const [selected, setSelected] = useState<FleetArmedDeployment | null>(null);
  const [unresolvedCount, setUnresolvedCount] = useState<number | null>(null);

  const canListFleet =
    typeof client === "object" &&
    client !== null &&
    typeof client.listFleet === "function";

  const canPause = typeof client.pauseEntries === "function";
  const canResume = typeof client.resumeEntries === "function";
  const canDisarm = typeof client.disarm === "function";
  const canMutate = canPause || canResume || canDisarm;

  const showUnresolved =
    unresolvedClient !== undefined &&
    unresolvedClient !== null &&
    typeof unresolvedClient.listUnresolvedOrders === "function";

  useEffect(() => {
    if (!canListFleet) {
      setState({ kind: "unavailable" });
      return;
    }
    let cancelled = false;
    setState({ kind: "loading" });
    client
      .listFleet()
      .then((view) => {
        if (cancelled) {
          return;
        }
        setState({
          kind: "ready",
          deployments: view.deployments,
          armed_count:
            typeof view.armed_count === "number"
              ? view.armed_count
              : view.deployments.length,
        });
        setLastError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        setState({ kind: "unavailable" });
        setLastError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [client, canListFleet]);

  useEffect(() => {
    const listUnresolved = unresolvedClient?.listUnresolvedOrders;
    if (typeof listUnresolved !== "function") {
      setUnresolvedCount(null);
      return;
    }
    let cancelled = false;
    listUnresolved()
      .then((rows) => {
        if (!cancelled) {
          setUnresolvedCount(rows.length);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUnresolvedCount(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [unresolvedClient]);

  // Keep selection truthful after a refresh: drop it when the arm is gone,
  // otherwise refresh the selected snapshot from the new list.
  useEffect(() => {
    if (state.kind !== "ready" || selected === null) {
      return;
    }
    const next = state.deployments.find((row) => rowKey(row) === rowKey(selected));
    if (next === undefined) {
      setSelected(null);
      onSelectionChange?.(null);
      return;
    }
    if (
      next.entries_paused !== selected.entries_paused ||
      next.pack_id !== selected.pack_id ||
      next.last_tick_ts_ms !== selected.last_tick_ts_ms ||
      next.last_tick_result !== selected.last_tick_result
    ) {
      setSelected(next);
      onSelectionChange?.(next);
    }
  }, [state, selected, onSelectionChange]);

  const applyReadyView = (view: {
    deployments: FleetArmedDeployment[];
    armed_count?: number;
  }): void => {
    setState({
      kind: "ready",
      deployments: view.deployments,
      armed_count:
        typeof view.armed_count === "number"
          ? view.armed_count
          : view.deployments.length,
    });
  };

  const refresh = async (): Promise<void> => {
    if (!canListFleet || inFlight) {
      return;
    }
    setInFlight(true);
    try {
      const view = await client.listFleet();
      applyReadyView(view);
      setLastError(null);
      const listUnresolved = unresolvedClient?.listUnresolvedOrders;
      if (typeof listUnresolved === "function") {
        try {
          const rows = await listUnresolved();
          setUnresolvedCount(rows.length);
        } catch {
          // Keep the last known summary; refresh failure is surfaceable via list.
        }
      }
    } catch (err) {
      setLastError(err instanceof Error ? err.message : String(err));
      if (state.kind !== "ready") {
        setState({ kind: "unavailable" });
      }
    } finally {
      setInFlight(false);
    }
  };

  const openDetail = (row: FleetArmedDeployment): void => {
    if (onOpenDetail) {
      onOpenDetail(row.detail_href, row.venue, row.pair);
      return;
    }
    if (typeof window !== "undefined") {
      window.location.assign(row.detail_href);
    }
  };

  const selectRow = (row: FleetArmedDeployment): void => {
    const next =
      selected !== null && rowKey(selected) === rowKey(row) ? null : row;
    setSelected(next);
    onSelectionChange?.(next);
    setRowActionError(null);
  };

  const handleRowKeyDown = (
    event: KeyboardEvent<HTMLTableRowElement>,
    row: FleetArmedDeployment,
  ): void => {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    event.preventDefault();
    selectRow(row);
  };

  const runRowAction = async (
    row: FleetArmedDeployment,
    kind: RowActionKind,
  ): Promise<void> => {
    if (rowActionInFlight) {
      return;
    }
    const key = rowKey(row);
    const label = actionLabel(kind);
    const command =
      kind === "pause"
        ? client.pauseEntries
        : kind === "resume"
          ? client.resumeEntries
          : client.disarm;
    if (typeof command !== "function") {
      rowActionKeyRef.current = key;
      setRowActionKind(kind);
      setRowActionError(`${label} failed: command unavailable`);
      return;
    }
    rowActionKeyRef.current = key;
    setRowActionKind(kind);
    setRowActionInFlight(true);
    setRowActionError(null);
    try {
      const result: PaperCommandResult = await command(row.venue, row.pair);
      if (result?.ok !== true) {
        throw new Error(result?.message || result?.code || "Command success was not confirmed");
      }
      setRowActionError(null);
      setRowActionKind(null);
      try {
        const view = await client.listFleet();
        applyReadyView(view);
        setLastError(null);
      } catch (err) {
        // A confirmed command must not be reported as failed when only its readback fails.
        setLastError(err instanceof Error ? err.message : String(err));
      }
    } catch (err) {
      setRowActionError(`${label} failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setRowActionInFlight(false);
    }
  };

  const rows = state.kind === "ready" ? state.deployments : [];
  const armedCount = state.kind === "ready" ? state.armed_count : 0;

  return (
    <section
      className="kbot-fleet"
      role="region"
      aria-label="Armed fleet"
      data-testid="fleet-armed-list"
    >
      <header className="kbot-fleet__head" data-testid="fleet-armed-head">
        <div className="kbot-fleet__head-titles">
          <h2 className="kbot-fleet__title">Armed fleet</h2>
          {state.kind === "ready" ? (
            <p className="kbot-fleet__count" data-testid="fleet-armed-count">
              {fleetCountLabel(armedCount)}
            </p>
          ) : null}
          {showUnresolved && unresolvedCount !== null ? (
            <p
              className="kbot-fleet__unresolved-summary"
              data-testid="fleet-unresolved-summary"
            >
              {unresolvedSummaryLabel(unresolvedCount)}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          className="kbot-fleet__action"
          onClick={() => {
            void refresh();
          }}
          disabled={inFlight || !canListFleet || rowActionInFlight}
        >
          {inFlight ? "Refreshing…" : "Refresh"}
        </button>
      </header>
      <div className="kbot-fleet__body">
        {state.kind === "loading" ? (
          <section
            className="kbot-fleet__panel"
            aria-label="Armed fleet list"
            data-testid="fleet-armed-panel"
          >
            <h3 className="kbot-fleet__panel-title">Deployments</h3>
            <p className="kbot-fleet__empty" data-testid="fleet-armed-loading">
              Loading armed fleet…
            </p>
          </section>
        ) : state.kind === "unavailable" ? (
          <section
            className="kbot-fleet__panel"
            aria-label="Armed fleet list"
            data-testid="fleet-armed-panel"
          >
            <h3 className="kbot-fleet__panel-title">Deployments</h3>
            <p
              className="kbot-fleet__empty"
              role="alert"
              data-testid="fleet-armed-unavailable"
            >
              Armed fleet unavailable
            </p>
            {lastError !== null ? (
              <p className="kbot-fleet__error" data-testid="fleet-armed-error">
                {lastError}
              </p>
            ) : null}
          </section>
        ) : rows.length === 0 ? (
          <section
            className="kbot-fleet__panel"
            aria-label="Armed fleet list"
            data-testid="fleet-armed-panel"
          >
            <h3 className="kbot-fleet__panel-title">Deployments</h3>
            <p
              className="kbot-fleet__empty kbot-fleet__empty--none"
              data-testid="fleet-armed-empty"
            >
              No packs armed
            </p>
          </section>
        ) : (
          <section
            className="kbot-fleet__panel"
            aria-label="Armed fleet list"
            data-testid="fleet-armed-panel"
          >
            <h3 className="kbot-fleet__panel-title">Deployments</h3>
            <div className="kbot-fleet__scroll" data-testid="fleet-armed-scroll">
              <table className="kbot-fleet__table" data-testid="fleet-armed-table">
                <thead>
                  <tr>
                    <th scope="col">Market</th>
                    <th scope="col">Pack</th>
                    <th scope="col">Entries</th>
                    <th scope="col">Last tick</th>
                    <th scope="col">Result</th>
                    <th scope="col">Detail</th>
                    {canMutate ? <th scope="col">Actions</th> : null}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const tone = entriesChipTone(row.entries_paused);
                    const key = rowKey(row);
                    const isSelected =
                      selected !== null && rowKey(selected) === key;
                    const rowBusy =
                      rowActionInFlight && rowActionKeyRef.current === key;
                    return (
                      <tr
                        key={key}
                        className={`kbot-fleet__row${
                          isSelected ? " kbot-fleet__row--selected" : ""
                        }`}
                        data-testid="fleet-armed-row"
                        data-venue={row.venue}
                        data-pair={row.pair}
                        data-selected={isSelected ? "true" : undefined}
                        tabIndex={0}
                        aria-selected={isSelected}
                        aria-label={`Select fleet arm ${row.venue} ${row.pair}`}
                        onClick={() => {
                          selectRow(row);
                        }}
                        onKeyDown={(event) => {
                          handleRowKeyDown(event, row);
                        }}
                      >
                        <td>
                          <span className="kbot-fleet__market">
                            {row.venue} · {row.pair}
                          </span>
                          <span className="kbot-fleet__mode">{row.mode}</span>
                        </td>
                        <td>
                          <span className="kbot-fleet__pack">{row.pack_id}</span>
                        </td>
                        <td>
                          <span
                            className={`kbot-fleet__chip kbot-fleet__chip--${tone}`}
                            data-testid="fleet-armed-entries"
                          >
                            {row.entries_paused ? "Entries paused" : "Entries active"}
                          </span>
                        </td>
                        <td>
                          <time
                            className="kbot-fleet__tick-time"
                            data-testid="fleet-armed-last-tick"
                            dateTime={
                              row.last_tick_ts_ms !== null
                                ? new Date(row.last_tick_ts_ms).toISOString()
                                : undefined
                            }
                          >
                            {formatTickTime(row.last_tick_ts_ms)}
                          </time>
                        </td>
                        <td>
                          <span
                            className="kbot-fleet__tick-result"
                            data-testid="fleet-armed-last-result"
                          >
                            {row.last_tick_result}
                          </span>
                        </td>
                        <td>
                          <a
                            className="kbot-fleet__detail"
                            href={row.detail_href}
                            data-testid="fleet-armed-detail-link"
                            onClick={(event) => {
                              event.stopPropagation();
                              if (
                                event.defaultPrevented ||
                                event.button !== 0 ||
                                event.metaKey ||
                                event.ctrlKey ||
                                event.shiftKey ||
                                event.altKey
                              ) {
                                return;
                              }
                              event.preventDefault();
                              openDetail(row);
                            }}
                          >
                            Open detail
                          </a>
                        </td>
                        {canMutate ? (
                          <td>
                            <div
                              className="kbot-fleet__row-actions"
                              data-testid="fleet-armed-row-actions"
                              onClick={(event) => {
                                event.stopPropagation();
                              }}
                            >
                              {canPause ? (
                                <button
                                  type="button"
                                  className="kbot-fleet__row-action"
                                  data-testid="fleet-armed-row-pause"
                                  aria-label={`Pause new buys on ${row.venue} ${row.pair}`}
                                  disabled={
                                    rowActionInFlight ||
                                    row.entries_paused === true
                                  }
                                  onClick={() => {
                                    void runRowAction(row, "pause");
                                  }}
                                >
                                  {rowBusy && rowActionKind === "pause"
                                    ? "Pausing…"
                                    : "Pause new buys"}
                                </button>
                              ) : null}
                              {canResume ? (
                                <button
                                  type="button"
                                  className="kbot-fleet__row-action"
                                  data-testid="fleet-armed-row-resume"
                                  aria-label={`Resume new buys on ${row.venue} ${row.pair}`}
                                  disabled={
                                    rowActionInFlight ||
                                    row.entries_paused === false
                                  }
                                  onClick={() => {
                                    void runRowAction(row, "resume");
                                  }}
                                >
                                  {rowBusy && rowActionKind === "resume"
                                    ? "Resuming…"
                                    : "Resume new buys"}
                                </button>
                              ) : null}
                              {canDisarm ? (
                                <button
                                  type="button"
                                  className="kbot-fleet__row-action"
                                  data-testid="fleet-armed-row-disarm"
                                  aria-label={`Stop paper run ${row.venue} ${row.pair}`}
                                  disabled={rowActionInFlight}
                                  onClick={() => {
                                    void runRowAction(row, "disarm");
                                  }}
                                >
                                  {rowBusy && rowActionKind === "disarm"
                                    ? "Stopping…"
                                    : "Stop paper run"}
                                </button>
                              ) : null}
                              {rowActionError !== null &&
                              rowActionKind !== null &&
                              rowActionKeyRef.current === key ? (
                                <p
                                  data-testid="fleet-armed-row-action-error"
                                  role="alert"
                                  className="kbot-fleet__row-action-error"
                                >
                                  {rowActionError}
                                </p>
                              ) : null}
                            </div>
                          </td>
                        ) : null}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {selected !== null ? (
              <div
                className="kbot-fleet__selected"
                data-testid="fleet-armed-selected"
                aria-label="Selected fleet arm"
              >
                <p className="kbot-fleet__selected-title">
                  Selected arm: {selected.venue} · {selected.pair}
                </p>
                <dl className="kbot-fleet__selected-meta">
                  <div>
                    <dt>Pack</dt>
                    <dd data-testid="fleet-armed-selected-pack">{selected.pack_id}</dd>
                  </div>
                  <div>
                    <dt>Last tick</dt>
                    <dd data-testid="fleet-armed-selected-tick">
                      {formatTickTime(selected.last_tick_ts_ms)}
                    </dd>
                  </div>
                  <div>
                    <dt>Result</dt>
                    <dd data-testid="fleet-armed-selected-result">
                      {selected.last_tick_result}
                    </dd>
                  </div>
                  <div>
                    <dt>Entries</dt>
                    <dd data-testid="fleet-armed-selected-entries">
                      {selected.entries_paused ? "Entries paused" : "Entries active"}
                    </dd>
                  </div>
                </dl>
                {canMutate ? (
                  <div
                    className="kbot-fleet__selected-actions"
                    data-testid="fleet-armed-selected-actions"
                  >
                    {canPause ? (
                      <button
                        type="button"
                        className="kbot-fleet__row-action"
                        data-testid="fleet-armed-selected-pause"
                        aria-label={`Pause new buys on selected ${selected.venue} ${selected.pair}`}
                        disabled={
                          rowActionInFlight || selected.entries_paused === true
                        }
                        onClick={() => {
                          void runRowAction(selected, "pause");
                        }}
                      >
                        Pause new buys
                      </button>
                    ) : null}
                    {canResume ? (
                      <button
                        type="button"
                        className="kbot-fleet__row-action"
                        data-testid="fleet-armed-selected-resume"
                        aria-label={`Resume new buys on selected ${selected.venue} ${selected.pair}`}
                        disabled={
                          rowActionInFlight || selected.entries_paused === false
                        }
                        onClick={() => {
                          void runRowAction(selected, "resume");
                        }}
                      >
                        Resume new buys
                      </button>
                    ) : null}
                    {canDisarm ? (
                      <button
                        type="button"
                        className="kbot-fleet__row-action"
                        data-testid="fleet-armed-selected-disarm"
                        aria-label={`Stop paper run selected ${selected.venue} ${selected.pair}`}
                        disabled={rowActionInFlight}
                        onClick={() => {
                          void runRowAction(selected, "disarm");
                        }}
                      >
                        Stop paper run
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
            {lastError !== null ? (
              <p className="kbot-fleet__error" data-testid="fleet-armed-error">
                {lastError}
              </p>
            ) : null}
          </section>
        )}
        {showUnresolved ? (
          <section
            className="kbot-fleet__panel"
            aria-label="Unresolved orders"
            data-testid="fleet-unresolved-panel"
          >
            <UnresolvedOrdersList
              client={unresolvedClient as OperationsClient}
            />
          </section>
        ) : null}
      </div>
    </section>
  );
}
