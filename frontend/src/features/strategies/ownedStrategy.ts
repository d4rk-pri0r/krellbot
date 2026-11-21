// Owned-strategy form model.
//
// Guided subset of the Pack DSL (src/krellbot/pack/schema.json): close versus
// one indicator or a two-average crossover, optional single-level all/any
// nesting with a close-vs-threshold confirm leaf, percentage or ATR protective
// stops, and one or two kraken|coinbase|binance|gate|pionex markets (paper-capable). Anything else
// — deeper nesting, extra indicator params (power_mean / roofing), more than
// two markets, unknown keys — returns null from `readOwnedStrategy` so the
// editor never silently rewrites or strips it.

import type { Pack } from "./client";
import { KRAKEN_BTC_USD_VENUE_SYMBOL } from "../../markets/krakenBtcUsd.ts";

export const INDICATOR_NAME = "ma";
export const FAST_INDICATOR_NAME = "fast";
export const SLOW_INDICATOR_NAME = "slow";

/** Stored Kraken venue symbol for the BTC/USD wave (not a display label). */
export const DEFAULT_PAIR = KRAKEN_BTC_USD_VENUE_SYMBOL;

export const TIMEFRAMES = ["1h", "4h", "1d"] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];

/** Src+len indicator fns the guided form can author (ATR is a stop, not here). */
export const MOVING_AVERAGE_KINDS = [
  "sma",
  "ema",
  "wma",
  "vwma",
  "stdev",
  "roc",
  "efficiency_ratio",
  "hma",
] as const;
export type MovingAverageKind = (typeof MOVING_AVERAGE_KINDS)[number];

export const RECIPE_NAMES = ["close_vs_ma", "ma_cross"] as const;
export type RecipeName = (typeof RECIPE_NAMES)[number];

export const COMPARISONS = [
  ">",
  "<",
  ">=",
  "<=",
  "crosses_above",
  "crosses_below",
] as const;
export type Comparison = (typeof COMPARISONS)[number];

export const VENUES = ["kraken", "coinbase", "binance", "gate", "pionex"] as const;
export type Venue = (typeof VENUES)[number];

/** Canonical Binance-class paper wave pair (concatenated BASEQUOTE). */
export const BINANCE_PAPER_WAVE_PAIR = "BTCUSDT";
export const GATE_PAPER_WAVE_PAIR = "BTC-USDT";
export const PIONEX_PAPER_WAVE_PAIR = "BTC-USDT";

export const STOP_KINDS = ["pct", "atr"] as const;
export type StopKind = (typeof STOP_KINDS)[number];

export const NESTING_MODES = ["leaf", "all", "any"] as const;
export type NestingMode = (typeof NESTING_MODES)[number];

export type OwnedStrategyField =
  | "name"
  | "id"
  | "pair"
  | "secondPair"
  | "timeframe"
  | "recipe"
  | "kind"
  | "fastLength"
  | "length"
  | "entryComparison"
  | "exitComparison"
  | "maxAccountPct"
  | "stopPct"
  | "atrLen"
  | "atrMult"
  | "entryConfirmThreshold"
  | "exitConfirmThreshold";

export type OwnedStrategyFormState = {
  name: string;
  id: string;
  venue: Venue;
  pair: string;
  secondVenue: Venue;
  secondPair: string;
  timeframe: Timeframe;
  recipe: RecipeName;
  kind: MovingAverageKind;
  fastLength: string;
  length: string;
  entryComparison: Comparison;
  exitComparison: Comparison;
  entryNesting: NestingMode;
  exitNesting: NestingMode;
  entryConfirmComparison: Comparison;
  exitConfirmComparison: Comparison;
  entryConfirmThreshold: string;
  exitConfirmThreshold: string;
  maxAccountPct: string;
  stopKind: StopKind;
  stopPct: string;
  atrLen: string;
  atrMult: string;
};

// Bounds mirror schema.json plus pack/lint.py's lookback budget
// (lookback len + 1 <= 600, so len 600 would fail lint even though the
// schema alone accepts it).
const LENGTH_MIN = 2;
const LENGTH_MAX = 599;
const NAME_MAX = 120;
const AUTHOR_MAX = 120;
const DEFAULT_AUTHOR = "local workstation";
const DEFAULT_TIMEFRAME: Timeframe = "1h";
const ATR_MULT_MAX = 20;

const ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,31}$/;
const PAIR_PATTERN = /^[A-Z0-9]{2,16}(-[A-Z0-9]{2,16})?$/;

function isFiniteNumber(text: string): boolean {
  if (!/^-?\d+(\.\d+)?$/.test(text)) {
    return false;
  }
  return Number.isFinite(Number(text));
}

function integerIn(text: string, min: number, max: number): boolean {
  if (!/^\d+$/.test(text)) {
    return false;
  }
  const value = Number(text);
  return Number.isInteger(value) && value >= min && value <= max;
}

function slugify(text: string): string {
  const base = text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32);
  const slug = base === "" ? "strategy" : base;
  const suffix = Math.random().toString(36).slice(2, 6);
  return `${slug.slice(0, 27)}-${suffix}`.slice(0, 32);
}

export function validateOwnedStrategyField(
  field: OwnedStrategyField,
  value: string,
): string | undefined {
  switch (field) {
    case "name":
      if (value.trim().length < 1) {
        return "Name is required";
      }
      if (value.length > NAME_MAX) {
        return `Name must be at most ${NAME_MAX} characters`;
      }
      return undefined;
    case "id":
      if (!ID_PATTERN.test(value)) {
        return "Id must be lowercase letters, digits or hyphens (max 32)";
      }
      return undefined;
    case "pair":
    case "secondPair":
      if (field === "secondPair" && value.trim() === "") {
        return undefined;
      }
      if (!PAIR_PATTERN.test(value)) {
        return "Pair must be uppercase like XXBTZUSD or BTC-USD";
      }
      return undefined;
    case "length":
      if (!integerIn(value, LENGTH_MIN, LENGTH_MAX)) {
        return `Length must be a whole number between ${LENGTH_MIN} and ${LENGTH_MAX}`;
      }
      return undefined;
    case "fastLength":
      if (!integerIn(value, LENGTH_MIN, LENGTH_MAX)) {
        return `Fast length must be a whole number between ${LENGTH_MIN} and ${LENGTH_MAX}`;
      }
      return undefined;
    case "atrLen":
      if (!integerIn(value, LENGTH_MIN, LENGTH_MAX)) {
        return `ATR length must be a whole number between ${LENGTH_MIN} and ${LENGTH_MAX}`;
      }
      return undefined;
    case "maxAccountPct":
      if (!integerIn(value, 1, 100)) {
        return "Max account percent must be a whole number between 1 and 100";
      }
      return undefined;
    case "stopPct": {
      if (!isFiniteNumber(value)) {
        return "Stop percent must be a number greater than 0 and at most 100";
      }
      const valueNumber = Number(value);
      if (valueNumber <= 0 || valueNumber > 100) {
        return "Stop percent must be greater than 0 and at most 100";
      }
      return undefined;
    }
    case "atrMult": {
      if (!isFiniteNumber(value)) {
        return `ATR multiplier must be a number greater than 0 and at most ${ATR_MULT_MAX}`;
      }
      const valueNumber = Number(value);
      if (valueNumber <= 0 || valueNumber > ATR_MULT_MAX) {
        return `ATR multiplier must be greater than 0 and at most ${ATR_MULT_MAX}`;
      }
      return undefined;
    }
    case "entryConfirmThreshold":
    case "exitConfirmThreshold": {
      if (!isFiniteNumber(value)) {
        return "Confirm threshold must be a finite number";
      }
      return undefined;
    }
    default:
      return undefined;
  }
}

function isTimeframe(value: unknown): value is Timeframe {
  return typeof value === "string" && (TIMEFRAMES as readonly string[]).includes(value);
}

function isKind(value: unknown): value is MovingAverageKind {
  return (
    typeof value === "string" &&
    (MOVING_AVERAGE_KINDS as readonly string[]).includes(value)
  );
}

function isComparison(value: unknown): value is Comparison {
  return (
    typeof value === "string" && (COMPARISONS as readonly string[]).includes(value)
  );
}

function isVenue(value: unknown): value is Venue {
  return typeof value === "string" && (VENUES as readonly string[]).includes(value);
}

function isStopKind(value: unknown): value is StopKind {
  return typeof value === "string" && (STOP_KINDS as readonly string[]).includes(value);
}

