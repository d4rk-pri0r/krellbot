/**
 * Pure, deterministic explanation of a saved strategy revision's stored pack
 * bytes. This describes what the stored JSON says — nothing more. It never
 * invents performance, costs, research results, or provenance, and it never
 * marks anything "valid" or "safe": unknown constructs are reported as
 * unsupported, with the raw detail shown safely as text.
 */

export const NOT_SUPPLIED = "not supplied";

export type OperandExplanation =
  | { kind: "price"; text: string }
  | { kind: "indicator"; text: string }
  | { kind: "number"; text: string }
  | { kind: "unknown"; text: string };

export type ConditionExplanation =
  | { kind: "leaf"; text: string }
  | { kind: "group"; text: string; joiner: "all" | "any"; children: ConditionExplanation[] }
  | { kind: "unknown"; text: string };

export type IndicatorExplanation = {
  name: string;
  text: string;
  supported: boolean;
};

export type MarketExplanation = {
  venue: string;
  pair: string;
  supported: boolean;
  text: string;
};

export type ExplainResult = {
  /** Revision the explanation was built from, as supplied. */
  revisionId: string | null;
  /** "saved" when a stored revision exists; "unsaved" otherwise. */
  savedStatus: "saved" | "unsaved";
  /** true when the bytes parsed as a JSON object. */
  parsed: boolean;
  /** Stored fields we can show but not verify. */
  metadata: {
    label: string | null;
    packId: string | null;
    version: string | null;
    author: string | null;
    origin: string | null;
  };
  timeframe: { text: string; supported: boolean };
  indicators: IndicatorExplanation[];
  entry: ConditionExplanation;
  exit: ConditionExplanation;
  markets: MarketExplanation[];
  allocation: { text: string; supported: boolean };
  stop: { text: string; supported: boolean };
  /** True when at least one construct was unsupported or malformed. */
  hasUnknowns: boolean;
  /** Number of characters of the stored bytes. */
  byteLength: number;
};

const PRICE_FIELDS = ["open", "high", "low", "close", "volume"] as const;
const KNOWN_OPERATORS = [">", "<", ">=", "<=", "crosses_above", "crosses_below"] as const;
const KNOWN_SOURCE_FNS = [
  "sma",
  "ema",
  "wma",
  "vwma",
  "stdev",
  "roc",
  "efficiency_ratio",
  "hma",
  "power_mean",
] as const;
const KNOWN_NO_SOURCE_FNS = ["atr"] as const;
const KNOWN_OPTIONAL_SOURCE_FNS = ["highest", "lowest"] as const;
const KNOWN_FNS = [
  ...KNOWN_SOURCE_FNS,
  ...KNOWN_NO_SOURCE_FNS,
  ...KNOWN_OPTIONAL_SOURCE_FNS,
  "roofing_filter",
] as const;
const KNOWN_VENUES = ["kraken", "coinbase"] as const;
const KNOWN_TIMEFRAMES = ["1h", "4h", "1d"] as const;

const OPERATOR_TEXT: Record<(typeof KNOWN_OPERATORS)[number], string> = {
  ">": "is greater than",
  "<": "is less than",
  ">=": "is at least",
  "<=": "is at most",
  crosses_above: "crosses above",
  crosses_below: "crosses below",
};

type Json = unknown;

function isRecord(value: Json): value is Record<string, Json> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function safelyStringify(value: Json): string {
  try {
    const text = JSON.stringify(value);
    if (typeof text === "string") {
      return text.length > 200 ? `${text.slice(0, 200)}…` : text;
    }
  } catch {
    // circular or otherwise unserializable; fall through
  }
  return String(value);
}

function formatNumber(value: number): string {
  return Number.isFinite(value) ? String(value) : safelyStringify(value);
}

function describeOperand(value: Json): OperandExplanation {
  if (typeof value === "string") {
    if ((PRICE_FIELDS as readonly string[]).includes(value)) {
      return { kind: "price", text: `the ${value} price` };
    }
    return { kind: "indicator", text: `the indicator "${value}"` };
  }
  if (typeof value === "number") {
    return { kind: "number", text: `the fixed number ${formatNumber(value)}` };
  }
  if (typeof value === "boolean" || value === null || typeof value === "undefined") {
    return { kind: "unknown", text: `an unusable value (${safelyStringify(value)})` };
  }
  return { kind: "unknown", text: `an unsupported value (${safelyStringify(value)})` };
}

