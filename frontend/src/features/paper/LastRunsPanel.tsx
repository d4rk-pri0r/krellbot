import { useCallback, useEffect, useId, useRef, useState, type JSX } from "react";
import "./LastRunsPanel.signal.css";
import type { PaperClient, PaperRun, PaperRunsClient } from "./client";

export type { PaperClient, PaperRunsClient } from "./client";

export type LastRunsPanelProps = {
  client: PaperClient & PaperRunsClient;
};

const COPY_FEEDBACK_MS = 2000;
type CopyOutcome = "ok" | "fail" | null;
type CopyOperation = { frame?: number; timer?: number };

function keyFor(run: PaperRun): string {
  return JSON.stringify([run.venue, run.pair, run.pack_id, run.first_ts_ms]);
}

function legacyFallback(text: string): void {
  // Older browsers without the Clipboard API can still copy via a selected,
  // hidden textarea. A denied API write must not silently use this fallback.
  const previousFocus = document.activeElement;
  const field = document.createElement("textarea");
  field.value = text;
  field.style.cssText = "position:fixed;opacity:0;pointer-events:none";
  document.body.appendChild(field);
  try {
    field.focus();
    field.select();
    if (!document.execCommand("copy")) throw new Error("Copy refused");
  } finally {
    field.remove();
    if (previousFocus instanceof HTMLElement) previousFocus.focus({ preventScroll: true });
  }
}

function formatTime(ts_ms: number): string {
  if (!ts_ms) {
    return "—";
  }
  return new Date(ts_ms).toISOString();
}