function isNestingMode(value: unknown): value is NestingMode {
  return (
    typeof value === "string" && (NESTING_MODES as readonly string[]).includes(value)
  );
}

export function seedOwnedStrategyForm(): OwnedStrategyFormState {
  return {
    name: "Moving average plan",
    id: slugify("moving-average-plan"),
    venue: "kraken",
    pair: DEFAULT_PAIR,
    secondVenue: "coinbase",
    secondPair: "",
    timeframe: DEFAULT_TIMEFRAME,
    recipe: "close_vs_ma",
    kind: "sma",
    fastLength: "10",
    length: "20",
    entryComparison: ">",
    exitComparison: "<",
    entryNesting: "leaf",
    exitNesting: "leaf",
    entryConfirmComparison: ">",
    exitConfirmComparison: "<",
    entryConfirmThreshold: "0",
    exitConfirmThreshold: "0",
    maxAccountPct: "25",
    stopKind: "pct",
    stopPct: "5",
    atrLen: "14",
    atrMult: "2",
  };
}

export function seedOwnedStrategyPack(name: string): Pack {
  const trimmed = name.trim().slice(0, NAME_MAX) || "Moving average plan";
  const form: OwnedStrategyFormState = {
    ...seedOwnedStrategyForm(),
    name: trimmed,
    id: slugify(trimmed),
  };
  // Built through the same path the form uses so the seeded pack always
  // matches the seeded form state (same id, same parameters).
  return buildOwnedStrategyPack(form, {}) as Pack;
}

type LeafCondition = [string, Comparison, string | number];

function isLeafCondition(value: unknown): value is LeafCondition {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    typeof value[0] === "string" &&
    (typeof value[2] === "string" || typeof value[2] === "number") &&
    isComparison(value[1])
  );
}

type ParsedCondition = {
  leaf: LeafCondition;
  nesting: NestingMode;
  confirmComparison: Comparison;
  confirmThreshold: string;
};

