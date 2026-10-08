import { useEffect, useState, type JSX } from "react";
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

  return (
    <section
      className="kbot-paper-armed"
      role="region"
      aria-label="Armed records"
      data-testid="paper-armed-records"
    >
      <header className="kbot-paper-armed__head">
        <h2 className="kbot-paper-armed__title">Armed records</h2>
        <button
          type="button"
          className="kbot-paper-armed__refresh"
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
          <p
            className="kbot-paper-armed__empty"
            data-testid="paper-armed-loading"
          >
            Loading armed records…
          </p>
        ) : state.kind === "unavailable" ? (
          <>
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
          </>
        ) : rows.length === 0 ? (
          <p
            className="kbot-paper-armed__empty"
            data-testid="paper-armed-empty"
          >
            No packs armed
          </p>
        ) : (
          <>
            <table className="kbot-paper-armed__table">
              <thead>
                <tr>
                  <th scope="col">Venue</th>
                  <th scope="col">Pair</th>
                  <th scope="col">Mode</th>
                  <th scope="col">Pack</th>
                  <th scope="col">Entries</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={rowKey(row)}
                    data-testid="paper-armed-row"
                    data-venue={row.venue}
                    data-pair={row.pair}
                    onClick={() => {
                      setSelected(
                        selected !== null && rowKey(selected) === rowKey(row)
                          ? null
                          : row,
                      );
                    }}
                  >
                    <td>{row.venue}</td>
                    <td>{row.pair}</td>
                    <td>{row.mode}</td>
                    <td>{row.pack_id}</td>
                    <td>{sentenceFor(row.entries_paused)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {selected !== null ? (
              <div
                className="kbot-paper-armed__detail"
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
              </div>
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
