import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type JSX,
} from "react";
import type { ResearchClient, StoredResult } from "./client";

export type { ResearchClient, StoredResult } from "./client";

export type ResearchViewProps = {
  client: ResearchClient;
  revisionId?: string | null;
};

type TraceCondition = {
  path?: unknown;
  outcome?: unknown;
};

type TraceBar = {
  bar_ts?: unknown;
  input?: { close?: unknown };
  conditions?: TraceCondition[];
};

const SYNTHETIC_FIXTURE_PATH = "fixtures/synthetic.csv";

const TRACE_ROW_HEIGHT = 24;
const TRACE_OVERSCAN_ROWS = 8;
const TRACE_VIEWPORT_HEIGHT = 480;

function readNumberField(value: string): number {
  const trimmed = value.trim();
  if (trimmed === "") {
    return 0;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : 0;
}

function readStringField(value: string): string {
  return value;
}

function isIntegerString(value: string): boolean {
  return /^-?\d+$/.test(value);
}

function formatMetric(value: unknown): string {
  if (value === null || value === undefined) {
    return "unavailable";
  }
  if (typeof value === "number") {
    return String(value);
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return "unavailable";
}

function readTradeCount(receipt: Record<string, unknown>): string {
  // Real engine receipts expose the count under ``metrics.trade_count``;
  // unit tests and the locked CLI receipt may also expose a top-level
  // ``trades`` array or a top-level ``trade_count`` number. Read all
  // three shapes so the UI displays a real value for both the
  // production receipt and the test fixture.
  const trades = receipt.trades;
  if (Array.isArray(trades)) {
    return String(trades.length);
  }
  const topLevelCount = receipt.trade_count;
  if (typeof topLevelCount === "number" && Number.isFinite(topLevelCount)) {
    return String(topLevelCount);
  }
  const metrics = receipt.metrics;
  if (metrics && typeof metrics === "object" && !Array.isArray(metrics)) {
    const metricCount = (metrics as Record<string, unknown>).trade_count;
    if (typeof metricCount === "number" && Number.isFinite(metricCount)) {
      return String(metricCount);
    }
  }
  return "unavailable";
}

function readMetrics(receipt: Record<string, unknown>): Record<string, unknown> | null {
  const metrics = receipt.metrics;
  if (metrics && typeof metrics === "object" && !Array.isArray(metrics)) {
    return metrics as Record<string, unknown>;
  }
  return null;
}

function readPercentageMetric(
  receipt: Record<string, unknown>,
  key: string,
): string {
  // Production receipts carry typed percentage metrics under ``metrics``
  // (e.g. total_return_pct). Only a real finite number is displayed;
  // missing, null, wrong-shape, and non-finite values stay unavailable —
  // never a fabricated zero.
  const metrics = readMetrics(receipt);
  if (metrics === null) {
    return "unavailable";
  }
  const value = metrics[key];
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return "unavailable";
}

function readEquity(receipt: Record<string, unknown>): string {
  // DISC-EQUITY-UNIT: the locked receipt shape has no currency equity.
  // ``metrics.total_return_pct`` and ``equity_curve`` are percentage
  // return series, not cash, so they must never satisfy the Equity
  // metric; deriving cash from an assumed starting value is forbidden.
  // Only an explicit top-level ``equity`` field (older unit-test
  // fixtures) is displayed as-is.
  const topLevelEquity = receipt.equity;
  if (typeof topLevelEquity === "number" && Number.isFinite(topLevelEquity)) {
    return String(topLevelEquity);
  }
  if (typeof topLevelEquity === "string") {
    return topLevelEquity;
  }
  return "unavailable";
}

function readMaxDrawdown(receipt: Record<string, unknown>): string {
  // ``metrics.max_drawdown_pct`` is a typed percentage: its finite value
  // is displayed with explicit percent units. When it is absent the
  // legacy untyped top-level ``max_drawdown`` fixture value is preserved
  // verbatim — no invented currency/percent units are attached to it —
  // and otherwise the metric is unavailable.
  const metrics = readMetrics(receipt);
  if (metrics !== null) {
    const value = metrics.max_drawdown_pct;
    if (typeof value === "number" && Number.isFinite(value)) {
      return `${value}%`;
    }
  }
  return formatMetric(receipt.max_drawdown);
}

function readBarTs(bar: TraceBar, index: number): string {
  if (typeof bar.bar_ts === "number") {
    return String(bar.bar_ts);
  }
  if (typeof bar.bar_ts === "string") {
    return bar.bar_ts;
  }
  return String(index);
}

function readBarClose(bar: TraceBar): string {
  const close = bar.input?.close;
  if (typeof close === "number") {
    return String(close);
  }
  if (typeof close === "string") {
    return close;
  }
  return "unavailable";
}

function readOutcome(condition: TraceCondition): string {
  const outcome = condition.outcome;
  if (typeof outcome === "boolean") {
    return outcome ? "true" : "false";
  }
  if (typeof outcome === "number") {
    return String(outcome);
  }
  if (typeof outcome === "string") {
    return outcome;
  }
  return "unknown";
}

function readPath(condition: TraceCondition): string {
  const path = condition.path;
  if (typeof path === "string") {
    return path;
  }
  return "";
}

export function ResearchView({
  client,
  revisionId,
}: ResearchViewProps): JSX.Element {
  const [datasetPath, setDatasetPath] = useState("");
  const [packPath, setPackPath] = useState("");
  const [feeBps, setFeeBps] = useState("");
  const [fromMs, setFromMs] = useState("");
  const [toMs, setToMs] = useState("");
  const [holdoutFrom, setHoldoutFrom] = useState("");
  const [holdoutTo, setHoldoutTo] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const jobIdRef = useRef<string | null>(null);
  const [storedResult, setStoredResult] = useState<StoredResult | null>(null);
  const [selectedBarTs, setSelectedBarTs] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [jobError, setJobError] = useState<
    { code: string; message: string } | null
  >(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const handleSyntheticFixture = (): void => {
    setDatasetPath(SYNTHETIC_FIXTURE_PATH);
  };

  const handleRun = async (): Promise<void> => {
    setSubmitError(null);
    setJobError(null);
    setExportError(null);
    setStoredResult(null);
    setSelectedBarTs(null);
    const holdoutFromTrimmed = holdoutFrom.trim();
    const holdoutToTrimmed = holdoutTo.trim();
    const holdoutFromFilled = holdoutFromTrimmed !== "";
    const holdoutToFilled = holdoutToTrimmed !== "";
    if (holdoutFromFilled && !isIntegerString(holdoutFromTrimmed)) {
      setSubmitError("holdout bound must be an integer");
      return;
    }
    if (holdoutToFilled && !isIntegerString(holdoutToTrimmed)) {
      setSubmitError("holdout bound must be an integer");
      return;
    }
    if (holdoutFromFilled !== holdoutToFilled) {
      setSubmitError("holdout bounds must both be set");
      return;
    }
    try {
      const request: Parameters<ResearchClient["submitRun"]>[0] = {
        datasetPath: readStringField(datasetPath),
        feeBps: readNumberField(feeBps),
        fromMs: readNumberField(fromMs),
        toMs: readNumberField(toMs),
      };
      // F4 + W1: when a revision is selected, the request carries the
      // revision and never a non-empty packPath, even if the typed
      // packPath state still holds a stale value.
      if (revisionId) {
        request.revisionId = revisionId;
      } else {
        request.packPath = readStringField(packPath);
      }
      if (holdoutFromFilled) {
        request.holdoutFromMs = Number(holdoutFromTrimmed);
      }
      if (holdoutToFilled) {
        request.holdoutToMs = Number(holdoutToTrimmed);
      }
      const summary = await client.submitRun(request);
      setJobId(summary.id);
      jobIdRef.current = summary.id;
      // Poll for the result so the UI auto-populates when the job
      // succeeds. The brief's e2e path waits for ``research-result``
      // without a manual Load result click; the original Load button
      // is preserved for users who want to refetch.
      void pollForResult(summary.id);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    }
  };

  const pollForResult = async (targetJobId: string): Promise<void> => {
    const intervalMs = 250;
    const deadline = Date.now() + 5 * 60 * 1000;
    while (Date.now() < deadline) {
      if (jobIdRef.current !== targetJobId) {
        return;
      }
      let snap: Awaited<ReturnType<ResearchClient["getJob"]>>;
      try {
        snap = await client.getJob(targetJobId);
      } catch {
        await new Promise((resolve) => setTimeout(resolve, intervalMs));
        continue;
      }
      if (snap === null) {
        await new Promise((resolve) => setTimeout(resolve, intervalMs));
        continue;
      }
      if (snap.state === "succeeded") {
        if (jobIdRef.current !== targetJobId) {
          return;
        }
        const result = await client.getResult(targetJobId);
        if (jobIdRef.current !== targetJobId) {
          return;
        }
        setStoredResult(result);
        return;
      }
      if (snap.state === "failed") {
        if (jobIdRef.current !== targetJobId) {
          return;
        }
        const error = snap.error ?? { code: "job_failed", message: "job failed" };
        setJobError(error);
        return;
      }
      if (snap.state === "cancelled") {
        if (jobIdRef.current !== targetJobId) {
          return;
        }
        setJobError({ code: "cancelled", message: "cancelled" });
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    if (jobIdRef.current === targetJobId) {
      setSubmitError("research job did not produce a result before timeout");
    }
  };

  const handleCancel = async (): Promise<void> => {
    if (!jobId) {
      return;
    }
    await client.cancelJob(jobId);
  };

  const handleLoadResult = async (): Promise<void> => {
    if (!jobId) {
      return;
    }
    const result = await client.getResult(jobId);
    setStoredResult(result);
    setSelectedBarTs(null);
  };

  const handleExport = async (): Promise<void> => {
    if (!jobId) {
      return;
    }
    setExportError(null);
    try {
      const response = await client.getResultDownload(jobId);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `research-receipt-${jobId}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(
        err instanceof Error ? err.message : "export failed",
      );
    }
  };

  const trace: TraceBar[] = storedResult
    ? (storedResult.trace as TraceBar[])
    : [];
  const selectedBar: TraceBar | null =
    selectedBarTs === null
      ? null
      : trace.find((bar) => readBarTs(bar, trace.indexOf(bar)) === selectedBarTs) ??
        null;

  return (
    <section
      className="kbot-research"
      role="region"
      aria-label="Research"
    >
      <h1 className="kbot-shell__heading">Research</h1>
      <div className="kbot-research__form">
        <label className="kbot-research__field" htmlFor="kbot-research-dataset">
          <span className="kbot-research__field-label">Dataset path</span>
          <input
            id="kbot-research-dataset"
            className="kbot-research__input"
            type="text"
            value={datasetPath}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              setDatasetPath(event.target.value)
            }
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <label className="kbot-research__field" htmlFor="kbot-research-pack">
          <span className="kbot-research__field-label">Pack path</span>
          <input
            id="kbot-research-pack"
            className="kbot-research__input"
            type="text"
            value={packPath}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              setPackPath(event.target.value)
            }
            autoComplete="off"
            spellCheck={false}
            disabled={revisionId != null}
          />
        </label>
        {revisionId ? (
          <p
            className="kbot-research__hint"
            data-testid="research-pack-hint"
          >
            Using revision {revisionId}
          </p>
        ) : null}
        {revisionId ? (
          <p className="kbot-research__revision" data-testid="research-revision">
            revision: {revisionId}
          </p>
        ) : null}
        <label className="kbot-research__field" htmlFor="kbot-research-fee-bps">
          <span className="kbot-research__field-label">Fee basis points</span>
          <input
            id="kbot-research-fee-bps"
            className="kbot-research__input"
            type="text"
            value={feeBps}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              setFeeBps(event.target.value)
            }
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <label className="kbot-research__field" htmlFor="kbot-research-from">
          <span className="kbot-research__field-label">From</span>
          <input
            id="kbot-research-from"
            className="kbot-research__input"
            type="text"
            value={fromMs}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              setFromMs(event.target.value)
            }
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <label className="kbot-research__field" htmlFor="kbot-research-to">
          <span className="kbot-research__field-label">To</span>
          <input
            id="kbot-research-to"
            className="kbot-research__input"
            type="text"
            value={toMs}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              setToMs(event.target.value)
            }
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <label className="kbot-research__field" htmlFor="kbot-research-holdout-from">
          <span className="kbot-research__field-label">Holdout from</span>
          <input
            id="kbot-research-holdout-from"
            className="kbot-research__input"
            type="text"
            value={holdoutFrom}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              setHoldoutFrom(event.target.value)
            }
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <label className="kbot-research__field" htmlFor="kbot-research-holdout-to">
          <span className="kbot-research__field-label">Holdout to</span>
          <input
            id="kbot-research-holdout-to"
            className="kbot-research__input"
            type="text"
            value={holdoutTo}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              setHoldoutTo(event.target.value)
            }
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <div className="kbot-research__actions">
          <button
            type="button"
            className="kbot-research__action"
            onClick={handleSyntheticFixture}
          >
            Synthetic fixture
          </button>
          <button
            type="button"
            className="kbot-research__action"
            onClick={() => {
              void handleRun();
            }}
          >
            Run
          </button>
          {jobId ? (
            <button
              type="button"
              className="kbot-research__action"
              onClick={() => {
                void handleCancel();
              }}
            >
              Cancel
            </button>
          ) : null}
          {jobId ? (
            <button
              type="button"
              className="kbot-research__action"
              onClick={() => {
                void handleLoadResult();
              }}
            >
              Load result
            </button>
          ) : null}
        </div>
        {submitError ? (
          <p className="kbot-research__error" role="alert">
            {submitError}
          </p>
        ) : null}
        {jobId ? (
          <p
            className="kbot-research__job"
            data-testid="research-job-id"
          >
            job: {jobId}
          </p>
        ) : null}
      </div>
      {storedResult ? (
        <ResultPanel
          receipt={storedResult.legacy_receipt}
          trace={trace}
          selectedBarTs={selectedBarTs}
          onSelectBar={setSelectedBarTs}
          selectedBar={selectedBar}
        />
      ) : null}
      {storedResult ? (
        <button
          type="button"
          className="kbot-research__action"
          onClick={() => {
            void handleExport();
          }}
        >
          Export result
        </button>
      ) : null}
      {exportError ? (
        <p
          className="kbot-research__error"
          role="alert"
          data-testid="research-export-error"
        >
          {exportError}
        </p>
      ) : null}
      {jobError ? (
        <p
          className="kbot-research__error"
          role="alert"
          data-testid="research-job-error"
        >
          {jobError.code}: {jobError.message}
        </p>
      ) : null}
      {storedResult ? (
        <pre
          className="kbot-research__export"
          data-testid="research-export"
        >
          {JSON.stringify(storedResult)}
        </pre>
      ) : null}
    </section>
  );
}

type ResultPanelProps = {
  receipt: Record<string, unknown>;
  trace: TraceBar[];
  selectedBarTs: string | null;
  onSelectBar: (barTs: string) => void;
  selectedBar: TraceBar | null;
};

function ResultPanel({
  receipt,
  trace,
  selectedBarTs,
  onSelectBar,
  selectedBar,
}: ResultPanelProps): JSX.Element {
  return (
    <div className="kbot-research__result" data-testid="research-result">
      <dl className="kbot-research__metrics">
        <div className="kbot-research__metric">
          <dt className="kbot-research__metric-label">Equity</dt>
          <dd
            className="kbot-research__metric-value"
            data-testid="research-result-equity"
          >
            {readEquity(receipt)}
          </dd>
        </div>
        <div className="kbot-research__metric">
          <dt className="kbot-research__metric-label">Max drawdown</dt>
          <dd
            className="kbot-research__metric-value"
            data-testid="research-result-max-drawdown"
          >
            {readMaxDrawdown(receipt)}
          </dd>
        </div>
        <div className="kbot-research__metric">
          <dt className="kbot-research__metric-label">Total return (%)</dt>
          <dd
            className="kbot-research__metric-value"
            data-testid="research-result-total-return-pct"
          >
            {readPercentageMetric(receipt, "total_return_pct")}
          </dd>
        </div>
        <div className="kbot-research__metric">
          <dt className="kbot-research__metric-label">Fee basis points</dt>
          <dd
            className="kbot-research__metric-value"
            data-testid="research-result-fee-bps"
          >
            {formatMetric(receipt.fee_bps)}
          </dd>
        </div>
        <div className="kbot-research__metric">
          <dt className="kbot-research__metric-label">Trade count</dt>
          <dd
            className="kbot-research__metric-value"
            data-testid="research-result-trade-count"
          >
            {readTradeCount(receipt)}
          </dd>
        </div>
        <div className="kbot-research__metric">
          <dt className="kbot-research__metric-label">Data manifest sha256</dt>
          <dd
            className="kbot-research__metric-value"
            data-testid="research-result-data-manifest-sha256"
          >
            {formatMetric(receipt.data_manifest_sha256)}
          </dd>
        </div>
      </dl>
      <div className="kbot-research__trace" data-testid="research-trace">
        <h2 className="kbot-research__trace-title">Trace</h2>
        <TraceList
          trace={trace}
          selectedBarTs={selectedBarTs}
          onSelectBar={onSelectBar}
        />
        {selectedBar ? (
          <div
            className="kbot-research__bar-detail"
            data-testid="research-bar-detail"
          >
            <p className="kbot-research__bar-close">
              close: {readBarClose(selectedBar)}
            </p>
            <ul className="kbot-research__conditions">
              {(selectedBar.conditions ?? []).map((condition, index) => (
                <li
                  key={`cond-${index}`}
                  className="kbot-research__condition"
                >
                  {readPath(condition)}: {readOutcome(condition)}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}

type TraceListProps = {
  trace: TraceBar[];
  selectedBarTs: string | null;
  onSelectBar: (barTs: string) => void;
};

/**
 * Windowed trace list: a fixed-height scroll container with a tall
 * spacer behind a small slice of visible rows. The scroll handler
 * recomputes the start/end indices and React re-mounts only the
 * mounted rows; everything outside the slice is unmounted. No new
 * runtime dependency is required.
 */
function TraceList({
  trace,
  selectedBarTs,
  onSelectBar,
}: TraceListProps): JSX.Element {
  const total = trace.length;
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(TRACE_VIEWPORT_HEIGHT);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) {
      return;
    }
    const update = (): void => {
      setViewportHeight(node.clientHeight || TRACE_VIEWPORT_HEIGHT);
    };
    update();
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(update);
      observer.observe(node);
      return () => {
        observer.disconnect();
      };
    }
    return undefined;
  }, []);

  const visibleCount = Math.max(
    1,
    Math.ceil(viewportHeight / TRACE_ROW_HEIGHT) + 1,
  );
  const startIndex = Math.max(
    0,
    Math.floor(scrollTop / TRACE_ROW_HEIGHT) - TRACE_OVERSCAN_ROWS,
  );
  const endIndex = Math.min(
    total,
    startIndex + visibleCount + TRACE_OVERSCAN_ROWS * 2,
  );
  const slice = useMemo(
    () => trace.slice(startIndex, endIndex),
    [trace, startIndex, endIndex],
  );

  const handleScroll = (event: React.UIEvent<HTMLDivElement>): void => {
    setScrollTop(event.currentTarget.scrollTop);
  };

  const totalHeight = total * TRACE_ROW_HEIGHT;

  return (
    <>
      <p className="kbot-research__trace-count" data-testid="research-trace-count">
        {total}
      </p>
      <div
        className="kbot-research__trace-scroll"
        data-testid="research-trace-scroll"
        ref={scrollRef}
        onScroll={handleScroll}
        style={{
          height: TRACE_VIEWPORT_HEIGHT,
          overflowY: "auto",
          border: "1px solid var(--kbot-border, #ccc)",
          position: "relative",
        }}
      >
        <div
          aria-hidden="true"
          style={{
            height: totalHeight,
            pointerEvents: "none",
          }}
        />
        <div
          style={{
            position: "absolute",
            top: startIndex * TRACE_ROW_HEIGHT,
            left: 0,
            right: 0,
          }}
        >
          {slice.map((bar, offset) => {
            const index = startIndex + offset;
            const label = readBarTs(bar, index);
            const active = label === selectedBarTs;
            return (
              <button
                key={`bar-${label}-${index}`}
                type="button"
                className={
                  "kbot-research__trace-button" +
                  (active ? " kbot-research__trace-button--active" : "")
                }
                aria-pressed={active}
                onClick={() => onSelectBar(label)}
                style={{
                  display: "block",
                  width: "100%",
                  height: TRACE_ROW_HEIGHT,
                  textAlign: "left",
                  padding: "0 8px",
                  border: "none",
                  background: active ? "#eef" : "transparent",
                  cursor: "pointer",
                  boxSizing: "border-box",
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>
    </>
  );
}