function parseGuidedCondition(value: unknown): ParsedCondition | null {
  if (isLeafCondition(value)) {
    // Primary leaves always use string indicator/price operands in the
    // guided recipes; a numeric right-hand side is confirm-only.
    if (typeof value[2] !== "string") {
      return null;
    }
    return {
      leaf: value,
      nesting: "leaf",
      confirmComparison: ">",
      confirmThreshold: "0",
    };
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const row = value as Record<string, unknown>;
  const keys = Object.keys(row);
  if (keys.length !== 1) {
    return null;
  }
  const nesting = keys[0];
  if (nesting !== "all" && nesting !== "any") {
    return null;
  }
  const children = row[nesting];
  if (!Array.isArray(children) || children.length !== 2) {
    return null;
  }
  if (!isLeafCondition(children[0]) || typeof children[0][2] !== "string") {
    return null;
  }
  const confirm = children[1];
  if (
    !isLeafCondition(confirm) ||
    confirm[0] !== "close" ||
    typeof confirm[2] !== "number" ||
    !Number.isFinite(confirm[2])
  ) {
    return null;
  }
  return {
    leaf: children[0],
    nesting,
    confirmComparison: confirm[1],
    confirmThreshold: String(confirm[2]),
  };
}

function wrapGuidedCondition(
  leaf: LeafCondition,
  nesting: NestingMode,
  confirmComparison: Comparison,
  threshold: number,
): LeafCondition | { all: LeafCondition[] } | { any: LeafCondition[] } {
  if (nesting === "leaf") {
    return leaf;
  }
  const confirm: LeafCondition = ["close", confirmComparison, threshold];
  if (nesting === "all") {
    return { all: [leaf, confirm] };
  }
  return { any: [leaf, confirm] };
}

/**
 * Read a pack into form state only when it is exactly the supported subset —
 * either the generated single-indicator shape (close compared to it) or the
 * generated two-average crossover shape (`fast` and `slow`), with optional
 * single-level all/any confirm nesting, pct or ATR stop, and one or two
 * kraken|coinbase|binance|gate|pionex markets. Anything else returns null so callers keep the
 * original bytes untouched instead of guessing at a partial edit.
 */
export function readOwnedStrategy(pack: Pack | null): OwnedStrategyFormState | null {
  if (!pack || pack.schema_version !== 1) {
    return null;
  }
  const name = pack.label;
  const id = pack.id;
  const author = pack.author;
  const timeframe = pack.timeframe;
  const indicators = pack.indicators;
  const entry = pack.entry;
  const exit = pack.exit;
  const risk = pack.risk;
  const markets = pack.markets;
  if (
    typeof name !== "string" ||
    name.length < 1 ||
    name.length > NAME_MAX ||
    typeof id !== "string" ||
    !ID_PATTERN.test(id) ||
    typeof author !== "string" ||
    author.length < 1 ||
    author.length > AUTHOR_MAX ||
    !isTimeframe(timeframe) ||
    !indicators ||
    typeof indicators !== "object" ||
    Array.isArray(indicators) ||
    (Object.keys(indicators).length !== 1 && Object.keys(indicators).length !== 2) ||
    !Array.isArray(markets) ||
    markets.length < 1 ||
    markets.length > 2
  ) {
    return null;
  }
  const parsedMarkets: { venue: Venue; pair: string }[] = [];
  for (const raw of markets) {
    if (!raw || typeof raw !== "object") {
      return null;
    }
    const market = raw as { venue?: unknown; pair?: unknown };
    if (!isVenue(market.venue) || typeof market.pair !== "string") {
      return null;
    }
    if (!PAIR_PATTERN.test(market.pair)) {
      return null;
    }
    parsedMarkets.push({ venue: market.venue, pair: market.pair });
  }
  const indicatorEntries = Object.entries(indicators as Record<string, unknown>).map(
    ([indicatorName, indicator]) => {
      if (
        !indicator ||
        typeof indicator !== "object" ||
        Array.isArray(indicator)
      ) {
        return null;
      }
      const params = indicator as { fn?: unknown; src?: unknown; len?: unknown };
      if (
        !isKind(params.fn) ||
        params.src !== "close" ||
        typeof params.len !== "number" ||
        !Number.isInteger(params.len) ||
        params.len < LENGTH_MIN ||
        params.len > LENGTH_MAX ||
        Object.keys(params).length !== 3
      ) {
        return null;
      }
      return { name: indicatorName, kind: params.fn, len: params.len };
    },
  );
  if (indicatorEntries.some((entry) => entry === null)) {
    return null;
  }
  const parsedEntry = parseGuidedCondition(entry);
  const parsedExit = parseGuidedCondition(exit);
  if (!parsedEntry || !parsedExit) {
    return null;
  }
  if (!risk || typeof risk !== "object" || Array.isArray(risk)) {
    return null;
  }
  const riskRow = risk as {
    max_account_pct?: unknown;
    stop?: unknown;
  };
  if (
    typeof riskRow.max_account_pct !== "number" ||
    !Number.isInteger(riskRow.max_account_pct) ||
    riskRow.max_account_pct < 1 ||
    riskRow.max_account_pct > 100 ||
    !riskRow.stop ||
    typeof riskRow.stop !== "object" ||
    Array.isArray(riskRow.stop) ||
    Object.keys(riskRow).length !== 2
  ) {
    return null;
  }
  const stop = riskRow.stop as {
    type?: unknown;
    pct?: unknown;
    len?: unknown;
    mult?: unknown;
  };
  let stopKind: StopKind;
  let stopPct = "5";
  let atrLen = "14";
  let atrMult = "2";
  if (stop.type === "pct") {
    if (
      typeof stop.pct !== "number" ||
      !Number.isFinite(stop.pct) ||
      stop.pct <= 0 ||
      stop.pct > 100 ||
      Object.keys(stop).length !== 2
    ) {
      return null;
    }
    stopKind = "pct";
    stopPct = String(stop.pct);
  } else if (stop.type === "atr") {
    if (
      typeof stop.len !== "number" ||
      !Number.isInteger(stop.len) ||
      stop.len < LENGTH_MIN ||
      stop.len > LENGTH_MAX ||
      typeof stop.mult !== "number" ||
      !Number.isFinite(stop.mult) ||
      stop.mult <= 0 ||
      stop.mult > ATR_MULT_MAX ||
      Object.keys(stop).length !== 3
    ) {
      return null;
    }
    stopKind = "atr";
    atrLen = String(stop.len);
    atrMult = String(stop.mult);
  } else {
    return null;
  }
  // Only the documented pack keys may be present; an imported pack with
  // anything extra is not part of the supported subset.
  const allowedKeys = new Set([
    "schema_version",
    "id",
    "version",
    "label",
    "author",
    "origin",
    "timeframe",
    "indicators",
    "entry",
    "exit",
    "risk",
    "markets",
  ]);
  for (const key of Object.keys(pack)) {
    if (!allowedKeys.has(key)) {
      return null;
    }
  }
  const [primary, secondary] = parsedMarkets;
  const common = {
    name,
    id,
    venue: primary.venue,
    pair: primary.pair,
    secondVenue: secondary?.venue ?? "coinbase",
    secondPair: secondary?.pair ?? "",
    timeframe,
    entryNesting: parsedEntry.nesting,
    exitNesting: parsedExit.nesting,
    entryConfirmComparison: parsedEntry.confirmComparison,
    exitConfirmComparison: parsedExit.confirmComparison,
    entryConfirmThreshold: parsedEntry.confirmThreshold,
    exitConfirmThreshold: parsedExit.confirmThreshold,
    maxAccountPct: String(riskRow.max_account_pct),
    stopKind,
    stopPct,
    atrLen,
    atrMult,
  };
  const entryLeaf = parsedEntry.leaf;
  const exitLeaf = parsedExit.leaf;
  if (indicatorEntries.length === 1) {
    const [single] = indicatorEntries as [{ name: string; kind: MovingAverageKind; len: number }];
    // Single-indicator shape: one indicator under any schema-valid name, with
    // close on the left of both primary leaves. The name is preserved as-is on
    // rebuild, so an imported `sma3`-style pack keeps its indicator name.
    if (
      entryLeaf[0] !== "close" ||
      entryLeaf[2] !== single.name ||
      exitLeaf[0] !== "close" ||
      exitLeaf[2] !== single.name
    ) {
      return null;
    }
    return {
      ...common,
      recipe: "close_vs_ma",
      kind: single.kind,
      fastLength: "",
      length: String(single.len),
      entryComparison: entryLeaf[1],
      exitComparison: exitLeaf[1],
    };
  }
  const [fast, slow] = indicatorEntries as [
    { name: string; kind: MovingAverageKind; len: number },
    { name: string; kind: MovingAverageKind; len: number },
  ];
  // Two-average crossover shape: the generated `fast`/`slow` names, one
  // shared average kind, fast strictly shorter than slow, and fast compared
  // to slow in both primary leaves.
  if (
    fast.name !== FAST_INDICATOR_NAME ||
    slow.name !== SLOW_INDICATOR_NAME ||
    fast.kind !== slow.kind ||
    fast.len >= slow.len ||
    entryLeaf[0] !== FAST_INDICATOR_NAME ||
    entryLeaf[2] !== SLOW_INDICATOR_NAME ||
    exitLeaf[0] !== FAST_INDICATOR_NAME ||
    exitLeaf[2] !== SLOW_INDICATOR_NAME
  ) {
    return null;
  }
  return {
    ...common,
    recipe: "ma_cross",
    kind: fast.kind,
    fastLength: String(fast.len),
    length: String(slow.len),
    entryComparison: entryLeaf[1],
    exitComparison: exitLeaf[1],
  };
}

/**
 * Build a pack from form state. Returns null (and no partial pack) when any
 * field is invalid, so a caller can refuse to replace a good payload with a
 * broken one.
 */
export function buildOwnedStrategyPack(
  state: OwnedStrategyFormState,
  base: Pack,
): Pack | null {
  const fields: OwnedStrategyField[] = [
    "name",
    "id",
    "pair",
    "secondPair",
    "length",
    "maxAccountPct",
  ];
  if (state.recipe === "ma_cross") {
    fields.push("fastLength");
  }
  if (state.stopKind === "pct") {
    fields.push("stopPct");
  } else if (state.stopKind === "atr") {
    fields.push("atrLen", "atrMult");
  } else {
    return null;
  }
  if (state.entryNesting !== "leaf") {
    fields.push("entryConfirmThreshold");
  }
  if (state.exitNesting !== "leaf") {
    fields.push("exitConfirmThreshold");
  }
  for (const field of fields) {
    if (validateOwnedStrategyField(field, state[field]) !== undefined) {
      return null;
    }
  }
  if (
    !isTimeframe(state.timeframe) ||
    !isKind(state.kind) ||
    !isVenue(state.venue) ||
    !isVenue(state.secondVenue) ||
    !isStopKind(state.stopKind) ||
    !isNestingMode(state.entryNesting) ||
    !isNestingMode(state.exitNesting)
  ) {
    return null;
  }
  if (!isComparison(state.entryComparison) || !isComparison(state.exitComparison)) {
    return null;
  }
  if (
    !isComparison(state.entryConfirmComparison) ||
    !isComparison(state.exitConfirmComparison)
  ) {
    return null;
  }
  if (typeof state.name !== "string" || typeof state.id !== "string") {
    return null;
  }
  const version = typeof base.version === "string" ? base.version : "1.0.0";
  const author =
    typeof base.author === "string" && base.author.length > 0
      ? base.author.slice(0, AUTHOR_MAX)
      : DEFAULT_AUTHOR;
  const risk =
    state.stopKind === "pct"
      ? {
          max_account_pct: Number(state.maxAccountPct),
          stop: { type: "pct", pct: Number(state.stopPct) },
        }
      : {
          max_account_pct: Number(state.maxAccountPct),
          stop: {
            type: "atr",
            len: Number(state.atrLen),
            mult: Number(state.atrMult),
          },
        };
  const markets: { venue: Venue; pair: string }[] = [
    { venue: state.venue, pair: state.pair },
  ];
  if (state.secondPair.trim() !== "") {
    markets.push({ venue: state.secondVenue, pair: state.secondPair });
  }
  const entryThreshold = Number(state.entryConfirmThreshold);
  const exitThreshold = Number(state.exitConfirmThreshold);

  const finish = (
    indicators: Record<string, { fn: MovingAverageKind; src: "close"; len: number }>,
    entryLeaf: LeafCondition,
    exitLeaf: LeafCondition,
  ): Pack => ({
    schema_version: 1,
    id: state.id,
    version,
    label: state.name,
    author,
    ...(typeof base.origin === "string" ? { origin: base.origin } : {}),
    timeframe: state.timeframe,
    indicators,
    entry: wrapGuidedCondition(
      entryLeaf,
      state.entryNesting,
      state.entryConfirmComparison,
      entryThreshold,
    ),
    exit: wrapGuidedCondition(
      exitLeaf,
      state.exitNesting,
      state.exitConfirmComparison,
      exitThreshold,
    ),
    risk,
    markets,
  });

  if (state.recipe === "ma_cross") {
    const fastLength = Number(state.fastLength);
    const slowLength = Number(state.length);
    // A "fast" average at or above the slow average is a contradiction, not a
    // number-format error, so it is refused here rather than normalized.
    if (fastLength >= slowLength) {
      return null;
    }
    return finish(
      {
        [FAST_INDICATOR_NAME]: {
          fn: state.kind,
          src: "close",
          len: fastLength,
        },
        [SLOW_INDICATOR_NAME]: {
          fn: state.kind,
          src: "close",
          len: slowLength,
        },
      },
      [FAST_INDICATOR_NAME, state.entryComparison, SLOW_INDICATOR_NAME],
      [FAST_INDICATOR_NAME, state.exitComparison, SLOW_INDICATOR_NAME],
    );
  }
  if (state.recipe !== "close_vs_ma") {
    return null;
  }
  // Prefer preserving a single-indicator name from an imported pack when the
  // base is still that same close-vs-one shape; otherwise use the generated
  // `ma` name so fresh seeds stay stable.
  let indicatorName = INDICATOR_NAME;
  const baseIndicators = base.indicators;
  if (
    baseIndicators &&
    typeof baseIndicators === "object" &&
    !Array.isArray(baseIndicators)
  ) {
    const names = Object.keys(baseIndicators);
    if (names.length === 1 && typeof names[0] === "string") {
      indicatorName = names[0];
    }
  }
  return finish(
    {
      [indicatorName]: {
        fn: state.kind,
        src: "close",
        len: Number(state.length),
      },
    },
    ["close", state.entryComparison, indicatorName],
    ["close", state.exitComparison, indicatorName],
  );
}
