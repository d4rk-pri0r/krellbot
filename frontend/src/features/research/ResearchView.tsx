import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type JSX,
} from "react";
import type { ResearchClient, StoredResult } from "./client";
import { ResearchDateWindow, utcFieldValueToMs } from "./ResearchDateWindow";
import { TraceCsvExport } from "./TraceCsvExport";
import { summarizeResearchJobError } from "./researchJobErrorLabel";
import "./ResearchView.signal.css";
import "./ResearchView.local-preview.signal.css";

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

type MetricCell = {
  label: string;
  testId: string;
  value: string;
  source: string;
};

const SYNTHETIC_FIXTURE_PATH = "fixtures/synthetic.csv";

const TRACE_ROW_HEIGHT = 24;
const TRACE_OVERSCAN_ROWS = 8;
const TRACE_VIEWPORT_HEIGHT = 480;

/** Truthful placeholder for an unset in-use/config value. */
const NOT_SET = "not set";

const EMPTY_STATE_COPY =
  "No research run yet. Submit a window to populate this view.";
const LOCAL_PREVIEW_COPY = "Local preview only — live trading unavailable";
const SUBMITTING_STATE_COPY = "Submitting research run…";
const SUBMIT_FAILED_COPY =
  "Could not submit research run — check the workstation is running.";

/**
 * KRELL-SIGNAL-20261010 research presentation. Every metric cell names the
 * real receipt field it reads and its unit, so a reader can tell a
 * percentage return from currency equity and an unavailable value from a
 * real zero. Values come from the existing receipt readers unchanged.
 */
function buildMetricCells(receipt: Record<string, unknown>): MetricCell[] {
  const equity = readEquity(receipt);
  const maxDrawdown = readMaxDrawdown(receipt);
  const totalReturn = readPercentageMetric(receipt, "total_return_pct");
  const feeBps = formatMetric(receipt.fee_bps);
  const tradeCount = readTradeCount(receipt);
  const manifest = formatMetric(receipt.data_manifest_sha256);
  return [
    {
      label: "Equity",
      testId: "research-result-equity",
      value: equity,
      source: "receipt.equity · currency, absent in production receipts",
    },
    {
      label: "Max drawdown",
      testId: "research-result-max-drawdown",
      value: maxDrawdown,
      source: "metrics.max_drawdown_pct · percent",
    },
    {
      label: "Total return (%)",
      testId: "research-result-total-return-pct",
      value: totalReturn,
      source: "metrics.total_return_pct · percent",
    },
    {
      label: "Fee basis points",
      testId: "research-result-fee-bps",
      value: feeBps,
      source: "receipt.fee_bps · basis points",
    },
    {
      label: "Trade count",
      testId: "research-result-trade-count",
      value: tradeCount,
      source: "metrics.trade_count / trades · count",
    },
    {
      label: "Data manifest sha256",
      testId: "research-result-data-manifest-sha256",
      value: manifest,
      source: "receipt.data_manifest_sha256 · sha256",
    },
  ];
}

function readStringField(value: string): string {
  return value;
}

function isIntegerString(value: string): boolean {
  return /^-?\d+$/.test(value);
}

/**
 * BUILD-RESEARCH-INPUTS-01: parse a REQUIRED integer setup field.
 * Blank, malformed, fractional, non-finite and unsafe-integer input
 * is refused — never silently coerced to zero, truncated or rounded.
 * The caller supplies the field-naming error text so the visible
 * alert always names the affected field.
 */
