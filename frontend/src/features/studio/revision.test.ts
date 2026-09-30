import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { semanticChanges } from "./revision";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function fullExecution(): Record<string, unknown> {
  return {
    schema_version: "1",
    id: "rev-1",
    timeframe: "1h",
    indicators: ["ema"],
    entry: { kind: "cross_above", lhs: "ema_20", rhs: "ema_50" },
    exit: { kind: "cross_below", lhs: "ema_20", rhs: "ema_50" },
    risk: { max_drawdown: 0.2 },
    markets: ["BTC-USD"],
  };
}

describe("semanticChanges: empty inputs", () => {
  it("returns an empty array when both sides are empty objects", () => {
    expect(semanticChanges({}, {})).toEqual([]);
  });

  it("returns an empty array when both sides are missing every execution field", () => {
    expect(semanticChanges({ layout: "left" }, { layout: "right" })).toEqual([]);
  });

  it("returns an empty array when both sides are deeply equal execution packs", () => {
    expect(semanticChanges(fullExecution(), fullExecution())).toEqual([]);
  });
});

describe("semanticChanges: each execution field independently", () => {
  it("reports schema_version when it changes", () => {
    const before = fullExecution();
    const after = fullExecution();
    (after as Record<string, unknown>).schema_version = "2";
    expect(semanticChanges(before, after)).toEqual(["schema_version"]);
  });

  it("reports id when it changes", () => {
    const before = fullExecution();
    const after = fullExecution();
    (after as Record<string, unknown>).id = "rev-2";
    expect(semanticChanges(before, after)).toEqual(["id"]);
  });

  it("reports timeframe when it changes", () => {
    const before = fullExecution();
    const after = fullExecution();
    (after as Record<string, unknown>).timeframe = "4h";
    expect(semanticChanges(before, after)).toEqual(["timeframe"]);
  });

  it("reports indicators when the list changes", () => {
    const before = fullExecution();
    const after = fullExecution();
    (after as Record<string, unknown>).indicators = ["ema", "atr"];
    expect(semanticChanges(before, after)).toEqual(["indicators"]);
  });

  it("reports entry when it changes", () => {
    const before = fullExecution();
    const after = fullExecution();
    (after as Record<string, unknown>).entry = {
      kind: "cross_below",
      lhs: "ema_20",
      rhs: "ema_50",
    };
    expect(semanticChanges(before, after)).toEqual(["entry"]);
  });

  it("reports exit when it changes", () => {
    const before = fullExecution();
    const after = fullExecution();
    (after as Record<string, unknown>).exit = {
      kind: "cross_above",
      lhs: "ema_20",
      rhs: "ema_50",
    };
    expect(semanticChanges(before, after)).toEqual(["exit"]);
  });

  it("reports risk when it changes", () => {
    const before = fullExecution();
    const after = fullExecution();
    (after as Record<string, unknown>).risk = { max_drawdown: 0.3 };
    expect(semanticChanges(before, after)).toEqual(["risk"]);
  });

  it("reports markets when the list changes", () => {
    const before = fullExecution();
    const after = fullExecution();
    (after as Record<string, unknown>).markets = ["BTC-USD", "ETH-USD"];
    expect(semanticChanges(before, after)).toEqual(["markets"]);
  });
});

describe("semanticChanges: non-execution fields are ignored", () => {
  it("does not report layout when it changes", () => {
    expect(
      semanticChanges({ layout: "left" }, { layout: "right" }),
    ).toEqual([]);
  });

  it("does not report x when it changes", () => {
    expect(semanticChanges({ x: 0 }, { x: 100 })).toEqual([]);
  });

  it("does not report y when it changes", () => {
    expect(semanticChanges({ y: 0 }, { y: 200 })).toEqual([]);
  });

  it("does not report editor when it changes", () => {
    expect(
      semanticChanges({ editor: "closed" }, { editor: "open" }),
    ).toEqual([]);
  });

  it("reports only the execution field when layout also changes", () => {
    const before = fullExecution();
    const after: Record<string, unknown> = {
      ...fullExecution(),
      layout: "right",
      x: 50,
      y: 75,
      editor: "open",
    };
    (after as Record<string, unknown>).entry = {
      kind: "cross_below",
      lhs: "ema_20",
      rhs: "ema_50",
    };
    expect(semanticChanges(before, after)).toEqual(["entry"]);
  });

  it("returns an empty array when only non-execution fields change", () => {
    expect(
      semanticChanges(
        { layout: "left", x: 0, y: 0, editor: "closed" },
        { layout: "right", x: 100, y: 200, editor: "open" },
      ),
    ).toEqual([]);
  });
});

