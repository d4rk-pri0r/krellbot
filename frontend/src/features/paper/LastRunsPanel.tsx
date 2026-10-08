import { useCallback, useEffect, useState, type JSX } from "react";
import type { PaperClient, PaperRun, PaperRunsClient } from "./client";

export type { PaperClient, PaperRunsClient } from "./client";

export type LastRunsPanelProps = {
  client: PaperClient & PaperRunsClient;
};

function formatTime(ts_ms: number): string {
  if (!ts_ms) {
    return "—";
  }
  return new Date(ts_ms).toISOString();
}

export function LastRunsPanel({ client }: LastRunsPanelProps): JSX.Element {
  const [runs, setRuns] = useState<PaperRun[] | null>(null);
  const [selected, setSelected] = useState<PaperRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const load = useCallback(async (): Promise<void> => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const history = await client.listRuns();
      setRuns(history.runs);
    } catch (err) {
      // A failed read leaves the last good table in place when there is
      // one; otherwise the panel says so instead of inventing runs.
      setRuns((previous) => previous ?? []);
      setErrorMessage(
        err instanceof Error ? err.message : "Paper history unavailable",
      );
    } finally {
      setLoading(false);
    }
  }, [client]);

  useEffect(() => {
    let cancelled = false;
    client
      .listRuns()
      .then((history) => {
        if (cancelled) {
          return;
        }
        setRuns(history.runs);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        setRuns([]);
        setLoading(false);
        setErrorMessage(
          err instanceof Error ? err.message : "Paper history unavailable",
        );
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const handleRefresh = (): void => {
    void load();
  };

  const handleSelectRun = (run: PaperRun): void => {
    setSelected(run);
  };

  const handleCloseDetail = (): void => {
    setSelected(null);
  };

  return (
    <section
      className="kbot-paper-runs"
      role="region"
      aria-label="Paper last runs"
      data-testid="paper-last-runs-panel"
    >
      <header className="kbot-paper-runs__head">
        <h2 className="kbot-paper-runs__title">Last runs</h2>
        <button
          type="button"
          className="kbot-paper-runs__action"
          onClick={handleRefresh}
          disabled={loading}
          data-testid="paper-last-runs-refresh"
        >
          Refresh
        </button>
      </header>
      <div className="kbot-paper-runs__body">
        {errorMessage !== null ? (
          <p
            className="kbot-paper-runs__error"
            role="alert"
            data-testid="paper-last-runs-error"
          >
            {errorMessage}
          </p>
        ) : null}
        {loading && runs === null ? (
          <p
            className="kbot-paper-runs__empty"
            data-testid="paper-last-runs-loading"
          >
            Loading paper runs…
          </p>
        ) : runs !== null && runs.length === 0 ? (
          <p className="kbot-paper-runs__empty" data-testid="paper-last-runs-empty">
            No paper runs yet
          </p>
        ) : runs !== null ? (
          <table className="kbot-paper-runs__table" data-testid="paper-last-runs-table">
            <thead>
              <tr>
                <th scope="col">Venue</th>
                <th scope="col">Pair</th>
                <th scope="col">Started</th>
                <th scope="col">Ended</th>
                <th scope="col">Fills</th>
                <th scope="col">Last refusal</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr
                  key={`${run.venue}|${run.pair}|${run.pack_id}|${run.first_ts_ms}`}
                  onClick={() => {
                    handleSelectRun(run);
                  }}
                  data-testid={`paper-last-runs-row-${run.venue}-${run.pair}`}
                >
                  <td>{run.venue}</td>
                  <td>{run.pair}</td>
                  <td>{formatTime(run.first_ts_ms)}</td>
                  <td>{formatTime(run.last_ts_ms)}</td>
                  <td data-testid={`paper-last-runs-fills-${run.venue}-${run.pair}`}>
                    {run.recent_fills.length}
                  </td>
                  <td>{run.last_refusal_code ?? "none"}</td>
                  <td>{run.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {selected !== null ? (
          <div
            className="kbot-paper-runs__detail"
            data-testid="paper-last-runs-detail"
          >
            <p
              className="kbot-paper-runs__summary"
              data-testid="paper-last-runs-detail-summary"
            >
              {selected.summary}
            </p>
            <button
              type="button"
              className="kbot-paper-runs__action"
              onClick={handleCloseDetail}
              data-testid="paper-last-runs-detail-close"
            >
              Close detail
            </button>
          </div>
        ) : null}
      </div>
    </section>
  );
}
