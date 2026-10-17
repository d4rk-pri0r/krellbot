import { describe, expect, it } from "vitest";
import { explainPack, conditionSentence, type ConditionExplanation } from "./explainPack";

function isUnknownDeep(condition: ConditionExplanation): boolean {
  if (condition.kind === "unknown") {
    return true;
  }
  if (condition.kind === "group") {
    return condition.children.some((child) => isUnknownDeep(child));
  }
  return false;
}

const supportedPack = {
  schema_version: 1,
  id: "trend-follow",
  version: "1.0.0",
  label: "Trend follow",
  author: "krellbot tests",
  origin: "Test fixture.",
  timeframe: "1h",
  indicators: {
    sma20: { fn: "sma", src: "close", len: 20 },
    atr14: { fn: "atr", len: 14 },
    hi5: { fn: "highest", len: 5 },
    pm5: { fn: "power_mean", src: "close", len: 5, p: 2 },
  },
  entry: {
    all: [
      ["close", ">", "sma20"],
      { any: [["hi5", "crosses_above", "close"]] },
    ],
  },
  exit: ["close", "<", "sma20"],
  risk: {
    max_account_pct: 25,
    stop: { type: "pct", pct: 5 },
  },
  markets: [
    { venue: "kraken", pair: "SUIUSD" },
    { venue: "coinbase", pair: "BTC-USD" },
  ],
};

describe("explainPack supported packs", () => {
  it("reports the revision id and saved status from the caller", () => {
    const saved = explainPack(JSON.stringify(supportedPack), "rev-42");
    expect(saved.revisionId).toBe("rev-42");
    expect(saved.savedStatus).toBe("saved");

    const unsaved = explainPack(JSON.stringify(supportedPack), null);
    expect(unsaved.savedStatus).toBe("unsaved");
  });

  it("describes market, timeframe and metadata as supplied", () => {
    const result = explainPack(JSON.stringify(supportedPack), "rev-1");
    expect(result.parsed).toBe(true);
    expect(result.timeframe.text).toContain("1h");
    expect(result.markets.map((m) => m.text)).toEqual([
      "kraken: SUIUSD",
      "coinbase: BTC-USD",
    ]);
    expect(result.metadata.packId).toBe("trend-follow");
    expect(result.metadata.version).toBe("1.0.0");
    expect(result.metadata.author).toBe("krellbot tests");
    expect(result.metadata.origin).toBe("Test fixture.");
  });

  it("reads missing metadata as not supplied rather than inventing it", () => {
    const minimal = {
      ...supportedPack,
      origin: undefined,
      author: undefined,
      version: undefined,
    };
    const result = explainPack(JSON.stringify(minimal), "rev-2");
    expect(result.metadata.origin).toBeNull();
    expect(result.metadata.author).toBeNull();
    expect(result.metadata.version).toBeNull();
  });

  it("explains entry and exit rules with truthful comparisons", () => {
    const result = explainPack(JSON.stringify(supportedPack), "rev-1");
    expect(conditionSentence(result.entry)).toBe(
      "(the close price is greater than the indicator \"sma20\") and (the indicator \"hi5\" crosses above the close price).",
    );
    expect(conditionSentence(result.exit)).toBe(
      "the close price is less than the indicator \"sma20\".",
    );
    expect(result.hasUnknowns).toBe(false);
  });

  it("explains indicator function, length and source", () => {
    const result = explainPack(JSON.stringify(supportedPack), "rev-1");
    const texts = result.indicators.map((i) => i.text);
    expect(texts).toContain('"sma20" = sma of close over the last 20 bars');
    expect(texts).toContain('"atr14" = atr over the last 14 bars');
    expect(texts).toContain('"hi5" = highest of high (not supplied; engine default) over the last 5 bars');
    expect(texts).toContain('"pm5" = power_mean of close over the last 5 bars with power 2');
  });

  it("explains allocation and both stop types", () => {
    const pct = explainPack(JSON.stringify(supportedPack), "rev-1");
    expect(pct.allocation.text).toContain("at most 25% of the account");
    expect(pct.stop.text).toBe("a percentage stop 5% below the entry price");

    const atr = explainPack(
      JSON.stringify({
        ...supportedPack,
        risk: { max_account_pct: 10, stop: { type: "atr", len: 14, mult: 2 } },
      }),
      "rev-3",
    );
    expect(atr.stop.text).toBe(
      "an ATR stop 2 × the 14-bar average true range below the entry price",
    );
  });

  it("is deterministic: identical bytes produce identical explanations", () => {
    const bytes = JSON.stringify(supportedPack);
    expect(explainPack(bytes, "rev-9")).toEqual(explainPack(bytes, "rev-9"));
  });
});

