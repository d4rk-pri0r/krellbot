import { useEffect, useState, type JSX } from "react";
import "./FleetArmedList.signal.css";
import type { FleetArmedClient, FleetArmedDeployment } from "./client";

export type { FleetArmedClient, FleetArmedDeployment } from "./client";

export type FleetArmedListProps = {
  client: FleetArmedClient;
  /** Optional navigate hook used by the shell for in-app deep links. */
  onOpenDetail?: (href: string, venue: string, pair: string) => void;
};

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; deployments: FleetArmedDeployment[] }
  | { kind: "unavailable" };

function rowKey(row: FleetArmedDeployment): string {
  return `${row.venue}:${row.pair}`;
}

function fleetCountLabel(count: number): string {
  return count === 1 ? "1 armed deployment" : `${count} armed deployments`;
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

export function FleetArmedList({
  client,
  onOpenDetail,
}: FleetArmedListProps): JSX.Element {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [inFlight, setInFlight] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);

  const canListFleet =
    typeof client === "object" &&
    client !== null &&
    typeof client.listFleet === "function";

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
        setState({ kind: "ready", deployments: view.deployments });
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

  const refresh = async (): Promise<void> => {
    if (!canListFleet || inFlight) {
      return;
    }
    setInFlight(true);
    try {
      const view = await client.listFleet();
      setState({ kind: "ready", deployments: view.deployments });
      setLastError(null);
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

  const rows = state.kind === "ready" ? state.deployments : [];

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
              {fleetCountLabel(rows.length)}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          className="kbot-fleet__action"
          onClick={() => {
            void refresh();
          }}
          disabled={inFlight || !canListFleet}
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
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const tone = entriesChipTone(row.entries_paused);
                    return (
                      <tr
                        key={rowKey(row)}
                        className="kbot-fleet__row"
                        data-testid="fleet-armed-row"
                        data-venue={row.venue}
                        data-pair={row.pair}
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
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {lastError !== null ? (
              <p className="kbot-fleet__error" data-testid="fleet-armed-error">
                {lastError}
              </p>
            ) : null}
          </section>
        )}
      </div>
    </section>
  );
}
