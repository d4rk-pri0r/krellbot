import { describe, expect, it } from "vitest";
import {
  INDICATOR_NAME,
  buildOwnedStrategyPack,
  readOwnedStrategy,
  seedOwnedStrategyForm,
  seedOwnedStrategyPack,
  validateOwnedStrategyField,
  type OwnedStrategyFormState,
} from "./ownedStrategy";
import type { Pack } from "./client";

const rehearsalPack: Pack = {
  schema_version: 1,
  id: "rehearsal-trend",
  version: "1.0.0",
  label: "Synthetic rehearsal trend follow",
  author: "krellbot",
  origin: "Bundled synthetic fixture. Not researched; not a live strategy.",
  timeframe: "1h",
  indicators: {
    sma3: { fn: "sma", src: "close", len: 3 },
  },
  entry: ["close", ">", "sma3"],
  exit: ["close", "<", "sma3"],
  risk: { max_account_pct: 25, stop: { type: "pct", pct: 5 } },
  markets: [{ venue: "kraken", pair: "SUIUSD" }],
};

describe("seedOwnedStrategyPack", () => {
  it("seeds a full valid pack: schema keys, one used indicator, leaf conditions, risk, market", () => {
    const pack = seedOwnedStrategyPack("My trend plan");
    expect(pack.schema_version).toBe(1);
    expect(pack.id).toMatch(/^[a-z0-9][a-z0-9-]{0,31}$/);
    expect(pack.version).toBe("1.0.0");
    expect(pack.label).toBe("My trend plan");
    expect(pack.author).toBe("local workstation");
    expect(pack.timeframe).toBe("1h");
    expect(Object.keys(pack.indicators ?? {})).toEqual([INDICATOR_NAME]);
    expect(pack.entry).toEqual(["close", ">", INDICATOR_NAME]);
    expect(pack.exit).toEqual(["close", "<", INDICATOR_NAME]);
    expect(pack.risk).toEqual({
      max_account_pct: 25,
      stop: { type: "pct", pct: 5 },
    });
    expect(pack.markets).toEqual([{ venue: "kraken", pair: "XXBTZUSD" }]);
    // No profit claim, no origin note asserting knowledge it cannot have.
    expect(pack.origin).toBeUndefined();
    expect(JSON.stringify(pack)).not.toMatch(/profit|backtest|live/i);
  });

  it("seeds distinct ids for repeated calls", () => {
    const a = seedOwnedStrategyPack("a");
    const b = seedOwnedStrategyPack("b");
    expect(a.id).not.toBe(b.id);
  });
});

describe("readOwnedStrategy", () => {
  it("round-trips a supported pack into form state", () => {
    const state = readOwnedStrategy(rehearsalPack);
    expect(state).toEqual<OwnedStrategyFormState>({
      name: "Synthetic rehearsal trend follow",
      id: "rehearsal-trend",
      pair: "SUIUSD",
      timeframe: "1h",
      kind: "sma",
      length: "3",
      entryComparison: ">",
      exitComparison: "<",
      maxAccountPct: "25",
      stopPct: "5",
    });
  });

  it("round-trips an ema pack with a crosses comparison", () => {
    const pack: Pack = {
      ...rehearsalPack,
      indicators: { ma: { fn: "ema", src: "close", len: 20 } },
      entry: ["close", "crosses_above", "ma"],
      exit: ["close", "crosses_below", "ma"],
    };
    const state = readOwnedStrategy(pack);
    expect(state?.kind).toBe("ema");
    expect(state?.length).toBe("20");
    expect(state?.entryComparison).toBe("crosses_above");
    expect(state?.exitComparison).toBe("crosses_below");
  });

  it("returns null for an unsupported imported pack (extra key)", () => {
    const unsupported: Pack = { ...rehearsalPack, leverage: 3 };
    expect(readOwnedStrategy(unsupported)).toBeNull();
  });

  it("returns null for a nested all/any condition pack", () => {
    const unsupported: Pack = {
      ...rehearsalPack,
      entry: { all: [["close", ">", "sma3"]] },
      exit: { any: [["close", "<", "sma3"]] },
    };
    expect(readOwnedStrategy(unsupported)).toBeNull();
  });

  it("returns null for multiple indicators or multiple markets", () => {
    expect(
      readOwnedStrategy({
        ...rehearsalPack,
        indicators: {
          sma3: { fn: "sma", src: "close", len: 3 },
          sma9: { fn: "sma", src: "close", len: 9 },
        },
        entry: ["close", ">", "sma9"],
        exit: ["close", "<", "sma9"],
      }),
    ).toBeNull();
    expect(
      readOwnedStrategy({
        ...rehearsalPack,
        markets: [
          { venue: "kraken", pair: "SUIUSD" },
          { venue: "coinbase", pair: "BTC-USD" },
        ],
      }),
    ).toBeNull();
  });

  it("returns null for an unsupported indicator fn (wma)", () => {
    expect(
      readOwnedStrategy({
        ...rehearsalPack,
        indicators: { wma5: { fn: "wma", src: "close", len: 5 } },
        entry: ["close", ">", "wma5"],
        exit: ["close", "<", "wma5"],
      }),
    ).toBeNull();
  });

  it("returns null for an atr stop (not the pct subset)", () => {
    expect(
      readOwnedStrategy({
        ...rehearsalPack,
        risk: {
          max_account_pct: 25,
          stop: { type: "atr", len: 14, mult: 2 },
        },
      }),
    ).toBeNull();
  });

  it("returns null for an unsupported non-kraken venue", () => {
    expect(
      readOwnedStrategy({
        ...rehearsalPack,
        markets: [{ venue: "coinbase", pair: "BTC-USD" }],
      }),
    ).toBeNull();
  });

  it("returns null when an operand is not close or the indicator", () => {
    expect(
      readOwnedStrategy({
        ...rehearsalPack,
        entry: ["high", ">", "sma3"],
      }),
    ).toBeNull();
    expect(
      readOwnedStrategy({
        ...rehearsalPack,
        exit: ["close", "<", 100],
      }),
    ).toBeNull();
  });
});

