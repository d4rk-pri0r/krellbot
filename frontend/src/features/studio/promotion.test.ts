import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { promotionPin } from "./promotion";

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

describe("promotionPin: empty inputs", () => {
  it("returns a string for an empty pack", () => {
    expect(typeof promotionPin({})).toBe("string");
  });

  it("returns a non-empty string for an empty pack", () => {
    expect(promotionPin({}).length).toBeGreaterThan(0);
  });

  it("returns the same pin for two empty packs", () => {
    expect(promotionPin({})).toBe(promotionPin({}));
  });

  it("returns the same pin for an empty pack with only non-execution fields", () => {
    expect(promotionPin({})).toBe(
      promotionPin({ layout: "left", x: 0, y: 0, editor: "closed" }),
    );
  });
});

describe("promotionPin: determinism", () => {
  it("returns the same pin for identical inputs across calls", () => {
    const pack = fullExecution();
    expect(promotionPin(pack)).toBe(promotionPin({ ...pack }));
  });

  it("does not depend on insertion order of top-level keys", () => {
    const a: Record<string, unknown> = {
      schema_version: "1",
      id: "rev-1",
      timeframe: "1h",
      indicators: ["ema"],
      entry: { kind: "cross_above" },
      exit: { kind: "cross_below" },
      risk: { max_drawdown: 0.2 },
      markets: ["BTC-USD"],
    };
    const b: Record<string, unknown> = {
      markets: ["BTC-USD"],
      risk: { max_drawdown: 0.2 },
      exit: { kind: "cross_below" },
      entry: { kind: "cross_above" },
      indicators: ["ema"],
      timeframe: "1h",
      id: "rev-1",
      schema_version: "1",
    };
    expect(promotionPin(a)).toBe(promotionPin(b));
  });

  it("does not depend on insertion order of nested object keys", () => {
    const a = { entry: { kind: "cross_above", lhs: "ema_20", rhs: "ema_50" } };
    const b = { entry: { rhs: "ema_50", lhs: "ema_20", kind: "cross_above" } };
    expect(promotionPin(a)).toBe(promotionPin(b));
  });

  it("treats array order as significant", () => {
    const a = { indicators: ["ema", "atr"] };
    const b = { indicators: ["atr", "ema"] };
    expect(promotionPin(a)).not.toBe(promotionPin(b));
  });
});

describe("promotionPin: ignores non-execution fields", () => {
  it("does not change when layout changes", () => {
    expect(promotionPin({ layout: "left" })).toBe(
      promotionPin({ layout: "right" }),
    );
  });

  it("does not change when x changes", () => {
    expect(promotionPin({ x: 0 })).toBe(promotionPin({ x: 100 }));
  });

  it("does not change when y changes", () => {
    expect(promotionPin({ y: 0 })).toBe(promotionPin({ y: 200 }));
  });

  it("does not change when editor changes", () => {
    expect(promotionPin({ editor: "closed" })).toBe(
      promotionPin({ editor: "open" }),
    );
  });

  it("does not change when only non-execution fields change together", () => {
    const a = { layout: "left", x: 0, y: 0, editor: "closed" };
    const b = { layout: "right", x: 100, y: 200, editor: "open" };
    expect(promotionPin(a)).toBe(promotionPin(b));
  });

  it("ignores non-execution fields even when execution fields are also present", () => {
    const a = {
      schema_version: "1",
      entry: { kind: "cross_above" },
      layout: "left",
      x: 0,
      y: 0,
      editor: "closed",
    };
    const b = {
      schema_version: "1",
      entry: { kind: "cross_above" },
      layout: "right",
      x: 100,
      y: 200,
      editor: "open",
    };
    expect(promotionPin(a)).toBe(promotionPin(b));
  });

  it("ignores runtime fields (fill_price, equity, return_pct, pnl)", () => {
    const a = {
      schema_version: "1",
      entry: { kind: "cross_above" },
      fill_price: 100,
      equity: 1000,
      return_pct: 0.1,
      pnl: 50,
    };
    const b = {
      schema_version: "1",
      entry: { kind: "cross_above" },
      fill_price: 200,
      equity: 1500,
      return_pct: 0.25,
      pnl: 75,
    };
    expect(promotionPin(a)).toBe(promotionPin(b));
  });
});

