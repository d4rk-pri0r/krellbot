import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { observeNode } from "./observe";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("observeNode: missing bar_index", () => {
  it("returns 'bar missing' when bar_index is undefined", () => {
    expect(observeNode({}, 10)).toEqual({
      available: false,
      reason: "bar missing",
    });
  });

  it("returns 'bar missing' when bar_index is null", () => {
    expect(observeNode({ bar_index: null }, 10)).toEqual({
      available: false,
      reason: "bar missing",
    });
  });

  it("returns 'bar missing' when bar_index key is absent", () => {
    expect(observeNode({ fn: "ema" }, 10)).toEqual({
      available: false,
      reason: "bar missing",
    });
  });

  it("does not treat undefined bar_index as bar 0", () => {
    const result = observeNode({}, 0);
    expect(result).toEqual({ available: false, reason: "bar missing" });
    expect(result).not.toEqual({ available: true, checkpoint: "present" });
    expect(result).not.toMatchObject({ reason: "future bar" });
  });

  it("returns 'bar missing' even when decisionBar is negative", () => {
    expect(observeNode({}, -100)).toEqual({
      available: false,
      reason: "bar missing",
    });
  });

  it("returns 'bar missing' before checking fn or checkpoint", () => {
    expect(
      observeNode({ fn: "ema", bar_index: undefined }, 0),
    ).toEqual({ available: false, reason: "bar missing" });
  });
});

describe("observeNode: future bar", () => {
  it("returns 'future bar' when bar_index is greater than decisionBar", () => {
    expect(observeNode({ bar_index: 11 }, 10)).toEqual({
      available: false,
      reason: "future bar",
    });
  });

  it("returns 'future bar' when bar_index is one above decisionBar", () => {
    expect(observeNode({ bar_index: 1 }, 0)).toEqual({
      available: false,
      reason: "future bar",
    });
  });

  it("returns 'future bar' regardless of how far ahead the bar is", () => {
    expect(observeNode({ bar_index: 1000 }, 10)).toEqual({
      available: false,
      reason: "future bar",
    });
  });

  it("returns 'future bar' even for non-stateful fns", () => {
    expect(
      observeNode({ fn: "sma", bar_index: 100 }, 10),
    ).toEqual({ available: false, reason: "future bar" });
  });

  it("returns 'future bar' before the checkpoint check for stateful fns", () => {
    expect(
      observeNode({ fn: "ema", bar_index: 100 }, 10),
    ).toEqual({ available: false, reason: "future bar" });
  });

  it("does not include a checkpoint field on a future bar", () => {
    const result = observeNode({ bar_index: 100 }, 10);
    expect(result).not.toHaveProperty("checkpoint");
  });
});

describe("observeNode: closed bar", () => {
  it("treats bar_index equal to decisionBar as closed", () => {
    expect(observeNode({ bar_index: 10 }, 10)).toEqual({
      available: true,
      checkpoint: "present",
    });
  });

  it("treats bar_index less than decisionBar as closed", () => {
    expect(observeNode({ bar_index: 5 }, 10)).toEqual({
      available: true,
      checkpoint: "present",
    });
  });

  it("treats bar_index zero with non-negative decisionBar as closed", () => {
    expect(observeNode({ bar_index: 0 }, 0)).toEqual({
      available: true,
      checkpoint: "present",
    });
  });
});

describe("observeNode: stateful fn with missing checkpoint", () => {
  it("returns checkpoint: 'missing' for ema with undefined checkpoint", () => {
    expect(observeNode({ fn: "ema", bar_index: 5 }, 10)).toEqual({
      available: false,
      reason: "checkpoint missing",
      checkpoint: "missing",
    });
  });

  it("returns checkpoint: 'missing' for atr with undefined checkpoint", () => {
    expect(observeNode({ fn: "atr", bar_index: 5 }, 10)).toEqual({
      available: false,
      reason: "checkpoint missing",
      checkpoint: "missing",
    });
  });

  it("returns checkpoint: 'missing' for roofing_filter with undefined checkpoint", () => {
    expect(
      observeNode({ fn: "roofing_filter", bar_index: 5 }, 10),
    ).toEqual({
      available: false,
      reason: "checkpoint missing",
      checkpoint: "missing",
    });
  });

  it("treats null checkpoint as missing for stateful fns", () => {
    expect(
      observeNode({ fn: "ema", bar_index: 5, checkpoint: null }, 10),
    ).toEqual({
      available: false,
      reason: "checkpoint missing",
      checkpoint: "missing",
    });
  });

  it("does not store 0 as a sentinel for a missing checkpoint", () => {
    const result = observeNode({ fn: "ema", bar_index: 5 }, 10);
    expect(result).toMatchObject({ checkpoint: "missing" });
    expect(result).not.toMatchObject({ checkpoint: 0 });
    expect(result).not.toHaveProperty("checkpoint", 0);
  });

  it("treats bar_index zero on a stateful fn with missing checkpoint as missing", () => {
    expect(observeNode({ fn: "ema", bar_index: 0 }, 0)).toEqual({
      available: false,
      reason: "checkpoint missing",
      checkpoint: "missing",
    });
  });

  it("returns 'checkpoint missing' before treating missing as bar 0", () => {
    expect(
      observeNode({ fn: "ema" }, 0),
    ).toEqual({ available: false, reason: "bar missing" });
  });
});