function describeCondition(value: Json, depth: number): ConditionExplanation {
  if (Array.isArray(value)) {
    if (value.length !== 3) {
      return {
        kind: "unknown",
        text: `an unsupported condition (${safelyStringify(value)})`,
      };
    }
    const [left, op, right] = value;
    if (typeof op !== "string" || !(KNOWN_OPERATORS as readonly string[]).includes(op)) {
      return {
        kind: "unknown",
        text: `a comparison with an unsupported operator (${safelyStringify(op)})`,
      };
    }
    const operator = op as (typeof KNOWN_OPERATORS)[number];
    const leftText = describeOperand(left).text;
    const rightText = describeOperand(right).text;
    return {
      kind: "leaf",
      text: `${leftText} ${OPERATOR_TEXT[operator]} ${rightText}`,
    };
  }
  if (isRecord(value)) {
    const keys = Object.keys(value);
    if (keys.length !== 1 || (keys[0] !== "all" && keys[0] !== "any")) {
      return {
        kind: "unknown",
        text: `an unsupported grouping (${safelyStringify(value)})`,
      };
    }
    const joiner = keys[0] as "all" | "any";
    const list = value[joiner];
    if (!Array.isArray(list) || list.length === 0) {
      return {
        kind: "unknown",
        text: `a "${joiner}" grouping with an unsupported list (${safelyStringify(list)})`,
      };
    }
    if (depth >= 4) {
      return {
        kind: "unknown",
        text: `a "${joiner}" grouping nested deeper than the DSL allows (${safelyStringify(value)})`,
      };
    }
    const children = list.map((child) => describeCondition(child, depth + 1));
    return { kind: "group", text: "", joiner, children };
  }
  return {
    kind: "unknown",
    text: `an unsupported condition (${safelyStringify(value)})`,
  };
}

function flattenCondition(condition: ConditionExplanation): string {
  if (condition.kind === "group") {
    const joinerWord = condition.joiner === "all" ? "and" : "or";
    const parts = condition.children.map((child) => flattenCondition(child));
    const joined = parts.map((part) => `(${part})`).join(` ${joinerWord} `);
    // A single child adds no meaning; keep the text tight.
    return parts.length === 1 ? parts[0] : joined;
  }
  return condition.text;
}

function sentenceFor(condition: ConditionExplanation): string {
  const flat = flattenCondition(condition).trim();
  return flat.length > 0 ? `${flat}.` : "";
}

function isUnknownCondition(condition: ConditionExplanation): boolean {
  if (condition.kind === "unknown") {
    return true;
  }
  if (condition.kind === "group") {
    return condition.children.some((child) => isUnknownCondition(child));
  }
  return false;
}

