import { useEffect, useState, type JSX, type KeyboardEvent as ReactKeyboardEvent } from "react";
import "./ArmedRecordsList.signal.css";
import type { PaperArmedClient, PaperArmedRecord } from "./client";

export type { PaperArmedClient, PaperArmedRecord } from "./client";

export type ArmedRecordsListProps = {
  client: PaperArmedClient;
};

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; records: PaperArmedRecord[] }
  | { kind: "unavailable" };

type EntriesSentence = "Entries active" | "Entries paused";

function sentenceFor(entries_paused: boolean): EntriesSentence {
  return entries_paused ? "Entries paused" : "Entries active";
}

function rowKey(record: PaperArmedRecord): string {
  return `${record.venue}:${record.pair}`;
}

/** Armed-run count chip copy: the real total read from the wire. */
function armedCountLabel(count: number): string {
  return count === 1 ? "1 armed run" : `${count} armed runs`;
}

/** Entries chip tone: sage for an active armed record, coral for a
 *  paused one. The verbatim sentence carries the state. */
function entriesChipTone(entries_paused: boolean): string {
  return entries_paused ? "coral" : "sage";
}

export function ArmedRecordsList({
  client,
}: ArmedRecordsListProps): JSX.Element {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [selected, setSelected] = useState<PaperArmedRecord | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);

  // The shell may pass a legacy client that does not implement
  // listArmed (the pre-armed-records injected test client). Calling it
  // would throw synchronously, so probe for the method; anything that
  // fails resolves to the truthful unavailable state rather than a
  // manufactured empty list.
  const canListArmed =
    typeof client === "object" &&
    client !== null &&
    typeof client.listArmed === "function";

  useEffect(() => {
    if (!canListArmed) {
      setState({ kind: "unavailable" });
      return;
    }
    let cancelled = false;
    setState({ kind: "loading" });
    client
      .listArmed()
      .then((view) => {
        if (cancelled) {
          return;
        }
        setState({ kind: "ready", records: view.records });
        setSelected((current) => {
          if (current === null) {
            return null;
          }
          const match = view.records.find(
            (row) => rowKey(row) === rowKey(current),
          );
          return match ?? null;
        });
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        // A failed lookup means the list is unknown; never render an
        // empty-list claim from a failure.
        setState({ kind: "unavailable" });
        setLastError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [client, canListArmed]);

  const refresh = async (): Promise<void> => {
    if (!canListArmed || inFlight) {
      return;
    }
    setInFlight(true);
    try {
      const view = await client.listArmed();
      setState({ kind: "ready", records: view.records });
      setLastError(null);
      setSelected((current) => {
        if (current === null) {
          return null;
        }
        const match = view.records.find(
          (row) => rowKey(row) === rowKey(current),
        );
        return match ?? null;
      });
    } catch (err) {
      // Keep the last good rows on a transient failure, but surface
      // the failure honestly rather than pretending the retry worked.
      setLastError(err instanceof Error ? err.message : String(err));
      if (state.kind !== "ready") {
        setState({ kind: "unavailable" });
      }
    } finally {
      setInFlight(false);
    }
  };

  const rows = state.kind === "ready" ? state.records : [];

  // Pointer and keyboard toggle the exact same selection state.
  const toggleRow = (row: PaperArmedRecord): void => {
    setSelected(
      selected !== null && rowKey(selected) === rowKey(row) ? null : row,
    );
  };

  // Keyboard activation with native-button semantics: plain and Shift
  // chords of Enter/Space toggle the detail, Ctrl/Meta/Alt chords and
  // auto-repeats are left alone, unrelated keys keep their default.
  // Space is canceled on every press (repeats included) so a focused
  // row never scrolls the page.
  const handleRowKeyDown = (
    event: ReactKeyboardEvent<HTMLTableRowElement>,
    row: PaperArmedRecord,
  ): void => {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey) {
      return;
    }
    event.preventDefault();
    if (event.repeat) {
      return;
    }
    toggleRow(row);
  };

  return (
    <section
      className="kbot-paper-armed"
      role="region"
      aria-label="Armed records"
      data-testid="paper-armed-records"
    >
      <header
        className="kbot-paper-armed__head"
        data-testid="paper-armed-head"
      >
        <div className="kbot-paper-armed__head-titles">
          <h2 className="kbot-paper-armed__title">Armed paper runs</h2>
          {state.kind === "ready" ? (
            <p
              className="kbot-paper-armed__count"
              data-testid="paper-armed-count"
            >
              {armedCountLabel(rows.length)}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          className="kbot-paper-armed__action"
          onClick={() => {
            void refresh();
          }}
          disabled={inFlight || !canListArmed}
        >
          {inFlight ? "Refreshing…" : "Refresh"}
        </button>
      </header>
      <div className="kbot-paper-armed__body">
        {state.kind === "loading" ? (
          <section
            className="kbot-paper-armed__panel"
            aria-label="Armed paper run list"
            data-testid="paper-armed-list-panel"
          >
            <h3 className="kbot-paper-armed__panel-title">Armed</h3>
            <p
              className="kbot-paper-armed__empty"
              data-testid="paper-armed-loading"
            >
              Loading armed records…
            </p>
          </section>
        ) : state.kind === "unavailable" ? (
          <section
            className="kbot-paper-armed__panel"
            aria-label="Armed paper run list"
            data-testid="paper-armed-list-panel"
          >
            <h3 className="kbot-paper-armed__panel-title">Armed</h3>
            <p
              className="kbot-paper-armed__empty"
              role="alert"
              data-testid="paper-armed-unavailable"
            >
              Armed records unavailable
            </p>
            {lastError !== null ? (
              <p className="kbot-paper-armed__error" data-testid="paper-armed-error">
                {lastError}
              </p>
            ) : null}
          </section>
        ) : rows.length === 0 ? (
          <section
            className="kbot-paper-armed__panel"
            aria-label="Armed paper run list"
            data-testid="paper-armed-list-panel"
          >
            <h3 className="kbot-paper-armed__panel-title">Armed</h3>
            <p
              className="kbot-paper-armed__empty kbot-paper-armed__empty--none"
              data-testid="paper-armed-empty"
            >
              No packs armed
            </p>
          </section>
        ) : (
          <>
            <section
              className="kbot-paper-armed__panel"
              aria-label="Armed paper run list"
              data-testid="paper-armed-list-panel"
            >
              <h3 className="kbot-paper-armed__panel-title">Armed</h3>
              <div
                className="kbot-paper-armed__scroll"
                data-testid="paper-armed-scroll"
              >
                <table
                  className="kbot-paper-armed__table"
                  data-testid="paper-armed-table"
                >
                  <thead>
                    <tr>
                      <th scope="col">Venue</th>
                      <th scope="col">Pair</th>
                      <th scope="col">Mode</th>
                      <th scope="col">Pack</th>
                      <th scope="col">Entries</th>
                      <th scope="col">
                        <span aria-hidden="true">Open</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => {
                      const isSelected =
                        selected !== null && rowKey(selected) === rowKey(row);
                      const tone = entriesChipTone(row.entries_paused);
                      return (
                        <tr
                          key={rowKey(row)}
                          className={`kbot-paper-armed__row${
                            isSelected
                              ? " kbot-paper-armed__row--selected"
                              : ""
                          }`}
                          data-testid="paper-armed-row"
                          data-venue={row.venue}
                          data-pair={row.pair}
                          tabIndex={0}
                          aria-label={`Toggle armed record detail for ${row.venue} ${row.pair}`}
                          onClick={() => {
                            toggleRow(row);
                          }}
                          onKeyDown={(event) => {
                            handleRowKeyDown(event, row);
                          }}
                        >
                          <td className="kbot-paper-armed__mono">{row.venue}</td>
                          <td className="kbot-paper-armed__pair">{row.pair}</td>
                          <td className="kbot-paper-armed__mono">{row.mode}</td>
                          <td className="kbot-paper-armed__mono">{row.pack_id}</td>
                          <td>
                            <span
                              className={`kbot-paper-armed__chip kbot-paper-armed__chip--${tone}`}
                              data-testid={`paper-armed-status-${row.venue}-${row.pair}`}
                            >
                              {sentenceFor(row.entries_paused)}
                            </span>
                          </td>
                          <td className="kbot-paper-armed__row-open">
                            <span aria-hidden="true">›</span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
            {selected !== null ? (
              <section
                className="kbot-paper-armed__panel kbot-paper-armed__detail"
                role="region"
                aria-label="Armed record detail"
                data-testid="paper-armed-detail"
              >
                <h3 className="kbot-paper-armed__detail-title">
                  {selected.pack_id} on {selected.venue} {selected.pair}
                </h3>
                <dl>
                  <div>
                    <dt>Venue</dt>
                    <dd>{selected.venue}</dd>
                  </div>
                  <div>
                    <dt>Pair</dt>
                    <dd>{selected.pair}</dd>
                  </div>
                  <div>
                    <dt>Mode</dt>
                    <dd>{selected.mode}</dd>
                  </div>
                  <div>
                    <dt>Pack</dt>
                    <dd>{selected.pack_id}</dd>
                  </div>
                  <div>
                    <dt>Entries</dt>
                    <dd>{sentenceFor(selected.entries_paused)}</dd>
                  </div>
                </dl>
              </section>
            ) : null}
            {lastError !== null ? (
              <p
                className="kbot-paper-armed__error"
                role="alert"
                data-testid="paper-armed-refresh-error"
              >
                {lastError}
              </p>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}
