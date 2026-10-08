import { useMemo, type ChangeEvent, type JSX } from "react";
import {
  COMPARISONS,
  MOVING_AVERAGE_KINDS,
  TIMEFRAMES,
  buildOwnedStrategyPack,
  validateOwnedStrategyField,
  type Comparison,
  type MovingAverageKind,
  type OwnedStrategyField,
  type OwnedStrategyFormState,
  type Timeframe,
} from "./ownedStrategy";
import type { Pack } from "./client";

export type OwnedStrategyFormProps = {
  state: OwnedStrategyFormState;
  basePack: Pack | null;
  onStateChange(next: OwnedStrategyFormState): void;
  onApply(pack: Pack | null, problems: string[]): void;
};

const COMPARISON_LABELS: Record<Comparison, string> = {
  ">": "close above",
  "<": "close below",
  ">=": "close at or above",
  "<=": "close at or below",
  crosses_above: "close crosses above",
  crosses_below: "close crosses below",
};

const KIND_LABELS: Record<MovingAverageKind, string> = {
  sma: "SMA (simple)",
  ema: "EMA (exponential)",
};

type TextFieldName =
  | "name"
  | "id"
  | "pair"
  | "length"
  | "maxAccountPct"
  | "stopPct";

const TEXT_FIELD_LABELS: Record<TextFieldName, string> = {
  name: "Strategy name",
  id: "Strategy id",
  pair: "Kraken pair",
  length: "Average length (bars)",
  maxAccountPct: "Max account percent",
  stopPct: "Protective stop percent",
};

const TEXT_FIELD_HINTS: Partial<Record<TextFieldName, string>> = {
  id: "lowercase-with-hyphens, max 32 characters; editing it starts a different strategy",
  pair: "uppercase like XXBTZUSD or XETHZUSD",
};

const VALIDATED_FIELDS: OwnedStrategyField[] = [
  "name",
  "id",
  "pair",
  "length",
  "maxAccountPct",
  "stopPct",
];

function problemsFor(state: OwnedStrategyFormState): string[] {
  const problems: string[] = [];
  for (const field of VALIDATED_FIELDS) {
    const message = validateOwnedStrategyField(field, state[field]);
    if (message) {
      problems.push(`${TEXT_FIELD_LABELS[field as TextFieldName]}: ${message}`);
    }
  }
  return problems;
}