function describeIndicator(name: string, value: Json): IndicatorExplanation {
  const base = { name };
  if (!isRecord(value)) {
    return { ...base, supported: false, text: `unsupported definition (${safelyStringify(value)})` };
  }
  const fn = value.fn;
  if (typeof fn !== "string" || !(KNOWN_FNS as readonly string[]).includes(fn)) {
    return {
      ...base,
      supported: false,
      text: `an unsupported function (${safelyStringify(fn)})`,
    };
  }
  const len = value.len;
  if (typeof len !== "number" || !Number.isInteger(len) || len < 2 || len > 600) {
    return {
      ...base,
      supported: false,
      text: `function "${fn}" with an unsupported length (${safelyStringify(len)})`,
    };
  }
  const needsSource = (KNOWN_SOURCE_FNS as readonly string[]).includes(fn);
  const optionalSource = (KNOWN_OPTIONAL_SOURCE_FNS as readonly string[]).includes(fn);
  const src = value.src;
  let sourceText: string;
  if (needsSource) {
    if (typeof src !== "string" || !(PRICE_FIELDS as readonly string[]).includes(src)) {
      return {
        ...base,
        supported: false,
        text: `function "${fn}" with an unsupported source (${safelyStringify(src)})`,
      };
    }
    sourceText = ` of ${src}`;
  } else if (optionalSource) {
    if (src === undefined) {
      const implied = fn === "highest" ? "high" : "low";
      sourceText = ` of ${implied} (not supplied; engine default)`;
    } else if (
      typeof src === "string" &&
      (PRICE_FIELDS as readonly string[]).includes(src)
    ) {
      sourceText = ` of ${src}`;
    } else {
      return {
        ...base,
        supported: false,
        text: `function "${fn}" with an unsupported source (${safelyStringify(src)})`,
      };
    }
  } else {
    // atr has no source; roofing_filter requires one.
    if (fn === "roofing_filter") {
      if (typeof src !== "string" || !(PRICE_FIELDS as readonly string[]).includes(src)) {
        return {
          ...base,
          supported: false,
          text: `function "${fn}" with an unsupported source (${safelyStringify(src)})`,
        };
      }
      sourceText = ` of ${src}`;
    } else {
      if (src !== undefined) {
        return {
          ...base,
          supported: false,
          text: `function "${fn}" with an unexpected source (${safelyStringify(src)})`,
        };
      }
      sourceText = "";
    }
  }
  let extras = "";
  if (fn === "power_mean") {
    const p = value.p;
    if (typeof p !== "number" || !Number.isFinite(p)) {
      return {
        ...base,
        supported: false,
        text: `function "${fn}" with an unsupported power (${safelyStringify(p)})`,
      };
    }
    extras = ` with power ${formatNumber(p)}`;
  }
  if (fn === "roofing_filter") {
    const smooth = value.smooth;
    if (smooth === undefined) {
      extras = " with smoothing not supplied";
    } else if (typeof smooth !== "number" || !Number.isInteger(smooth) || smooth < 2 || smooth > 600) {
      return {
        ...base,
        supported: false,
        text: `function "${fn}" with an unsupported smoothing (${safelyStringify(smooth)})`,
      };
    } else {
      extras = ` smoothed over ${smooth} bars`;
    }
  }
  return {
    ...base,
    supported: true,
    text: `"${name}" = ${fn}${sourceText} over the last ${len} bars${extras}`,
  };
}

function describeTimeframe(value: Json): { text: string; supported: boolean } {
  if (typeof value !== "string" || !(KNOWN_TIMEFRAMES as readonly string[]).includes(value)) {
    return { supported: false, text: `unsupported timeframe (${safelyStringify(value)})` };
  }
  const perBar = value === "1h" ? "hour" : value === "4h" ? "4 hours" : "day";
  return { supported: true, text: `${value} (one bar per ${perBar})` };
}

function describeMarkets(value: Json): MarketExplanation[] {
  if (!Array.isArray(value) || value.length === 0) {
    return [
      {
        venue: "",
        pair: "",
        supported: false,
        text: `no markets supplied (${safelyStringify(value)})`,
      },
    ];
  }
  return value.map((entry): MarketExplanation => {
    if (!isRecord(entry)) {
      return {
        venue: "",
        pair: "",
        supported: false,
        text: `an unsupported market entry (${safelyStringify(entry)})`,
      };
    }
    const venue = entry.venue;
    const pair = entry.pair;
    const venueOk = typeof venue === "string" && (KNOWN_VENUES as readonly string[]).includes(venue);
    const pairOk = typeof pair === "string" && /^[A-Z0-9]{2,16}(-[A-Z0-9]{2,16})?$/.test(pair);
    if (!venueOk || !pairOk) {
      return {
        venue: typeof venue === "string" ? venue : "",
        pair: typeof pair === "string" ? pair : "",
        supported: false,
        text: `an unsupported market (${safelyStringify(entry)})`,
      };
    }
    return {
      venue,
      pair,
      supported: true,
      text: `${venue}: ${pair}`,
    };
  });
}

function describeAllocation(value: Json): { text: string; supported: boolean } {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 1 ||
    value > 100
  ) {
    return {
      supported: false,
      text: `an unsupported maximum allocation (${safelyStringify(value)})`,
    };
  }
  return {
    supported: true,
    text: `at most ${value}% of the account per entry, sized on the entry fill price`,
  };
}