describe("promotionPin: each execution field independently", () => {
  it("changes when schema_version changes", () => {
    expect(promotionPin({ schema_version: "1" })).not.toBe(
      promotionPin({ schema_version: "2" }),
    );
  });

  it("changes when id changes", () => {
    expect(promotionPin({ id: "rev-1" })).not.toBe(
      promotionPin({ id: "rev-2" }),
    );
  });

  it("changes when timeframe changes", () => {
    expect(promotionPin({ timeframe: "1h" })).not.toBe(
      promotionPin({ timeframe: "4h" }),
    );
  });

  it("changes when indicators changes", () => {
    expect(promotionPin({ indicators: ["ema"] })).not.toBe(
      promotionPin({ indicators: ["atr"] }),
    );
  });

  it("changes when entry changes", () => {
    expect(promotionPin({ entry: { kind: "cross_above" } })).not.toBe(
      promotionPin({ entry: { kind: "cross_below" } }),
    );
  });

  it("changes when exit changes", () => {
    expect(promotionPin({ exit: { kind: "cross_above" } })).not.toBe(
      promotionPin({ exit: { kind: "cross_below" } }),
    );
  });

  it("changes when risk changes", () => {
    expect(promotionPin({ risk: { max_drawdown: 0.2 } })).not.toBe(
      promotionPin({ risk: { max_drawdown: 0.3 } }),
    );
  });

  it("changes when markets changes", () => {
    expect(promotionPin({ markets: ["BTC-USD"] })).not.toBe(
      promotionPin({ markets: ["ETH-USD"] }),
    );
  });
});

describe("promotionPin: missing field is not equal to 0", () => {
  it("entry 0 differs from a missing entry", () => {
    expect(promotionPin({ entry: 0 })).not.toBe(promotionPin({}));
  });

  it("a missing entry with entry 0 on the other side differs in both directions", () => {
    expect(promotionPin({ entry: 0 })).not.toBe(promotionPin({}));
    expect(promotionPin({})).not.toBe(promotionPin({ entry: 0 }));
  });

  it("exit 0 differs from a missing exit", () => {
    expect(promotionPin({ exit: 0 })).not.toBe(promotionPin({}));
  });

  it("risk 0 differs from a missing risk", () => {
    expect(promotionPin({ risk: 0 })).not.toBe(promotionPin({}));
  });

  it("markets as an empty list differs from a missing markets", () => {
    expect(promotionPin({ markets: [] })).not.toBe(promotionPin({}));
  });

  it("indicators as an empty list differs from a missing indicators", () => {
    expect(promotionPin({ indicators: [] })).not.toBe(promotionPin({}));
  });

  it("timeframe empty string differs from a missing timeframe", () => {
    expect(promotionPin({ timeframe: "" })).not.toBe(promotionPin({}));
  });

  it("schema_version empty string differs from a missing schema_version", () => {
    expect(promotionPin({ schema_version: "" })).not.toBe(promotionPin({}));
  });

  it("id empty string differs from a missing id", () => {
    expect(promotionPin({ id: "" })).not.toBe(promotionPin({}));
  });

  it("entry 0 on both sides is the same pin", () => {
    expect(promotionPin({ entry: 0 })).toBe(promotionPin({ entry: 0 }));
  });

  it("entry null differs from entry 0", () => {
    expect(promotionPin({ entry: null })).not.toBe(promotionPin({ entry: 0 }));
  });

  it("entry null differs from a missing entry", () => {
    expect(promotionPin({ entry: null })).not.toBe(promotionPin({}));
  });
});