describe("explainPack unsupported and malformed inputs", () => {
  it("marks unparseable bytes as not parsed without inventing rules", () => {
    const result = explainPack("{not json", "rev-bad");
    expect(result.parsed).toBe(false);
    expect(result.hasUnknowns).toBe(true);
  });

  it("marks a non-object root as not parsed", () => {
    const result = explainPack(JSON.stringify([1, 2, 3]), "rev-arr");
    expect(result.parsed).toBe(false);
  });

  it("reports an unknown comparison operator as unsupported", () => {
    const result = explainPack(
      JSON.stringify({ ...supportedPack, entry: ["close", "!=", "sma20"] }),
      "rev-x",
    );
    expect(result.entry.kind).toBe("unknown");
    expect(result.entry.text).toContain("unsupported operator");
    expect(result.hasUnknowns).toBe(true);
  });

  it("reports an unknown indicator function as unsupported with raw detail", () => {
    const result = explainPack(
      JSON.stringify({
        ...supportedPack,
        indicators: { weird: { fn: "magic", src: "close", len: 5 } },
      }),
      "rev-x",
    );
    const weird = result.indicators.find((i) => i.name === "weird");
    expect(weird?.supported).toBe(false);
    expect(weird?.text).toContain("magic");
  });

  it("reports an unknown stop type as unsupported", () => {
    const result = explainPack(
      JSON.stringify({
        ...supportedPack,
        risk: { max_account_pct: 25, stop: { type: "volatility" } },
      }),
      "rev-x",
    );
    expect(result.stop.supported).toBe(false);
    expect(result.stop.text).toContain("unsupported stop type");
  });

  it("reports missing risk metadata as unsupported, never as zero", () => {
    const result = explainPack(
      JSON.stringify({ ...supportedPack, risk: undefined }),
      "rev-x",
    );
    expect(result.allocation.text).not.toContain("0%");
    expect(result.allocation.supported).toBe(false);
  });

  it("reports an unsupported timeframe and venue without claiming them", () => {
    const result = explainPack(
      JSON.stringify({
        ...supportedPack,
        timeframe: "5m",
        markets: [{ venue: "binance", pair: "SUIUSDT" }],
      }),
      "rev-x",
    );
    expect(result.timeframe.supported).toBe(false);
    expect(result.markets[0].supported).toBe(false);
    expect(result.markets[0].text).toContain("unsupported market");
  });

  it("reports deep nesting as unsupported rather than guessing", () => {
    const deep = { all: [{ all: [{ all: [{ all: [["close", ">", "sma20"]] }] }] }] };
    const result = explainPack(
      JSON.stringify({ ...supportedPack, entry: deep }),
      "rev-x",
    );
    expect(isUnknownDeep(result.entry)).toBe(true);
    expect(conditionSentence(result.entry)).toContain("nested deeper");
  });

  it("still explains three-deep nesting, the DSL maximum", () => {
    const threeDeep = { all: [{ all: [["close", ">", "sma20"]] }] };
    const result = explainPack(
      JSON.stringify({ ...supportedPack, entry: threeDeep }),
      "rev-x",
    );
    expect(result.entry.kind).toBe("group");
    expect(result.hasUnknowns).toBe(false);
  });

  it("never produces a performance or cost claim", () => {
    const texts: string[] = [
      explainPack(JSON.stringify(supportedPack), "rev-1").allocation.text,
      explainPack(JSON.stringify(supportedPack), "rev-1").stop.text,
    ];
    for (const text of texts) {
      expect(text).not.toMatch(/return|profit|win rate|sharpe|backtest result/i);
    }
  });
});