function describeStop(value: Json): { text: string; supported: boolean } {
  if (!isRecord(value)) {
    return { supported: false, text: `an unsupported stop (${safelyStringify(value)})` };
  }
  const type = value.type;
  if (type === "pct") {
    const pct = value.pct;
    if (typeof pct !== "number" || !(pct > 0) || pct > 100) {
      return {
        supported: false,
        text: `a percentage stop with an unsupported value (${safelyStringify(pct)})`,
      };
    }
    return {
      supported: true,
      text: `a percentage stop ${pct}% below the entry price`,
    };
  }
  if (type === "atr") {
    const len = value.len;
    const mult = value.mult;
    const lenOk = typeof len === "number" && Number.isInteger(len) && len >= 2 && len <= 600;
    const multOk = typeof mult === "number" && Number.isFinite(mult) && mult > 0 && mult <= 20;
    if (!lenOk || !multOk) {
      return {
        supported: false,
        text: `an ATR stop with unsupported values (len ${safelyStringify(len)}, mult ${safelyStringify(mult)})`,
      };
    }
    return {
      supported: true,
      text: `an ATR stop ${formatNumber(mult)} × the ${len}-bar average true range below the entry price`,
    };
  }
  return { supported: false, text: `an unsupported stop type (${safelyStringify(type)})` };
}

function readMetadataString(pack: Record<string, Json>, key: string): string | null {
  const value = pack[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

/**
 * Build the explanation from stored revision bytes. `revisionId` and
 * `savedStatus` come from the caller's saved-revision state; everything else
 * is derived purely from `bytes`.
 */
export function explainPack(bytes: string, revisionId: string | null): ExplainResult {
  const savedStatus = revisionId === null ? "unsaved" : "saved";
  let parsed = false;
  let pack: Record<string, Json> = {};
  try {
    const value = JSON.parse(bytes) as Json;
    if (isRecord(value)) {
      pack = value;
      parsed = true;
    }
  } catch {
    parsed = false;
  }

  const indicatorsInput = pack.indicators;
  let indicators: IndicatorExplanation[] = [];
  if (isRecord(indicatorsInput) && Object.keys(indicatorsInput).length > 0) {
    indicators = Object.entries(indicatorsInput).map(([name, value]) =>
      describeIndicator(name, value),
    );
  } else {
    indicators = [
      {
        name: "",
        supported: false,
        text: `no indicators supplied (${safelyStringify(indicatorsInput)})`,
      },
    ];
  }

  const timeframe = describeTimeframe(pack.timeframe);
  const entry = describeCondition(pack.entry, 1);
  const exit = describeCondition(pack.exit, 1);
  const markets = describeMarkets(pack.markets);
  const allocation = isRecord(pack.risk)
    ? describeAllocation(pack.risk.max_account_pct)
    : { supported: false, text: `an unsupported risk block (${safelyStringify(pack.risk)})` };
  const stop = isRecord(pack.risk)
    ? describeStop(pack.risk.stop)
    : { supported: false, text: `an unsupported risk block (${safelyStringify(pack.risk)})` };

  const hasUnknowns =
    !parsed ||
    !timeframe.supported ||
    isUnknownCondition(entry) ||
    isUnknownCondition(exit) ||
    markets.some((market) => !market.supported) ||
    !allocation.supported ||
    !stop.supported ||
    indicators.some((indicator) => !indicator.supported);

  return {
    revisionId,
    savedStatus,
    parsed,
    metadata: {
      label: readMetadataString(pack, "label"),
      packId: readMetadataString(pack, "id"),
      version: readMetadataString(pack, "version"),
      author: readMetadataString(pack, "author"),
      origin: readMetadataString(pack, "origin"),
    },
    timeframe,
    indicators,
    entry,
    exit,
    markets,
    allocation,
    stop,
    hasUnknowns,
    byteLength: bytes.length,
  };
}

/**
 * Render a condition as the sentence shown to the user. Group conditions are
 * joined with "and"/"or" reflecting the stored `all`/`any` joiner.
 */
export function conditionSentence(condition: ConditionExplanation): string {
  return sentenceFor(condition);
}