describe("promotionPin: result shape", () => {
  it("returns a string", () => {
    expect(typeof promotionPin({})).toBe("string");
    expect(typeof promotionPin(fullExecution())).toBe("string");
  });

  it("returns a non-empty string", () => {
    expect(promotionPin({}).length).toBeGreaterThan(0);
    expect(promotionPin(fullExecution()).length).toBeGreaterThan(0);
  });

  it("does not contain 'fill_price' when a runtime fill_price is present", () => {
    const pin = promotionPin({ entry: 0, fill_price: 100 });
    expect(pin).not.toContain("fill_price");
  });

  it("does not contain 'equity' when a runtime equity is present", () => {
    const pin = promotionPin({ entry: 0, equity: 1000 });
    expect(pin).not.toContain("equity");
  });

  it("does not contain 'return_pct' when a runtime return_pct is present", () => {
    const pin = promotionPin({ entry: 0, return_pct: 0.1 });
    expect(pin).not.toContain("return_pct");
  });

  it("does not contain 'pnl' when a runtime pnl is present", () => {
    const pin = promotionPin({ entry: 0, pnl: 50 });
    expect(pin).not.toContain("pnl");
  });

  it("does not contain 'fill_price' even when the value is a literal 'fill_price' string", () => {
    const pin = promotionPin({ fill_price: "fill_price" });
    expect(pin).not.toContain("fill_price");
  });

  it("does not contain 'fill_price' across all forbidden substrings at once", () => {
    const pin = promotionPin({
      schema_version: "1",
      id: "rev-1",
      timeframe: "1h",
      indicators: ["ema"],
      entry: { kind: "cross_above" },
      exit: { kind: "cross_below" },
      risk: { max_drawdown: 0.2 },
      markets: ["BTC-USD"],
      fill_price: 100,
      equity: 1000,
      return_pct: 0.1,
      pnl: 50,
    });
    expect(pin).not.toContain("fill_price");
    expect(pin).not.toContain("equity");
    expect(pin).not.toContain("return_pct");
    expect(pin).not.toContain("pnl");
  });
});

describe("promotionPin: side-effect freedom", () => {
  it("does not read localStorage when called", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem");
    promotionPin({});
    promotionPin(fullExecution());
    promotionPin({ entry: 0 });
    promotionPin({ fill_price: 100, equity: 1000, return_pct: 0.1, pnl: 50 });
    expect(spy).not.toHaveBeenCalled();
  });

  it("does not call fetch when called", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    promotionPin({});
    promotionPin(fullExecution());
    promotionPin({ entry: 0 });
    promotionPin({ fill_price: 100, equity: 1000, return_pct: 0.1, pnl: 50 });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("promotion.ts module surface", () => {
  it("does not import a graph library", () => {
    const source = readFileSync(resolve(here, "promotion.ts"), "utf8");
    expect(source).not.toMatch(/@xyflow\/react/);
    expect(source).not.toMatch(/from\s+["']reactflow["']/);
    expect(source).not.toMatch(/from\s+["']react-flow-renderer["']/);
    expect(source).not.toMatch(/from\s+["']d3["']/);
    expect(source).not.toMatch(/from\s+["']cytoscape["']/);
    expect(source).not.toMatch(/from\s+["']vis-network["']/);
  });

  it("does not import a network library", () => {
    const source = readFileSync(resolve(here, "promotion.ts"), "utf8");
    expect(source).not.toMatch(/from\s+["']axios["']/);
    expect(source).not.toMatch(/from\s+["']node-fetch["']/);
    expect(source).not.toMatch(/from\s+["']ky["']/);
  });

  it("does not import a storage library", () => {
    const source = readFileSync(resolve(here, "promotion.ts"), "utf8");
    expect(source).not.toMatch(/from\s+["']localforage["']/);
    expect(source).not.toMatch(/from\s+["']idb-keyval["']/);
  });
});