// Fills render in the viewer's local time, unlike the run rows above which
// stay UTC; a missing or invalid stamp shows "—", never a fabricated one.
function formatFillTime(ts_ms: number): string {
  if (!ts_ms || !Number.isFinite(ts_ms)) {
    return "—";
  }
  const date = new Date(ts_ms);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  const pad = (value: number): string => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

/** Run-count chip copy: the real total read from the wire. */
function runCountLabel(count: number): string {
  return count === 1 ? "1 run" : `${count} runs`;
}

/** Status chip tone: sage for an armed/active run, coral for a failed
 *  one, neutral otherwise. The verbatim status word carries the state. */
function statusChipTone(status: string): string {
  if (status === "active") {
    return "sage";
  }
  if (status === "failed") {
    return "coral";
  }
  return "neutral";
}

/** Side badge tone: sage for buy, coral for sell, neutral otherwise. */
function sideBadgeTone(side: string): string {
  if (side === "buy") {
    return "buy";
  }
  if (side === "sell") {
    return "sell";
  }
  return "";
}

export function LastRunsPanel({ client }: LastRunsPanelProps): JSX.Element {
  const detailId = useId();
  const [runs, setRuns] = useState<PaperRun[] | null>(null);
  const [selected, setSelected] = useState<PaperRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [copyState, setCopyState] = useState<Record<string, CopyOutcome>>({});
  const copyOperations = useRef<Record<string, CopyOperation>>({});

  useEffect(() => () => {
    for (const operation of Object.values(copyOperations.current)) {
      if (operation.frame !== undefined) cancelAnimationFrame(operation.frame);
      if (operation.timer !== undefined) window.clearTimeout(operation.timer);
    }
    copyOperations.current = {};
  }, []);

  async function handleCopyText(key: string, text: string): Promise<void> {
    const previous = copyOperations.current[key];
    if (previous?.frame !== undefined) cancelAnimationFrame(previous.frame);
    if (previous?.timer !== undefined) window.clearTimeout(previous.timer);
    const operation: CopyOperation = {};
    copyOperations.current[key] = operation;
    setCopyState((state) => ({ ...state, [key]: null }));
    let outcome: CopyOutcome = "ok";
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
      else legacyFallback(text);
    } catch {
      outcome = "fail";
    }
    if (copyOperations.current[key] !== operation) return;
    operation.frame = requestAnimationFrame(() => {
      if (copyOperations.current[key] !== operation) return;
      setCopyState((state) => ({ ...state, [key]: outcome }));
      operation.timer = window.setTimeout(() => {
        if (copyOperations.current[key] !== operation) return;
        setCopyState((state) => ({ ...state, [key]: null }));
        delete copyOperations.current[key];
      }, COPY_FEEDBACK_MS);
    });
  }

  async function handleCopyRun(run: PaperRun): Promise<void> {
    await handleCopyText(keyFor(run), run.summary);
  }

  function copyLabel(key: string, label = "Copy"): string {
    return copyState[key] === "ok" ? "Copied" : copyState[key] === "fail" ? "Copy failed" : label;
  }

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
        <div className="kbot-paper-runs__head-titles">
          <h2 className="kbot-paper-runs__title">Paper runs</h2>
          {runs !== null ? (
            <p
              className="kbot-paper-runs__count"
              data-testid="paper-last-runs-count"
            >
              {runCountLabel(runs.length)}
            </p>
          ) : null}
        </div>
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
        <section
          className="kbot-paper-runs__panel"
          aria-label="Paper run history list"
          data-testid="paper-last-runs-list-panel"
        >
          <h3 className="kbot-paper-runs__panel-title">Runs</h3>
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
            <div
              className="kbot-paper-runs__scroll"
              data-testid="paper-last-runs-scroll"
            >
              <table className="kbot-paper-runs__table" data-testid="paper-last-runs-table">
                <thead>
                  <tr>
                    <th scope="col">Venue</th>
                    <th scope="col">Pair</th>
                    <th scope="col">Started</th>
                    <th scope="col">Ended</th>
                    <th scope="col">Status</th>
                    <th scope="col">Fills</th>
                    <th scope="col">Last refusal</th>
                    <th scope="col">Result</th>
                    <th scope="col">
                      <span aria-hidden="true">Open</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => {
                    const tone = statusChipTone(run.status);
                    const isSelected = selected === run;
                    return (
                      <tr
                        key={`${run.venue}|${run.pair}|${run.pack_id}|${run.first_ts_ms}`}
                        className={`kbot-paper-runs__row${
                          isSelected ? " kbot-paper-runs__row--selected" : ""
                        }`}
                        tabIndex={0}
                        aria-expanded={isSelected}
                        aria-controls={detailId}
                        aria-label={`Open run detail for ${run.venue} ${run.pair}`}
                        onClick={() => {
                          handleSelectRun(run);
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            handleSelectRun(run);
                          }
                        }}
                        data-testid={`paper-last-runs-row-${run.venue}-${run.pair}`}
                      >
                        <td className="kbot-paper-runs__venue">{run.venue}</td>
                        <td className="kbot-paper-runs__pair">{run.pair}</td>
                        <td className="kbot-paper-runs__ts">
                          {formatTime(run.first_ts_ms)}
                        </td>
                        <td className="kbot-paper-runs__ts">
                          {formatTime(run.last_ts_ms)}
                        </td>
                        <td>
                          <span
                            className={`kbot-paper-runs__chip${
                              tone === "neutral"
                                ? ""
                                : ` kbot-paper-runs__chip--${tone}`
                            }`}
                            data-testid={`paper-last-runs-status-${run.venue}-${run.pair}`}
                          >
                            {run.status}
                          </span>
                        </td>
                        <td
                          className="kbot-paper-runs__num"
                          data-testid={`paper-last-runs-fills-${run.venue}-${run.pair}`}
                        >
                          {run.recent_fills.length}
                        </td>
                        <td
                          className={`kbot-paper-runs__refusal${
                            run.last_refusal_code !== null
                              ? " kbot-paper-runs__refusal--present"
                              : ""
                          }`}
                        >
                          {run.last_refusal_code ?? "none"}
                        </td>
                        <td className="kbot-paper-runs__result">{run.summary}</td>
                        <td className="kbot-paper-runs__row-open">
                          <button
                            type="button"
                            className="kbot-paper-runs__action kbot-paper-runs__copy"
                            data-testid={`paper-last-runs-copy-${run.venue}-${run.pair}`}
                            aria-label={`Copy summary for ${run.venue} ${run.pair}`}
                            title="Copy summary"
                            onKeyDown={(event) => { event.stopPropagation(); }}
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleCopyRun(run);
                            }}
                          >
                            {copyLabel(keyFor(run))}
                          </button>
                          <span aria-hidden="true">›</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
        {selected !== null ? (
          <section
            className="kbot-paper-runs__panel kbot-paper-runs__detail"
            id={detailId}
            aria-label="Selected paper run detail"
            data-testid="paper-last-runs-detail"
          >
            <div className="kbot-paper-runs__detail-head">
              <h3 className="kbot-paper-runs__panel-title">Run detail</h3>
              <button
                type="button"
                className="kbot-paper-runs__action"
                onClick={handleCloseDetail}
                data-testid="paper-last-runs-detail-close"
              >
                Close detail
              </button>
            </div>
            <p
              className="kbot-paper-runs__summary"
              data-testid="paper-last-runs-detail-summary"
            >
              {selected.summary}
            </p>
            {selected.recent_fills.length > 0 ? (
              <div
                className="kbot-paper-runs__scroll"
                data-testid="paper-last-runs-fills-scroll"
              >
                <table
                  className="kbot-paper-runs__fills"
                  data-testid="paper-last-runs-fills-table"
                >
                  <thead>
                    <tr>
                      <th scope="col">Time</th>
                      <th scope="col">Pair</th>
                      <th scope="col">Side</th>
                      <th scope="col">Coid</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selected.recent_fills.map((fill, index) => {
                      const sideTone = sideBadgeTone(fill.side);
                      const fillCopyKey = JSON.stringify([keyFor(selected), fill.coid, fill.ts_ms, index]);
                      return (
                        <tr key={`${fill.coid}|${fill.ts_ms}|${index}`}>
                          <td className="kbot-paper-runs__ts">
                            {formatFillTime(fill.ts_ms)}
                          </td>
                          {/* The paper-history wire carries pair at the run level,
                              not on the adapted fill objects (see adaptHistory in
                              client.ts), so every fill row reuses selected.pair. */}
                          <td className="kbot-paper-runs__pair">{selected.pair}</td>
                          <td>
                            <span
                              className={`kbot-paper-runs__side${
                                sideTone === ""
                                  ? ""
                                  : ` kbot-paper-runs__side--${sideTone}`
                              }`}
                            >
                              {fill.side}
                            </span>
                          </td>
                          <td className="kbot-paper-runs__coid">
                            {fill.coid}{" "}
                            <button
                              type="button"
                              className="kbot-paper-runs__action kbot-paper-runs__copy"
                              aria-label="Copy coid"
                              title="Copy coid"
                              onClick={() => { void handleCopyText(fillCopyKey, fill.coid); }}
                            >
                              {copyLabel(fillCopyKey, "Copy coid")}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <p
                className="kbot-paper-runs__fills-empty"
                data-testid="paper-last-runs-fills-empty"
              >
                no fills in this run
              </p>
            )}
          </section>
        ) : null}
      </div>
    </section>
  );
}