describe("semanticChanges: missing fields are not equal to 0", () => {
  it("reports entry when it is 0 on one side and absent on the other", () => {
    expect(semanticChanges({ entry: 0 }, {})).toEqual(["entry"]);
    expect(semanticChanges({}, { entry: 0 })).toEqual(["entry"]);
  });

  it("reports exit when it is 0 on one side and absent on the other", () => {
    expect(semanticChanges({ exit: 0 }, {})).toEqual(["exit"]);
    expect(semanticChanges({}, { exit: 0 })).toEqual(["exit"]);
  });

  it("reports risk when it is 0 on one side and absent on the other", () => {
    expect(semanticChanges({ risk: 0 }, {})).toEqual(["risk"]);
    expect(semanticChanges({}, { risk: 0 })).toEqual(["risk"]);
  });

  it("reports markets when it is an empty list on one side and absent on the other", () => {
    expect(semanticChanges({ markets: [] }, {})).toEqual(["markets"]);
    expect(semanticChanges({}, { markets: [] })).toEqual(["markets"]);
  });

  it("reports indicators when it is an empty list on one side and absent on the other", () => {
    expect(semanticChanges({ indicators: [] }, {})).toEqual(["indicators"]);
    expect(semanticChanges({}, { indicators: [] })).toEqual(["indicators"]);
  });

  it("reports timeframe when it is the empty string on one side and absent on the other", () => {
    expect(semanticChanges({ timeframe: "" }, {})).toEqual(["timeframe"]);
    expect(semanticChanges({}, { timeframe: "" })).toEqual(["timeframe"]);
  });

  it("reports schema_version when it is the empty string on one side and absent on the other", () => {
    expect(semanticChanges({ schema_version: "" }, {})).toEqual([
      "schema_version",
    ]);
    expect(semanticChanges({}, { schema_version: "" })).toEqual([
      "schema_version",
    ]);
  });

  it("reports id when it is the empty string on one side and absent on the other", () => {
    expect(semanticChanges({ id: "" }, {})).toEqual(["id"]);
    expect(semanticChanges({}, { id: "" })).toEqual(["id"]);
  });

  it("does not report a field when it is absent on both sides", () => {
    expect(semanticChanges({}, {})).toEqual([]);
    expect(
      semanticChanges({ layout: "left" }, { editor: "open" }),
    ).toEqual([]);
  });

  it("does not report entry when both sides have the value 0", () => {
    expect(semanticChanges({ entry: 0 }, { entry: 0 })).toEqual([]);
  });
});

describe("semanticChanges: sorted output for multiple changes", () => {
  it("returns the names in alphabetical order across the full field set", () => {
    const before = fullExecution();
    const after: Record<string, unknown> = { ...fullExecution() };
    (after as Record<string, unknown>).markets = ["ETH-USD"];
    (after as Record<string, unknown>).entry = {
      kind: "cross_below",
      lhs: "ema_20",
      rhs: "ema_50",
    };
    (after as Record<string, unknown>).indicators = ["atr"];
    (after as Record<string, unknown>).id = "rev-2";
    (after as Record<string, unknown>).schema_version = "2";
    expect(semanticChanges(before, after)).toEqual([
      "entry",
      "id",
      "indicators",
      "markets",
      "schema_version",
    ]);
  });

  it("returns the names in alphabetical order for two changes", () => {
    expect(semanticChanges({ entry: 0 }, { exit: 0 })).toEqual(["entry", "exit"]);
    expect(semanticChanges({ exit: 0 }, { entry: 0 })).toEqual(["entry", "exit"]);
  });

  it("returns the names in alphabetical order when fields appear in reverse order", () => {
    const after: Record<string, unknown> = { ...fullExecution() };
    (after as Record<string, unknown>).timeframe = "4h";
    (after as Record<string, unknown>).schema_version = "2";
    (after as Record<string, unknown>).risk = { max_drawdown: 0.5 };
    const before = fullExecution();
    expect(semanticChanges(before, after)).toEqual([
      "risk",
      "schema_version",
      "timeframe",
    ]);
  });
});

