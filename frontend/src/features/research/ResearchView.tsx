import { useState, type JSX } from "react";
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
  const trades = receipt.trades;
  if (Array.isArray(trades)) {
    return String(trades.length);
  }
  return "unavailable";
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
  const [storedResult, setStoredResult] = useState<StoredResult | null>(null);
  const [selectedBarTs, setSelectedBarTs] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const handleSyntheticFixture = (): void => {
    setDatasetPath(SYNTHETIC_FIXTURE_PATH);
  };

  const handleRun = async (): Promise<void> => {
    setSubmitError(null);
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
        packPath: readStringField(packPath),
      };
      if (revisionId && packPath.trim() === "") {
        request.revisionId = revisionId;
      }
      if (holdoutFromFilled) {
        request.holdoutFromMs = Number(holdoutFromTrimmed);
      }
      if (holdoutToFilled) {
        request.holdoutToMs = Number(holdoutToTrimmed);
      }
      const summary = await client.submitRun(request);
      setJobId(summary.id);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
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
            onChange={(event) => setDatasetPath(event.target.value)}
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
            onChange={(event) => setPackPath(event.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
        </label>
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
            onChange={(event) => setFeeBps(event.target.value)}
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
            onChange={(event) => setFromMs(event.target.value)}
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
            onChange={(event) => setToMs(event.target.value)}
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
            onChange={(event) => setHoldoutFrom(event.target.value)}
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
            onChange={(event) => setHoldoutTo(event.target.value)}
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
            const blob = new Blob([JSON.stringify(storedResult)], {
              type: "application/json",
            });
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement("a");
            anchor.href = url;
            anchor.download = "research-result.json";
            document.body.appendChild(anchor);
            anchor.click();
            document.body.removeChild(anchor);
          }}
        >
          Export result
        </button>
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
            {formatMetric(receipt.equity)}
          </dd>
        </div>
        <div className="kbot-research__metric">
          <dt className="kbot-research__metric-label">Max drawdown</dt>
          <dd
            className="kbot-research__metric-value"
            data-testid="research-result-max-drawdown"
          >
            {formatMetric(receipt.max_drawdown)}
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
        <div className="kbot-research__trace-buttons">
          {trace.map((bar, index) => {
            const label = readBarTs(bar, index);
            const active = label === selectedBarTs;
            return (
              <button
                key={`bar-${label}`}
                type="button"
                className={
                  "kbot-research__trace-button" +
                  (active ? " kbot-research__trace-button--active" : "")
                }
                aria-pressed={active}
                onClick={() => onSelectBar(label)}
              >
                {label}
              </button>
            );
          })}
        </div>
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