export function OwnedStrategyForm({
  state,
  basePack,
  onStateChange,
  onApply,
}: OwnedStrategyFormProps): JSX.Element {
  const problemList = useMemo(() => problemsFor(state), [state]);

  const update = (patch: Partial<OwnedStrategyFormState>): void => {
    const next = { ...state, ...patch };
    onStateChange(next);
    // Problems are computed from `next`, never from the previous state, so
    // the message matches the value the user just typed.
    const problems = problemsFor(next);
    if (problems.length > 0) {
      // A field is invalid: keep reporting the problems and never replace
      // the pack payload with a broken one.
      onApply(null, problems);
      return;
    }
    const built = buildOwnedStrategyPack(next, basePack ?? {});
    if (!built) {
      onApply(null, ["Strategy values are not supported"]);
      return;
    }
    onApply(built, []);
  };

  const handleTextChange = (field: TextFieldName) =>
    (event: ChangeEvent<HTMLInputElement>): void => {
      update({ [field]: event.target.value } as Partial<OwnedStrategyFormState>);
    };

  const handleSelectChange =
    <K extends keyof OwnedStrategyFormState>(field: K) =>
    (event: ChangeEvent<HTMLSelectElement>): void => {
      const raw = event.target.value;
      const value =
        field === "timeframe"
          ? (raw as Timeframe)
          : field === "kind"
            ? (raw as MovingAverageKind)
            : (raw as Comparison);
      update({ [field]: value } as Partial<OwnedStrategyFormState>);
    };

  return (
    <section
      className="kbot-owned-strategy-form"
      role="group"
      aria-label="Owned strategy form"
      data-testid="owned-strategy-form"
    >
      <h3 className="kbot-owned-strategy-form__title">Owned strategy</h3>
      <p className="kbot-owned-strategy-form__hint">
        A supported subset of the pack DSL: one moving average of close, a
        close-versus-average entry and exit, a percentage protective stop, and
        one Kraken market. Advanced JSON stays available below.
      </p>
      <div className="kbot-owned-strategy-form__grid">
        {(Object.keys(TEXT_FIELD_LABELS) as TextFieldName[]).map((field) => (
          <label
            key={field}
            className="kbot-owned-strategy-form__field"
            htmlFor={`kbot-owned-strategy-${field}`}
          >
            <span className="kbot-owned-strategy-form__field-label">
              {TEXT_FIELD_LABELS[field]}
            </span>
            <input
              id={`kbot-owned-strategy-${field}`}
              className="kbot-owned-strategy-form__input"
              type="text"
              value={state[field]}
              onChange={handleTextChange(field)}
              autoComplete="off"
              spellCheck={false}
            />
            {TEXT_FIELD_HINTS[field] ? (
              <span className="kbot-owned-strategy-form__field-hint">
                {TEXT_FIELD_HINTS[field]}
              </span>
            ) : null}
          </label>
        ))}
        <label
          className="kbot-owned-strategy-form__field"
          htmlFor="kbot-owned-strategy-timeframe"
        >
          <span className="kbot-owned-strategy-form__field-label">Timeframe</span>
          <select
            id="kbot-owned-strategy-timeframe"
            className="kbot-owned-strategy-form__select"
            value={state.timeframe}
            onChange={handleSelectChange("timeframe")}
          >
            {TIMEFRAMES.map((timeframe) => (
              <option key={timeframe} value={timeframe}>
                {timeframe}
              </option>
            ))}
          </select>
        </label>
        <label
          className="kbot-owned-strategy-form__field"
          htmlFor="kbot-owned-strategy-kind"
        >
          <span className="kbot-owned-strategy-form__field-label">
            Average type
          </span>
          <select
            id="kbot-owned-strategy-kind"
            className="kbot-owned-strategy-form__select"
            value={state.kind}
            onChange={handleSelectChange("kind")}
          >
            {MOVING_AVERAGE_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {KIND_LABELS[kind]}
              </option>
            ))}
          </select>
        </label>
        <label
          className="kbot-owned-strategy-form__field"
          htmlFor="kbot-owned-strategy-entryComparison"
        >
          <span className="kbot-owned-strategy-form__field-label">
            Enter when
          </span>
          <select
            id="kbot-owned-strategy-entryComparison"
            className="kbot-owned-strategy-form__select"
            value={state.entryComparison}
            onChange={handleSelectChange("entryComparison")}
          >
            {COMPARISONS.map((comparison) => (
              <option key={comparison} value={comparison}>
                {COMPARISON_LABELS[comparison]}
              </option>
            ))}
          </select>
        </label>
        <label
          className="kbot-owned-strategy-form__field"
          htmlFor="kbot-owned-strategy-exitComparison"
        >
          <span className="kbot-owned-strategy-form__field-label">Exit when</span>
          <select
            id="kbot-owned-strategy-exitComparison"
            className="kbot-owned-strategy-form__select"
            value={state.exitComparison}
            onChange={handleSelectChange("exitComparison")}
          >
            {COMPARISONS.map((comparison) => (
              <option key={comparison} value={comparison}>
                {COMPARISON_LABELS[comparison]}
              </option>
            ))}
          </select>
        </label>
      </div>
      {problemList.length > 0 ? (
        <ul
          className="kbot-owned-strategy-form__problems"
          data-testid="owned-strategy-form-problems"
        >
          {problemList.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : null}
      <p className="kbot-owned-strategy-form__footnote">
        Paper-trading only; live execution stays disabled in this workstation.
      </p>
    </section>
  );
}
