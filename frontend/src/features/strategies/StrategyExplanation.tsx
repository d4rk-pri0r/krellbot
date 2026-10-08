import { useMemo, type JSX } from "react";
import {
  explainPack,
  NOT_SUPPLIED,
  type ConditionExplanation,
  type ExplainResult,
} from "./explainPack";

export type StrategyExplanationProps = {
  /** Stored revision bytes, exactly as saved/imported. */
  bytes: string;
  /** Saved revision id, or null when nothing has been saved yet. */
  revisionId: string | null;
};

function ConditionList({ condition }: { condition: ConditionExplanation }): JSX.Element {
  if (condition.kind === "group") {
    return (
      <>
        <li>
          {condition.joiner === "all"
            ? "All of these are true:"
            : "Any of these is true:"}
        </li>
        {condition.children.map((child, index) => (
          <ConditionList key={index} condition={child} />
        ))}
      </>
    );
  }
  return <li>{condition.text}</li>;
}

function MetadataRow({ label, value }: { label: string; value: string | null }): JSX.Element {
  return (
    <p>
      {label}: {value ?? NOT_SUPPLIED}
    </p>
  );
}

export function StrategyExplanation({
  bytes,
  revisionId,
}: StrategyExplanationProps): JSX.Element {
  const explanation = useMemo<ExplainResult>(
    () => explainPack(bytes, revisionId),
    [bytes, revisionId],
  );

  const savedLabel =
    explanation.savedStatus === "saved"
      ? `Saved revision ${explanation.revisionId}`
      : "No saved revision yet (showing stored draft content as unsaved)";

  return (
    <section
      role="region"
      aria-label="Strategy explanation"
      data-testid="strategy-explanation"
    >
      <header>
        <h3>What this revision trades</h3>
        <p data-testid="strategy-explanation-revision">{savedLabel}</p>
      </header>

      {!explanation.parsed ? (
        <p role="status" data-testid="strategy-explanation-unparsed">
          The saved content is not readable JSON, so its rules cannot be explained
          here. Nothing about it is assumed or invented.
        </p>
      ) : (
        <>
          <h4>Stored details (as supplied, not verified)</h4>
          <div data-testid="strategy-explanation-metadata">
            <MetadataRow label="Label" value={explanation.metadata.label} />
            <MetadataRow label="Pack id" value={explanation.metadata.packId} />
            <MetadataRow label="Version" value={explanation.metadata.version} />
            <MetadataRow label="Author" value={explanation.metadata.author} />
            <MetadataRow label="Origin" value={explanation.metadata.origin} />
            <MetadataRow label="Timeframe" value={explanation.timeframe.text} />
          </div>

          <h4>Indicators</h4>
          <ul data-testid="strategy-explanation-indicators">
            {explanation.indicators.map((indicator, index) => (
              <li
                key={indicator.name || `unknown-${index}`}
                data-supported={indicator.supported ? "1" : "0"}
              >
                {indicator.text}
              </li>
            ))}
          </ul>

          <h4>When it enters</h4>
          <ul data-testid="strategy-explanation-entry">
            <ConditionList condition={explanation.entry} />
          </ul>

          <h4>When it exits</h4>
          <ul data-testid="strategy-explanation-exit">
            <ConditionList condition={explanation.exit} />
          </ul>

          <h4>Markets</h4>
          <ul data-testid="strategy-explanation-markets">
            {explanation.markets.map((market, index) => (
              <li key={`${market.venue}-${market.pair}-${index}`} data-supported={market.supported ? "1" : "0"}>
                {market.text}
              </li>
            ))}
          </ul>

          <h4>Allocation and protection</h4>
          <p data-testid="strategy-explanation-allocation">{explanation.allocation.text}</p>
          <p data-testid="strategy-explanation-stop">{explanation.stop.text}</p>

          <p data-testid="strategy-explanation-performance">
            Costs, research results and performance are not provided by this
            revision and are not stated here.
          </p>

          {explanation.hasUnknowns ? (
            <p role="status" data-testid="strategy-explanation-unknowns">
              Some parts of this revision are unsupported in this explanation and
              shown as unknown above. The view does not decide whether the
              revision is valid or safe to run.
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