describe("observeNode: closed bar with dict checkpoint", () => {
  it("returns available: true and checkpoint: 'present' for ema with dict checkpoint", () => {
    expect(
      observeNode(
        { fn: "ema", bar_index: 5, checkpoint: { value: 42 } },
        10,
      ),
    ).toEqual({ available: true, checkpoint: "present" });
  });

  it("returns available: true and checkpoint: 'present' for atr with dict checkpoint", () => {
    expect(
      observeNode(
        { fn: "atr", bar_index: 5, checkpoint: { value: 1.5 } },
        10,
      ),
    ).toEqual({ available: true, checkpoint: "present" });
  });

  it("returns available: true and checkpoint: 'present' for roofing_filter with dict checkpoint", () => {
    expect(
      observeNode(
        { fn: "roofing_filter", bar_index: 5, checkpoint: { state: "warm" } },
        10,
      ),
    ).toEqual({ available: true, checkpoint: "present" });
  });

  it("returns available: true for roofing_filter with an empty dict checkpoint", () => {
    expect(
      observeNode(
        { fn: "roofing_filter", bar_index: 5, checkpoint: {} },
        10,
      ),
    ).toEqual({ available: true, checkpoint: "present" });
  });

  it("does not store a numeric 0 checkpoint as present", () => {
    expect(
      observeNode({ fn: "ema", bar_index: 5, checkpoint: 0 }, 10),
    ).toEqual({
      available: false,
      reason: "checkpoint missing",
      checkpoint: "missing",
    });
  });

  it("does not store an empty-string checkpoint as present", () => {
    expect(
      observeNode({ fn: "atr", bar_index: 5, checkpoint: "" }, 10),
    ).toEqual({
      available: false,
      reason: "checkpoint missing",
      checkpoint: "missing",
    });
  });
});

describe("observeNode: non-stateful fn", () => {
  it("does not require a checkpoint for a closed bar with no fn", () => {
    expect(observeNode({ bar_index: 5 }, 10)).toEqual({
      available: true,
      checkpoint: "present",
    });
  });

  it("does not require a checkpoint for sma on a closed bar", () => {
    expect(observeNode({ fn: "sma", bar_index: 5 }, 10)).toEqual({
      available: true,
      checkpoint: "present",
    });
  });

  it("does not require a checkpoint for rsi on a closed bar", () => {
    expect(observeNode({ fn: "rsi", bar_index: 5 }, 10)).toEqual({
      available: true,
      checkpoint: "present",
    });
  });

  it("does not require a checkpoint for an unknown fn name", () => {
    expect(
      observeNode({ fn: "made_up_indicator", bar_index: 5 }, 10),
    ).toEqual({ available: true, checkpoint: "present" });
  });
});

describe("observeNode: result shape", () => {
  it("never includes a fill_price field on a missing bar", () => {
    const result = observeNode({}, 10);
    expect("fill_price" in result).toBe(false);
    expect(result).not.toHaveProperty("fill_price");
  });

  it("never includes a fill_price field on a future bar", () => {
    const result = observeNode({ bar_index: 100 }, 10);
    expect("fill_price" in result).toBe(false);
    expect(result).not.toHaveProperty("fill_price");
  });

  it("never includes a fill_price field on a missing-checkpoint result", () => {
    const result = observeNode({ fn: "ema", bar_index: 5 }, 10);
    expect("fill_price" in result).toBe(false);
    expect(result).not.toHaveProperty("fill_price");
  });

  it("never includes a fill_price field on an available result", () => {
    const result = observeNode(
      { fn: "ema", bar_index: 5, checkpoint: {} },
      10,
    );
    expect("fill_price" in result).toBe(false);
    expect(result).not.toHaveProperty("fill_price");
  });

  it("does not read localStorage across all branches", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem");
    observeNode({}, 10);
    observeNode({ bar_index: 100 }, 10);
    observeNode({ fn: "ema", bar_index: 5 }, 10);
    observeNode({ fn: "ema", bar_index: 5, checkpoint: {} }, 10);
    observeNode({ fn: "ema", bar_index: 5, checkpoint: null }, 10);
    observeNode({ bar_index: 0 }, 0);
    expect(spy).not.toHaveBeenCalled();
  });

  it("does not call fetch across all branches", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    observeNode({}, 10);
    observeNode({ bar_index: 100 }, 10);
    observeNode({ fn: "ema", bar_index: 5 }, 10);
    observeNode({ fn: "ema", bar_index: 5, checkpoint: {} }, 10);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns plain objects (no class instances) for every branch", () => {
    const results = [
      observeNode({}, 10),
      observeNode({ bar_index: 100 }, 10),
      observeNode({ fn: "ema", bar_index: 5 }, 10),
      observeNode({ fn: "ema", bar_index: 5, checkpoint: {} }, 10),
    ];
    for (const result of results) {
      expect(Object.getPrototypeOf(result)).toBe(Object.prototype);
    }
  });
});

describe("observe.ts module surface", () => {
  it("does not import a graph library", () => {
    const source = readFileSync(resolve(here, "observe.ts"), "utf8");
    expect(source).not.toMatch(/@xyflow\/react/);
    expect(source).not.toMatch(/from\s+["']reactflow["']/);
    expect(source).not.toMatch(/from\s+["']react-flow-renderer["']/);
    expect(source).not.toMatch(/from\s+["']d3["']/);
    expect(source).not.toMatch(/from\s+["']cytoscape["']/);
    expect(source).not.toMatch(/from\s+["']vis-network["']/);
  });

  it("does not import a network or fetch library", () => {
    const source = readFileSync(resolve(here, "observe.ts"), "utf8");
    expect(source).not.toMatch(/from\s+["']axios["']/);
    expect(source).not.toMatch(/from\s+["']node-fetch["']/);
    expect(source).not.toMatch(/from\s+["']ky["']/);
  });

  it("does not import a storage library", () => {
    const source = readFileSync(resolve(here, "observe.ts"), "utf8");
    expect(source).not.toMatch(/from\s+["']localforage["']/);
    expect(source).not.toMatch(/from\s+["']idb-keyval["']/);
  });
});
