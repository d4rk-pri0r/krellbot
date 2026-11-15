import { useMemo, type ChangeEvent, type JSX } from "react";
import "./OwnedStrategyForm.signal.css";
import {
  COMPARISONS,
  MOVING_AVERAGE_KINDS,
  NESTING_MODES,
  RECIPE_NAMES,
  STOP_KINDS,
  TIMEFRAMES,
  VENUES,
  buildOwnedStrategyPack,
  validateOwnedStrategyField,
  type Comparison,
  type MovingAverageKind,
  type NestingMode,
  type OwnedStrategyField,
  type OwnedStrategyFormState,
  type RecipeName,
  type StopKind,
  type Timeframe,
  type Venue,
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

const CROSS_COMPARISON_LABELS: Record<Comparison, string> = {
  ">": "fast average above slow",
  "<": "fast average below slow",
  ">=": "fast average at or above slow",
  "<=": "fast average at or below slow",
  crosses_above: "fast average crosses above slow",
  crosses_below: "fast average crosses below slow",
};

const CONFIRM_COMPARISON_LABELS: Record<Comparison, string> = {
  ">": "close above threshold",
  "<": "close below threshold",
  ">=": "close at or above threshold",
  "<=": "close at or below threshold",
  crosses_above: "close crosses above threshold",
  crosses_below: "close crosses below threshold",
};

const KIND_LABELS: Record<MovingAverageKind, string> = {
  sma: "SMA (simple)",
  ema: "EMA (exponential)",
  wma: "WMA (weighted)",
  vwma: "VWMA (volume-weighted)",
  stdev: "Stdev (standard deviation)",
  roc: "ROC (rate of change)",
  efficiency_ratio: "Efficiency ratio",
  hma: "HMA (Hull)",
};

const RECIPE_LABELS: Record<RecipeName, string> = {
  close_vs_ma: "Close versus one average",
  ma_cross: "Two-average crossover (fast vs slow)",
};

const VENUE_LABELS: Record<Venue, string> = {
  kraken: "Kraken",
  coinbase: "Coinbase",
};

const STOP_KIND_LABELS: Record<StopKind, string> = {
  pct: "Percentage stop",
  atr: "ATR stop",
};

const NESTING_LABELS: Record<NestingMode, string> = {
  leaf: "Single condition",
  all: "All of (condition and confirm)",
  any: "Any of (condition or confirm)",
};

type TextFieldName =
  | "name"
  | "id"
  | "pair"
  | "secondPair"
  | "fastLength"
  | "length"
  | "maxAccountPct"
  | "stopPct"
  | "atrLen"
  | "atrMult"
  | "entryConfirmThreshold"
  | "exitConfirmThreshold";

const TEXT_FIELD_LABELS: Record<TextFieldName, string> = {
  name: "Strategy name",
  id: "Strategy id",
  pair: "Market pair",
  secondPair: "Optional second pair",
  fastLength: "Fast average length (bars)",
  length: "Average length (bars)",
  maxAccountPct: "Max account percent",
  stopPct: "Protective stop percent",
  atrLen: "ATR stop length (bars)",
  atrMult: "ATR stop multiplier",
  entryConfirmThreshold: "Entry confirm threshold",
  exitConfirmThreshold: "Exit confirm threshold",
};

const TEXT_FIELD_HINTS: Partial<Record<TextFieldName, string>> = {
  id: "lowercase-with-hyphens, max 32 characters; editing it starts a different strategy",
  pair: "uppercase like XXBTZUSD, XETHZUSD, or BTC-USD",
  secondPair: "leave blank for one market; set to add a second paper market (max two)",
  fastLength: "must be shorter than the slow average length",
  atrMult: "greater than 0 and at most 20",
  entryConfirmThreshold: "numeric close threshold paired with the entry nesting",
  exitConfirmThreshold: "numeric close threshold paired with the exit nesting",
};

const VALIDATED_FIELDS: OwnedStrategyField[] = [
  "name",
  "id",
  "pair",
  "secondPair",
  "length",
  "maxAccountPct",
];

function problemsFor(state: OwnedStrategyFormState): string[] {
  const problems: string[] = [];
  const fields: OwnedStrategyField[] =
    state.recipe === "ma_cross"
      ? [...VALIDATED_FIELDS.slice(0, 4), "fastLength", ...VALIDATED_FIELDS.slice(4)]
      : VALIDATED_FIELDS;
  if (state.stopKind === "pct") {
    fields.push("stopPct");
  } else {
    fields.push("atrLen", "atrMult");
  }
  if (state.entryNesting !== "leaf") {
    fields.push("entryConfirmThreshold");
  }
  if (state.exitNesting !== "leaf") {
    fields.push("exitConfirmThreshold");
  }
  for (const field of fields) {
    const message = validateOwnedStrategyField(field, state[field]);
    if (message) {
      problems.push(`${TEXT_FIELD_LABELS[field as TextFieldName]}: ${message}`);
    }
  }
  // Only the crossover recipe has two averages to order; the single-average
  // recipe keeps its existing behavior with the lone `length` field.
  if (
    state.recipe === "ma_cross" &&
    Number.isFinite(Number(state.fastLength)) &&
    Number.isFinite(Number(state.length)) &&
    Number(state.fastLength) >= Number(state.length)
  ) {
    problems.push(
      "Fast average length: must be shorter than the slow average length",
    );
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
            : field === "recipe"
              ? (raw as RecipeName)
              : field === "venue" || field === "secondVenue"
                ? (raw as Venue)
                : field === "stopKind"
                  ? (raw as StopKind)
                  : field === "entryNesting" || field === "exitNesting"
                    ? (raw as NestingMode)
                    : (raw as Comparison);
      update({ [field]: value } as Partial<OwnedStrategyFormState>);
    };

  const crossover = state.recipe === "ma_cross";
  const comparisonLabels = crossover ? CROSS_COMPARISON_LABELS : COMPARISON_LABELS;
  const atrStop = state.stopKind === "atr";
  const showEntryConfirm = state.entryNesting !== "leaf";
  const showExitConfirm = state.exitNesting !== "leaf";

  const renderTextField = (field: TextFieldName): JSX.Element => (
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
  );

  return (
    <div className="kbot-feature__owned-strategy-form-root">
      <section
        className="kbot-owned-strategy-form"
        role="group"
        aria-label="Owned strategy form"
        data-testid="owned-strategy-form"
      >
        <h3 className="kbot-owned-strategy-form__title">Owned strategy</h3>
        <p className="kbot-owned-strategy-form__hint">
          Guided pack coverage: close versus one indicator or a fast/slow
          crossover, optional all/any confirm nesting, percentage or ATR stop,
          and one or two Kraken or Coinbase paper markets. Advanced JSON stays
          available below; validate before arm is unchanged.
        </p>
        <div className="kbot-owned-strategy-form__grid">
          <label
            className="kbot-owned-strategy-form__field"
            htmlFor="kbot-owned-strategy-recipe"
          >
            <span className="kbot-owned-strategy-form__field-label">Recipe</span>
            <select
              id="kbot-owned-strategy-recipe"
              className="kbot-owned-strategy-form__select"
              value={state.recipe}
              onChange={handleSelectChange("recipe")}
            >
              {RECIPE_NAMES.map((recipe) => (
                <option key={recipe} value={recipe}>
                  {RECIPE_LABELS[recipe]}
                </option>
              ))}
            </select>
          </label>
          <p
            data-testid="owned-strategy-form-recipe-status"
            id="owned-strategy-form-recipe-status"
            className="kbot-owned-strategy-form__recipe-status"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            {state.recipe === "ma_cross"
              ? "Recipe: two-average crossover. Enter and exit comparisons now mean fast average versus slow average. A Fast average length field has appeared."
              : "Recipe: close versus one average. Enter and exit comparisons now mean close versus the single average. The Fast average length field is hidden."}
          </p>
          {renderTextField("name")}
          {renderTextField("id")}
          <label
            className="kbot-owned-strategy-form__field"
            htmlFor="kbot-owned-strategy-venue"
          >
            <span className="kbot-owned-strategy-form__field-label">
              Market venue
            </span>
            <select
              id="kbot-owned-strategy-venue"
              className="kbot-owned-strategy-form__select"
              value={state.venue}
              onChange={handleSelectChange("venue")}
            >
              {VENUES.map((venue) => (
                <option key={venue} value={venue}>
                  {VENUE_LABELS[venue]}
                </option>
              ))}
            </select>
          </label>
          {renderTextField("pair")}
          {renderTextField("secondPair")}
          <label
            className="kbot-owned-strategy-form__field"
            htmlFor="kbot-owned-strategy-secondVenue"
          >
            <span className="kbot-owned-strategy-form__field-label">
              Second venue
            </span>
            <select
              id="kbot-owned-strategy-secondVenue"
              className="kbot-owned-strategy-form__select"
              value={state.secondVenue}
              onChange={handleSelectChange("secondVenue")}
              disabled={state.secondPair.trim() === ""}
            >
              {VENUES.map((venue) => (
                <option key={venue} value={venue}>
                  {VENUE_LABELS[venue]}
                </option>
              ))}
            </select>
          </label>
          {crossover ? renderTextField("fastLength") : null}
          {renderTextField("length")}
          {renderTextField("maxAccountPct")}
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
              {crossover ? "Indicator type (both averages)" : "Indicator type"}
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
            htmlFor="kbot-owned-strategy-stopKind"
          >
            <span className="kbot-owned-strategy-form__field-label">
              Protective stop
            </span>
            <select
              id="kbot-owned-strategy-stopKind"
              className="kbot-owned-strategy-form__select"
              value={state.stopKind}
              onChange={handleSelectChange("stopKind")}
            >
              {STOP_KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {STOP_KIND_LABELS[kind]}
                </option>
              ))}
            </select>
          </label>
          {atrStop ? (
            <>
              {renderTextField("atrLen")}
              {renderTextField("atrMult")}
            </>
          ) : (
            renderTextField("stopPct")
          )}
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
                  {comparisonLabels[comparison]}
                </option>
              ))}
            </select>
          </label>
          <label
            className="kbot-owned-strategy-form__field"
            htmlFor="kbot-owned-strategy-entryNesting"
          >
            <span className="kbot-owned-strategy-form__field-label">
              Entry nesting
            </span>
            <select
              id="kbot-owned-strategy-entryNesting"
              className="kbot-owned-strategy-form__select"
              value={state.entryNesting}
              onChange={handleSelectChange("entryNesting")}
            >
              {NESTING_MODES.map((mode) => (
                <option key={mode} value={mode}>
                  {NESTING_LABELS[mode]}
                </option>
              ))}
            </select>
          </label>
          {showEntryConfirm ? (
            <>
              <label
                className="kbot-owned-strategy-form__field"
                htmlFor="kbot-owned-strategy-entryConfirmComparison"
              >
                <span className="kbot-owned-strategy-form__field-label">
                  Entry confirm when
                </span>
                <select
                  id="kbot-owned-strategy-entryConfirmComparison"
                  className="kbot-owned-strategy-form__select"
                  value={state.entryConfirmComparison}
                  onChange={handleSelectChange("entryConfirmComparison")}
                >
                  {COMPARISONS.map((comparison) => (
                    <option key={comparison} value={comparison}>
                      {CONFIRM_COMPARISON_LABELS[comparison]}
                    </option>
                  ))}
                </select>
              </label>
              {renderTextField("entryConfirmThreshold")}
            </>
          ) : null}
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
                  {comparisonLabels[comparison]}
                </option>
              ))}
            </select>
          </label>
          <label
            className="kbot-owned-strategy-form__field"
            htmlFor="kbot-owned-strategy-exitNesting"
          >
            <span className="kbot-owned-strategy-form__field-label">
              Exit nesting
            </span>
            <select
              id="kbot-owned-strategy-exitNesting"
              className="kbot-owned-strategy-form__select"
              value={state.exitNesting}
              onChange={handleSelectChange("exitNesting")}
            >
              {NESTING_MODES.map((mode) => (
                <option key={mode} value={mode}>
                  {NESTING_LABELS[mode]}
                </option>
              ))}
            </select>
          </label>
          {showExitConfirm ? (
            <>
              <label
                className="kbot-owned-strategy-form__field"
                htmlFor="kbot-owned-strategy-exitConfirmComparison"
              >
                <span className="kbot-owned-strategy-form__field-label">
                  Exit confirm when
                </span>
                <select
                  id="kbot-owned-strategy-exitConfirmComparison"
                  className="kbot-owned-strategy-form__select"
                  value={state.exitConfirmComparison}
                  onChange={handleSelectChange("exitConfirmComparison")}
                >
                  {COMPARISONS.map((comparison) => (
                    <option key={comparison} value={comparison}>
                      {CONFIRM_COMPARISON_LABELS[comparison]}
                    </option>
                  ))}
                </select>
              </label>
              {renderTextField("exitConfirmThreshold")}
            </>
          ) : null}
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
          Arm still requires a validated revision.
        </p>
      </section>
    </div>
  );
}