function parseRequiredIntegerField(
  raw: string,
  errorText: string,
): { ok: true; value: number } | { ok: false; error: string } {
  const trimmed = raw.trim();
  if (!isIntegerString(trimmed)) {
    return { ok: false, error: errorText };
  }
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || !Number.isSafeInteger(parsed)) {
    return { ok: false, error: errorText };
  }
  return { ok: true, value: parsed };
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
  // UTC date/time mirror state for the scored window and holdout bounds.
  // ``editedUtcLast`` records which control drove the current value so a
  // controlled edit in either direction is echoed losslessly into the
  // other without a feedback loop or a silent reformat.
  const [fromUtc, setFromUtc] = useState("");
  const [toUtc, setToUtc] = useState("");
  const [holdoutFromUtc, setHoldoutFromUtc] = useState("");
  const [holdoutToUtc, setHoldoutToUtc] = useState("");
  const [fromEditedUtcLast, setFromEditedUtcLast] = useState(false);
  const [toEditedUtcLast, setToEditedUtcLast] = useState(false);
  const [holdoutFromEditedUtcLast, setHoldoutFromEditedUtcLast] = useState(false);
  const [holdoutToEditedUtcLast, setHoldoutToEditedUtcLast] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const jobIdRef = useRef<string | null>(null);
  const [storedResult, setStoredResult] = useState<StoredResult | null>(null);
  const [selectedBarTs, setSelectedBarTs] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // Honest-state tracking for the result area. ``submitting`` covers only
  // the in-flight client.submitRun call; ``submitFailed`` is set only when
  // that call rejects, so setup-validation refusals (which keep the real
  // field-naming alert) are never mislabeled as a workstation failure.
  const [submitting, setSubmitting] = useState(false);
  const [submitFailed, setSubmitFailed] = useState(false);
  const [jobError, setJobError] = useState<
    { code: string; message: string } | null
  >(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const handleSyntheticFixture = (): void => {
    setDatasetPath(SYNTHETIC_FIXTURE_PATH);
  };

  // UTC date/time <-> exact millisecond echoing. Each bound keeps a single
  // source of truth: when the UTC control was edited last it owns the value
  // and the advanced field shows its exact integer milliseconds (or is
  // cleared when the text is not yet a valid UTC instant); when the advanced
  // field was edited last it owns the value and the UTC control shows the
  // exact UTC instant. No local-timezone conversion is ever applied.
  const handleFromUtcChange = (text: string): void => {
    setFromUtc(text);
    setFromEditedUtcLast(true);
    const ms = utcFieldValueToMs(text);
    setFromMs(ms === null ? "" : String(ms));
  };
  const handleToUtcChange = (text: string): void => {
    setToUtc(text);
    setToEditedUtcLast(true);
    const ms = utcFieldValueToMs(text);
    setToMs(ms === null ? "" : String(ms));
  };
  const handleHoldoutFromUtcChange = (text: string): void => {
    setHoldoutFromUtc(text);
    setHoldoutFromEditedUtcLast(true);
    const ms = utcFieldValueToMs(text);
    setHoldoutFrom(ms === null ? "" : String(ms));
  };
  const handleHoldoutToUtcChange = (text: string): void => {
    setHoldoutToUtc(text);
    setHoldoutToEditedUtcLast(true);
    const ms = utcFieldValueToMs(text);
    setHoldoutTo(ms === null ? "" : String(ms));
  };

  const handleRun = async (): Promise<void> => {
    // BUILD-RESEARCH-INPUTS-01: validate the required fee/date setup
    // fields BEFORE clearing any current result/selection. A refused
    // setup must not submit a job, fabricate a job id, or discard the
    // current job identity/result/decision/export.
    const feeField = parseRequiredIntegerField(
      feeBps,
      "Fee basis points must be a nonnegative integer",
    );
    if (!feeField.ok) {
      setSubmitError(feeField.error);
      return;
    }
    const feeBpsValue = feeField.value;
    if (feeBpsValue < 0) {
      setSubmitError("Fee basis points must be a nonnegative integer");
      return;
    }
    const fromField = parseRequiredIntegerField(
      fromMs,
      "From must be an integer timestamp",
    );
    if (!fromField.ok) {
      setSubmitError(fromField.error);
      return;
    }
    const toField = parseRequiredIntegerField(
      toMs,
      "To must be an integer timestamp",
    );
    if (!toField.ok) {
      setSubmitError(toField.error);
      return;
    }
    if (fromField.value > toField.value) {
      setSubmitError(
        "From must be less than or equal to To for the inclusive scored window",
      );
      return;
    }
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
    setSubmitError(null);
    setJobError(null);
    setExportError(null);
    setStoredResult(null);
    setSelectedBarTs(null);
    try {
      const request: Parameters<ResearchClient["submitRun"]>[0] = {
        datasetPath: readStringField(datasetPath),
        feeBps: feeBpsValue,
        fromMs: fromField.value,
        toMs: toField.value,
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
      setSubmitting(true);
      setSubmitFailed(false);
      try {
        const summary = await client.submitRun(request);
        setJobId(summary.id);
        jobIdRef.current = summary.id;
        // Poll for the result so the UI auto-populates when the job
        // succeeds. The brief's e2e path waits for ``research-result``
        // without a manual Load result click; the original Load button
        // is preserved for users who want to refetch.
        void pollForResult(summary.id);
      } finally {
        setSubmitting(false);
      }
    } catch (err) {
      setSubmitFailed(true);
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
    setCancelError(null);
    try {
      await client.cancelJob(jobId);
      setJobId(null);
    } catch (err) {
      setCancelError(
        `Cancel job failed: ${err instanceof Error ? err.message : String(err)} — outcome unknown: the command may not have been sent or applied — check state before retrying`,
      );
    }
  };

  const handleLoadResult = async (): Promise<void> => {
    setLoadError(null);
    if (!jobId) {
      return;
    }
    try {
      const result = await client.getResult(jobId);
      setStoredResult(result);
      setSelectedBarTs(null);
    } catch (err) {
      setLoadError(
        `Load result failed: ${err instanceof Error ? err.message : String(err)} — outcome unknown: the command may not have been sent or applied — check state before retrying`,
      );
    }
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

  // In-use strip: a truthful echo of what the NEXT Run submits — the exact
  // current field texts, never a reformatted or inferred configuration.
  const inUseStrategy = revisionId
    ? `revision ${revisionId}`
    : packPath.trim() === ""
      ? NOT_SET
      : packPath;
  const inUseDataset = datasetPath.trim() === "" ? NOT_SET : datasetPath;
  const inUseFee = feeBps.trim() === "" ? NOT_SET : feeBps.trim();
  const inUseWindow =
    fromMs.trim() === "" || toMs.trim() === ""
      ? NOT_SET
      : `${fromMs.trim()} → ${toMs.trim()}`;
  const inUseHoldout =
    holdoutFrom.trim() === "" && holdoutTo.trim() === ""
      ? NOT_SET
      : `${holdoutFrom.trim() || "…"} → ${holdoutTo.trim() || "…"}`;

  return (
    <section
      className="kbot-research"
      role="region"
      aria-label="Research"
    >
      <h1 className="kbot-shell__heading">Research</h1>
      <div className="kbot-research__intro">
        <p>
          Configure a backtest, run it against the local engine, then read the
          stored receipt and inspect or export its trace. Results come only
          from completed research jobs; nothing here is a live trading result.
        </p>
      </div>

      <div className="kbot-research__setup">
        <section
          className="kbot-research__panel"
          data-testid="research-setup-panel-strategy"
          aria-labelledby="kbot-research-panel-strategy-title"
        >
          <h2
            className="kbot-research__panel-title"
            id="kbot-research-panel-strategy-title"
          >
            Strategy source
          </h2>
          <p className="kbot-research__panel-note">
            A saved strategy revision, or a pack file on disk when no revision
            is selected.
          </p>
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
        </section>

        <section
          className="kbot-research__panel"
          data-testid="research-setup-panel-data"
          aria-labelledby="kbot-research-panel-data-title"
        >
          <h2
            className="kbot-research__panel-title"
            id="kbot-research-panel-data-title"
          >
            Data source
          </h2>
          <p className="kbot-research__panel-note">
            Path to a local candle CSV the engine will read for this run.
          </p>
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
          <div>
            <button
              type="button"
              className="kbot-research__action"
              onClick={handleSyntheticFixture}
            >
              Synthetic fixture
            </button>
          </div>
        </section>

        <section
          className="kbot-research__panel"
          data-testid="research-setup-panel-window"
          aria-labelledby="kbot-research-panel-window-title"
        >
          <h2
            className="kbot-research__panel-title"
            id="kbot-research-panel-window-title"
          >
            Scored window &amp; holdout
          </h2>
          <p className="kbot-research__panel-note">
            Exact epoch-millisecond bounds submitted to the engine. Holdout
            bounds are optional but must be set as a pair.
          </p>
          <div className="kbot-research__window-grid">
            <div className="kbot-research__window-ms">
              <label className="kbot-research__field" htmlFor="kbot-research-from">
                <span className="kbot-research__field-label">From</span>
                <input
                  id="kbot-research-from"
                  className="kbot-research__input"
                  type="text"
                  value={fromMs}
                  onChange={(event: ChangeEvent<HTMLInputElement>) => {
                    setFromMs(event.target.value);
                    setFromEditedUtcLast(false);
                  }}
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
                  onChange={(event: ChangeEvent<HTMLInputElement>) => {
                    setToMs(event.target.value);
                    setToEditedUtcLast(false);
                  }}
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
              <label
                className="kbot-research__field"
                htmlFor="kbot-research-holdout-from"
              >
                <span className="kbot-research__field-label">Holdout from</span>
                <input
                  id="kbot-research-holdout-from"
                  className="kbot-research__input"
                  type="text"
                  value={holdoutFrom}
                  onChange={(event: ChangeEvent<HTMLInputElement>) => {
                    setHoldoutFrom(event.target.value);
                    setHoldoutFromEditedUtcLast(false);
                  }}
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
              <label
                className="kbot-research__field"
                htmlFor="kbot-research-holdout-to"
              >
                <span className="kbot-research__field-label">Holdout to</span>
                <input
                  id="kbot-research-holdout-to"
                  className="kbot-research__input"
                  type="text"
                  value={holdoutTo}
                  onChange={(event: ChangeEvent<HTMLInputElement>) => {
                    setHoldoutTo(event.target.value);
                    setHoldoutToEditedUtcLast(false);
                  }}
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
            </div>
            <ResearchDateWindow
              fromMsText={fromMs}
              toMsText={toMs}
              holdoutFromMsText={holdoutFrom}
              holdoutToMsText={holdoutTo}
              fromUtcText={fromUtc}
              toUtcText={toUtc}
              holdoutFromUtcText={holdoutFromUtc}
              holdoutToUtcText={holdoutToUtc}
              fromEditedUtcLast={fromEditedUtcLast}
              toEditedUtcLast={toEditedUtcLast}
              holdoutFromEditedUtcLast={holdoutFromEditedUtcLast}
              holdoutToEditedUtcLast={holdoutToEditedUtcLast}
              onFromUtcChange={handleFromUtcChange}
              onToUtcChange={handleToUtcChange}
              onHoldoutFromUtcChange={handleHoldoutFromUtcChange}
              onHoldoutToUtcChange={handleHoldoutToUtcChange}
            />
          </div>
        </section>

        <section
          className="kbot-research__panel"
          data-testid="research-setup-panel-costs"
          aria-labelledby="kbot-research-panel-costs-title"
        >
          <h2
            className="kbot-research__panel-title"
            id="kbot-research-panel-costs-title"
          >
            Costs
          </h2>
          <p className="kbot-research__panel-note">
            Fee assumption applied by the engine, in basis points per side.
          </p>
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
        </section>
      </div>

      <div
        className="kbot-research__inuse"
        data-testid="research-inuse"
        aria-label="Configuration in use for the next run"
      >
        <div className="kbot-research__inuse-item">
          <span className="kbot-research__inuse-label">Strategy</span>
          <span className="kbot-research__inuse-value" data-testid="research-inuse-strategy">
            {inUseStrategy}
          </span>
        </div>
        <div className="kbot-research__inuse-item">
          <span className="kbot-research__inuse-label">Data</span>
          <span className="kbot-research__inuse-value" data-testid="research-inuse-dataset">
            {inUseDataset}
          </span>
        </div>
        <div className="kbot-research__inuse-item">
          <span className="kbot-research__inuse-label">Window (ms)</span>
          <span className="kbot-research__inuse-value" data-testid="research-inuse-window">
            {inUseWindow}
          </span>
        </div>
        <div className="kbot-research__inuse-item">
          <span className="kbot-research__inuse-label">Holdout (ms)</span>
          <span className="kbot-research__inuse-value" data-testid="research-inuse-holdout">
            {inUseHoldout}
          </span>
        </div>
        <div className="kbot-research__inuse-item">
          <span className="kbot-research__inuse-label">Fee (bps)</span>
          <span className="kbot-research__inuse-value" data-testid="research-inuse-fee">
            {inUseFee}
          </span>
        </div>
      </div>

      <div className="kbot-research__runbar" data-testid="research-runbar">
        <button
          type="button"
          className="kbot-research__action kbot-research__action--primary"
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
            data-testid="research-cancel"
            onClick={() => {
              void handleCancel();
            }}
          >
            Cancel
          </button>
        ) : null}
        {cancelError ? (
          <p className="kbot-research__error" data-testid="research-cancel-error" role="alert">
            {cancelError}
          </p>
        ) : null}
        {loadError !== null ? (
          <p className="kbot-research__error" data-testid="research-load-result-error" role="alert">
            {loadError}
          </p>
        ) : null}
        {jobId ? (
          <button
            type="button"
            className="kbot-research__action"
            data-testid="research-load-result"
            onClick={() => {
              void handleLoadResult();
            }}
          >
            Load result
          </button>
        ) : null}
        {jobId ? (
          <p
            className="kbot-research__job"
            data-testid="research-job-id"
          >
            <b>job</b> {jobId}
          </p>
        ) : null}
        {jobId && storedResult === null && jobError === null ? (
          <p className="kbot-research__status" data-testid="research-job-status">
            <span className="kbot-research__status-dot" aria-hidden="true" />
            Waiting for the job result…
          </p>
        ) : null}
      </div>

      {submitError ? (
        <p className="kbot-research__error" role="alert">
          {submitError}
        </p>
      ) : null}

      {storedResult ? null : submitting ? (
        <div
          className="kbot-research__state kbot-research__state--submitting"
          data-testid="research-state-submitting"
          role="status"
        >
          <span className="kbot-research__status-dot" aria-hidden="true" />
          <p className="kbot-research__state-copy">{SUBMITTING_STATE_COPY}</p>
        </div>
      ) : submitFailed ? (
        <div
          className="kbot-research__state kbot-research__state--error"
          data-testid="research-state-error"
        >
          <p className="kbot-research__state-copy">
            {SUBMIT_FAILED_COPY}
            {submitError ? (
              <span
                className="kbot-research__state-detail"
                data-testid="research-state-error-detail"
              >
                {submitError}
              </span>
            ) : null}
          </p>
          <button
            type="button"
            className="kbot-research__action"
            data-testid="research-submit-retry"
            onClick={() => {
              void handleRun();
            }}
          >
            Retry
          </button>
        </div>
      ) : jobId === null ? (
        <div
          className="kbot-research__state kbot-research__state--empty"
          data-testid="research-state-empty"
        >
          <p className="kbot-research__state-copy">{EMPTY_STATE_COPY}</p>
          <p
            className="kbot-research__local-preview"
            data-testid="research-local-preview"
          >
            {LOCAL_PREVIEW_COPY}
          </p>
        </div>
      ) : null}

      {storedResult ? (
        <ResultPanel
          receipt={storedResult.legacy_receipt}
          trace={trace}
          jobId={jobId}
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
          {summarizeResearchJobError(jobError).label}: {jobError.message}
        </p>
      ) : null}

      {storedResult ? (
        <details
          className="kbot-research__receipt"
          data-testid="research-receipt-detail"
        >
          <summary>Raw stored result (JSON, exactly as stored)</summary>
          <pre
            className="kbot-research__export"
            data-testid="research-export"
          >
            {JSON.stringify(storedResult)}
          </pre>
        </details>
      ) : null}
    </section>
  );
}

type ResultPanelProps = {
  receipt: Record<string, unknown>;
  trace: TraceBar[];
  jobId: string | null;
  selectedBarTs: string | null;
  onSelectBar: (barTs: string) => void;
  selectedBar: TraceBar | null;
};

function ResultPanel({
  receipt,
  trace,
  jobId,
  selectedBarTs,
  onSelectBar,
  selectedBar,
}: ResultPanelProps): JSX.Element {
  const metrics = buildMetricCells(receipt);
  // Result provenance: only what the stored receipt itself carries plus the
  // job identity it was loaded under — never the (editable) setup fields.
  const provenance: Array<{ label: string; value: string; testId: string }> = [
    {
      label: "Job",
      value: jobId ?? "unavailable",
      testId: "research-result-context-job",
    },
    {
      label: "Fee (bps)",
      value: formatMetric(receipt.fee_bps),
      testId: "research-result-context-fee",
    },
    {
      label: "Data manifest sha256",
      value: formatMetric(receipt.data_manifest_sha256),
      testId: "research-result-context-sha",
    },
  ];
  return (
    <div className="kbot-research__result" data-testid="research-result">
      <div
        className="kbot-research__result-context"
        data-testid="research-result-context"
        aria-label="Result provenance"
      >
        {provenance.map((item) => (
          <div className="kbot-research__result-context-item" key={item.testId}>
            <span className="kbot-research__result-context-label">
              {item.label}
            </span>
            <span
              className="kbot-research__result-context-value"
              data-testid={item.testId}
            >
              {item.value}
            </span>
          </div>
        ))}
      </div>
      <dl className="kbot-research__metrics">
        {metrics.map((metric) => (
          <div
            className={
              "kbot-research__metric" +
              (metric.value === "unavailable"
                ? " kbot-research__metric--unavailable"
                : "")
            }
            key={metric.testId}
          >
            <dt className="kbot-research__metric-label">{metric.label}</dt>
            <dd
              className="kbot-research__metric-value"
              data-testid={metric.testId}
            >
              {metric.value}
            </dd>
            <dd className="kbot-research__metric-source">{metric.source}</dd>
          </div>
        ))}
      </dl>
      <div className="kbot-research__trace" data-testid="research-trace">
        <div className="kbot-research__trace-head">
          <h2 className="kbot-research__trace-title">Trace</h2>
          <TraceCsvExport
            trace={trace as Array<Record<string, unknown>>}
            jobId={jobId}
          />
        </div>
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
            <p className="kbot-research__bar-detail-title">
              Selected bar detail
            </p>
            <p className="kbot-research__bar-close">
              close: {readBarClose(selectedBar)}
            </p>
            <ul className="kbot-research__conditions">
              {(selectedBar.conditions ?? []).map((condition, index) => {
                const outcome = readOutcome(condition);
                return (
                  <li
                    key={`cond-${index}`}
                    className="kbot-research__condition"
                  >
                    <span className="kbot-research__condition-path">
                      {readPath(condition)}
                    </span>
                    <span
                      className={
                        "kbot-research__condition-outcome" +
                        ` kbot-research__condition-outcome--${outcome}`
                      }
                    >
                      {outcome}
                    </span>
                  </li>
                );
              })}
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
  const rowRefs = useRef(new Map<number, HTMLButtonElement>());
  const pendingFocus = useRef<number | null>(null);
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

  useLayoutEffect(() => {
    const target = pendingFocus.current;
    if (target === null) return;
    const row = rowRefs.current.get(target);
    if (row) {
      row.focus({ preventScroll: true });
      pendingFocus.current = null;
    }
  });

  const handleRowKeyDown = (
    event: React.KeyboardEvent<HTMLButtonElement>,
    index: number,
  ): void => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    let target: number;
    switch (event.key) {
      case "ArrowUp":
        target = Math.max(0, index - 1);
        break;
      case "ArrowDown":
        target = Math.min(total - 1, index + 1);
        break;
      case "Home":
        target = 0;
        break;
      case "End":
        target = total - 1;
        break;
      default:
        return;
    }
    const node = scrollRef.current;
    if (!node) return;
    event.preventDefault();
    const height = node.clientHeight || viewportHeight;
    const top = target * TRACE_ROW_HEIGHT;
    const bottom = top + TRACE_ROW_HEIGHT;
    const alignedTop = top < node.scrollTop
      ? top
      : bottom > node.scrollTop + height ? bottom - height : node.scrollTop;
    node.scrollTop = Math.max(0, Math.min(alignedTop, total * TRACE_ROW_HEIGHT - height));
    pendingFocus.current = target;
    setScrollTop(node.scrollTop);
    // Already-mounted targets need no render; other targets focus after commit.
    const row = rowRefs.current.get(target);
    if (row) {
      row.focus({ preventScroll: true });
      pendingFocus.current = null;
    }
  };

  const totalHeight = total * TRACE_ROW_HEIGHT;

  return (
    <>
      <p
        className="kbot-research__trace-count"
        data-testid="research-trace-count"
        aria-label="Trace rows in this result"
      >
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
                ref={(node) => {
                  if (node) rowRefs.current.set(index, node);
                  else rowRefs.current.delete(index);
                }}
                onKeyDown={(event) => handleRowKeyDown(event, index)}
                onClick={() => onSelectBar(label)}
                /* Inline height stays the geometry source of truth; it must
                   equal TRACE_ROW_HEIGHT and the CSS row rule. */
                style={{
                  height: TRACE_ROW_HEIGHT,
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