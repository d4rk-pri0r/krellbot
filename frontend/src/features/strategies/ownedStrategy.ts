// Owned-strategy form model.
//
// This is a deliberately narrow, supported subset of the Pack DSL
// (src/krellbot/pack/schema.json): one moving-average indicator over close,
// leaf `close <op> <indicator>` entry and exit conditions, a percentage
// protective stop, and a single Kraken market. Anything else — imported
// packs with nested conditions, extra indicators, other venues or stop
// kinds — is reported as unsupported (`readOwnedStrategy` returns null) so
// the editor never silently rewrites or strips it.

import type { Pack } from "./client";

export const INDICATOR_NAME = "ma";

export const TIMEFRAMES = ["1h", "4h", "1d"] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];

export const MOVING_AVERAGE_KINDS = ["sma", "ema"] as const;
export type MovingAverageKind = (typeof MOVING_AVERAGE_KINDS)[number];

export const COMPARISONS = [
  ">",
  "<",
  ">=",
  "<=",
  "crosses_above",
  "crosses_below",
] as const;
export type Comparison = (typeof COMPARISONS)[number];

export type OwnedStrategyField =
  | "name"
  | "id"
  | "pair"
  | "timeframe"
  | "kind"
  | "length"
  | "entryComparison"
  | "exitComparison"
  | "maxAccountPct"
  | "stopPct";

export type OwnedStrategyFormState = {
  name: string;
  id: string;
  pair: string;
  timeframe: Timeframe;
  kind: MovingAverageKind;
  length: string;
  entryComparison: Comparison;
  exitComparison: Comparison;
  maxAccountPct: string;
  stopPct: string;
};

// Bounds mirror schema.json plus pack/lint.py's lookback budget
// (lookback len + 1 <= 600, so len 600 would fail lint even though the
// schema alone accepts it).
const LENGTH_MIN = 2;
const LENGTH_MAX = 599;
const NAME_MAX = 120;
const AUTHOR_MAX = 120;
const DEFAULT_AUTHOR = "local workstation";
const DEFAULT_PAIR = "XXBTZUSD";
const DEFAULT_TIMEFRAME: Timeframe = "1h";

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
      if (!PAIR_PATTERN.test(value)) {
        return "Pair must be uppercase like XXBTZUSD";
      }
      return undefined;
    case "length":
      if (!integerIn(value, LENGTH_MIN, LENGTH_MAX)) {
        return `Length must be a whole number between ${LENGTH_MIN} and ${LENGTH_MAX}`;
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

export function seedOwnedStrategyForm(): OwnedStrategyFormState {
  return {
    name: "Moving average plan",
    id: slugify("moving-average-plan"),
    pair: DEFAULT_PAIR,
    timeframe: DEFAULT_TIMEFRAME,
    kind: "sma",
    length: "20",
    entryComparison: ">",
    exitComparison: "<",
    maxAccountPct: "25",
    stopPct: "5",
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

type LeafCondition = [string, Comparison, string];

function isLeafCondition(value: unknown): value is LeafCondition {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    typeof value[0] === "string" &&
    typeof value[2] === "string" &&
    isComparison(value[1])
  );
}

/**
 * Read a pack into form state only when it is exactly the supported subset.
 * Anything unsupported returns null so callers keep the original bytes
 * untouched instead of guessing at a partial edit.
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
    Object.keys(indicators).length !== 1 ||
    !Array.isArray(markets) ||
    markets.length !== 1 ||
    !markets[0] ||
    typeof markets[0] !== "object"
  ) {
    return null;
  }
  const market = markets[0] as { venue?: unknown; pair?: unknown };
  if (market.venue !== "kraken" || typeof market.pair !== "string") {
    return null;
  }
  const indicatorName = Object.keys(indicators)[0];
  const indicator = (indicators as Record<string, unknown>)[indicatorName];
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
  if (!isLeafCondition(entry) || !isLeafCondition(exit)) {
    return null;
  }
  if (entry[0] !== "close" || entry[2] !== indicatorName) {
    return null;
  }
  if (exit[0] !== "close" || exit[2] !== indicatorName) {
    return null;
  }
  if (!risk || typeof risk !== "object" || Array.isArray(risk)) {
    return null;
  }
  const riskRow = risk as {
    max_account_pct?: unknown;
    stop?: unknown;
  };
  const stop = riskRow.stop as { type?: unknown; pct?: unknown } | undefined;
  if (
    typeof riskRow.max_account_pct !== "number" ||
    !Number.isInteger(riskRow.max_account_pct) ||
    riskRow.max_account_pct < 1 ||
    riskRow.max_account_pct > 100 ||
    !stop ||
    stop.type !== "pct" ||
    typeof stop.pct !== "number" ||
    !Number.isFinite(stop.pct) ||
    stop.pct <= 0 ||
    stop.pct > 100 ||
    Object.keys(riskRow).length !== 2 ||
    Object.keys(stop).length !== 2
  ) {
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
  return {
    name,
    id,
    pair: market.pair,
    timeframe,
    kind: params.fn,
    length: String(params.len),
    entryComparison: entry[1],
    exitComparison: exit[1],
    maxAccountPct: String(riskRow.max_account_pct),
    stopPct: String(stop.pct),
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
    "length",
    "maxAccountPct",
    "stopPct",
  ];
  for (const field of fields) {
    if (validateOwnedStrategyField(field, state[field]) !== undefined) {
      return null;
    }
  }
  if (!isTimeframe(state.timeframe) || !isKind(state.kind)) {
    return null;
  }
  if (!isComparison(state.entryComparison) || !isComparison(state.exitComparison)) {
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
  return {
    schema_version: 1,
    id: state.id,
    version,
    label: state.name,
    author,
    ...(typeof base.origin === "string" ? { origin: base.origin } : {}),
    timeframe: state.timeframe,
    indicators: {
      [INDICATOR_NAME]: {
        fn: state.kind,
        src: "close",
        len: Number(state.length),
      },
    },
    entry: ["close", state.entryComparison, INDICATOR_NAME],
    exit: ["close", state.exitComparison, INDICATOR_NAME],
    risk: {
      max_account_pct: Number(state.maxAccountPct),
      stop: { type: "pct", pct: Number(state.stopPct) },
    },
    markets: [{ venue: "kraken", pair: state.pair }],
  };
}