describe("buildOwnedStrategyPack", () => {
  it("builds a pack from valid form state, preserving seeded id and author", () => {
    const seeded = seedOwnedStrategyPack("Plan");
    const state = readOwnedStrategy(seeded);
    expect(state).not.toBeNull();
    const built = buildOwnedStrategyPack(state as OwnedStrategyFormState, seeded);
    expect(built).not.toBeNull();
    const pack = built as Pack;
    expect(pack.id).toBe(seeded.id);
    expect(pack.author).toBe(seeded.author);
    expect(pack.indicators).toEqual(seeded.indicators);
    expect(pack.entry).toEqual(["close", ">", INDICATOR_NAME]);
    expect(pack.exit).toEqual(["close", "<", INDICATOR_NAME]);
  });

  it("changing a parameter changes the real pack payload", () => {
    const seeded = seedOwnedStrategyPack("Plan");
    const state = readOwnedStrategy(seeded) as OwnedStrategyFormState;
    const edited: OwnedStrategyFormState = {
      ...state,
      length: "50",
      entryComparison: "crosses_above",
      maxAccountPct: "40",
      stopPct: "2.5",
      pair: "XETHZUSD",
    };
    const pack = buildOwnedStrategyPack(edited, seeded) as Pack;
    expect(pack.indicators).toEqual({
      [INDICATOR_NAME]: { fn: "sma", src: "close", len: 50 },
    });
    expect(pack.entry).toEqual(["close", "crosses_above", INDICATOR_NAME]);
    expect(pack.risk).toEqual({
      max_account_pct: 40,
      stop: { type: "pct", pct: 2.5 },
    });
    expect(pack.markets).toEqual([{ venue: "kraken", pair: "XETHZUSD" }]);
  });

  it("rejects an out-of-range length instead of generating an invalid pack", () => {
    const seeded = seedOwnedStrategyPack("Plan");
    const state = readOwnedStrategy(seeded) as OwnedStrategyFormState;
    expect(buildOwnedStrategyPack({ ...state, length: "1" }, seeded)).toBeNull();
    expect(buildOwnedStrategyPack({ ...state, length: "600" }, seeded)).toBeNull();
    expect(buildOwnedStrategyPack({ ...state, length: "1.5" }, seeded)).toBeNull();
    expect(buildOwnedStrategyPack({ ...state, length: "" }, seeded)).toBeNull();
  });

  it("rejects invalid risk values", () => {
    const seeded = seedOwnedStrategyPack("Plan");
    const state = readOwnedStrategy(seeded) as OwnedStrategyFormState;
    expect(buildOwnedStrategyPack({ ...state, maxAccountPct: "0" }, seeded)).toBeNull();
    expect(buildOwnedStrategyPack({ ...state, maxAccountPct: "101" }, seeded)).toBeNull();
    expect(buildOwnedStrategyPack({ ...state, stopPct: "0" }, seeded)).toBeNull();
    expect(buildOwnedStrategyPack({ ...state, stopPct: "100.5" }, seeded)).toBeNull();
    expect(buildOwnedStrategyPack({ ...state, stopPct: "abc" }, seeded)).toBeNull();
  });

  it("rejects an invalid id and an invalid pair", () => {
    const seeded = seedOwnedStrategyPack("Plan");
    const state = readOwnedStrategy(seeded) as OwnedStrategyFormState;
    expect(buildOwnedStrategyPack({ ...state, id: "Bad_ID" }, seeded)).toBeNull();
    expect(buildOwnedStrategyPack({ ...state, id: "" }, seeded)).toBeNull();
    expect(
      buildOwnedStrategyPack({ ...state, pair: "btc-usd!!" }, seeded),
    ).toBeNull();
  });

  it("rejects an empty label", () => {
    const seeded = seedOwnedStrategyPack("Plan");
    const state = readOwnedStrategy(seeded) as OwnedStrategyFormState;
    expect(buildOwnedStrategyPack({ ...state, name: "" }, seeded)).toBeNull();
    expect(
      buildOwnedStrategyPack({ ...state, name: "x".repeat(121) }, seeded),
    ).toBeNull();
  });
});

describe("validateOwnedStrategyField", () => {
  it("reports a message per invalid field and undefined for valid ones", () => {
    expect(validateOwnedStrategyField("length", "1")).toMatch(/2/);
    expect(validateOwnedStrategyField("length", "600")).toMatch(/599/);
    expect(validateOwnedStrategyField("length", "12")).toBeUndefined();
    expect(validateOwnedStrategyField("maxAccountPct", "0")).toMatch(/1/);
    expect(validateOwnedStrategyField("stopPct", "0")).toMatch(/0/);
    expect(validateOwnedStrategyField("id", "NO")).toMatch(/lowercase/);
    expect(validateOwnedStrategyField("pair", "nope!")).toMatch(/pair/i);
  });
});

describe("seedOwnedStrategyForm", () => {
  it("seeds a default form state with a valid name", () => {
    const state = seedOwnedStrategyForm();
    expect(state.name).toBe("Moving average plan");
    expect(validateOwnedStrategyField("name", state.name)).toBeUndefined();
    expect(buildOwnedStrategyPack(state, seedOwnedStrategyPack("Moving average plan"))).not.toBeNull();
  });
});