describe("semanticChanges: result shape", () => {
  it("returns an array", () => {
    expect(Array.isArray(semanticChanges({}, {}))).toBe(true);
  });

  it("returns an array of strings only", () => {
    const result = semanticChanges({ entry: 0 }, { exit: 0 });
    for (const name of result) {
      expect(typeof name).toBe("string");
    }
  });

  it("never returns the literal 'fill_price' as a field name", () => {
    const result = semanticChanges(
      { fill_price: 100, entry: 0 },
      { fill_price: 200, entry: 0 },
    );
    expect(result).not.toContain("fill_price");
  });

  it("never returns 'equity' as a field name", () => {
    const result = semanticChanges(
      { equity: 100, entry: 0 },
      { equity: 200, entry: 0 },
    );
    expect(result).not.toContain("equity");
  });

  it("never returns 'return_pct' as a field name", () => {
    const result = semanticChanges(
      { return_pct: 0.1, entry: 0 },
      { return_pct: 0.2, entry: 0 },
    );
    expect(result).not.toContain("return_pct");
  });

  it("never returns 'pnl' as a field name", () => {
    const result = semanticChanges(
      { pnl: 10, entry: 0 },
      { pnl: 20, entry: 0 },
    );
    expect(result).not.toContain("pnl");
  });

  it("returns an empty array (no sentinel values) when only runtime fields differ", () => {
    expect(
      semanticChanges(
        { fill_price: 100, equity: 1000, return_pct: 0.1, pnl: 50 },
        { fill_price: 200, equity: 1500, return_pct: 0.2, pnl: 75 },
      ),
    ).toEqual([]);
  });
});

describe("semanticChanges: side-effect freedom", () => {
  it("does not read localStorage when called", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem");
    semanticChanges(fullExecution(), fullExecution());
    semanticChanges({ entry: 0 }, { exit: 0 });
    semanticChanges({ layout: "left" }, { layout: "right" });
    expect(spy).not.toHaveBeenCalled();
  });

  it("does not call fetch when called", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    semanticChanges(fullExecution(), fullExecution());
    semanticChanges({ entry: 0 }, { exit: 0 });
    semanticChanges({ layout: "left" }, { layout: "right" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("revision.ts module surface", () => {
  it("does not import a graph library", () => {
    const source = readFileSync(resolve(here, "revision.ts"), "utf8");
    expect(source).not.toMatch(/@xyflow\/react/);
    expect(source).not.toMatch(/from\s+["']reactflow["']/);
    expect(source).not.toMatch(/from\s+["']react-flow-renderer["']/);
    expect(source).not.toMatch(/from\s+["']d3["']/);
    expect(source).not.toMatch(/from\s+["']cytoscape["']/);
    expect(source).not.toMatch(/from\s+["']vis-network["']/);
  });

  it("does not import a network library", () => {
    const source = readFileSync(resolve(here, "revision.ts"), "utf8");
    expect(source).not.toMatch(/from\s+["']axios["']/);
    expect(source).not.toMatch(/from\s+["']node-fetch["']/);
    expect(source).not.toMatch(/from\s+["']ky["']/);
  });

  it("does not import a storage library", () => {
    const source = readFileSync(resolve(here, "revision.ts"), "utf8");
    expect(source).not.toMatch(/from\s+["']localforage["']/);
    expect(source).not.toMatch(/from\s+["']idb-keyval["']/);
  });
});