import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { refuseIncompatibleEdge } from "./edges";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("refuseIncompatibleEdge: matching legal timeframes", () => {
  it("returns null when both endpoints share 1h", () => {
    expect(
      refuseIncompatibleEdge({ timeframe: "1h" }, { timeframe: "1h" }),
    ).toBeNull();
  });

  it("returns null when both endpoints share 4h", () => {
    expect(
      refuseIncompatibleEdge({ timeframe: "4h" }, { timeframe: "4h" }),
    ).toBeNull();
  });

  it("returns null when both endpoints share 1d", () => {
    expect(
      refuseIncompatibleEdge({ timeframe: "1d" }, { timeframe: "1d" }),
    ).toBeNull();
  });
});

describe("refuseIncompatibleEdge: different legal timeframes", () => {
  it("returns 'timeframe mismatch' for 1h vs 4h", () => {
    expect(
      refuseIncompatibleEdge({ timeframe: "1h" }, { timeframe: "4h" }),
    ).toBe("timeframe mismatch");
  });

  it("returns 'timeframe mismatch' for 4h vs 1d", () => {
    expect(
      refuseIncompatibleEdge({ timeframe: "4h" }, { timeframe: "1d" }),
    ).toBe("timeframe mismatch");
  });

  it("returns 'timeframe mismatch' for 1h vs 1d", () => {
    expect(
      refuseIncompatibleEdge({ timeframe: "1h" }, { timeframe: "1d" }),
    ).toBe("timeframe mismatch");
  });

  it("returns 'timeframe mismatch' regardless of argument order", () => {
    expect(
      refuseIncompatibleEdge({ timeframe: "4h" }, { timeframe: "1h" }),
    ).toBe("timeframe mismatch");
    expect(
      refuseIncompatibleEdge({ timeframe: "1d" }, { timeframe: "4h" }),
    ).toBe("timeframe mismatch");
  });
});

describe("refuseIncompatibleEdge: missing timeframe", () => {
  it("returns 'timeframe missing' when source has no timeframe and target is 1h", () => {
    expect(
      refuseIncompatibleEdge({}, { timeframe: "1h" }),
    ).toBe("timeframe missing");
  });

  it("returns 'timeframe missing' when target has no timeframe and source is 1h", () => {
    expect(
      refuseIncompatibleEdge({ timeframe: "1h" }, {}),
    ).toBe("timeframe missing");
  });

  it("returns 'timeframe missing' when both endpoints lack a timeframe", () => {
    expect(refuseIncompatibleEdge({}, {})).toBe("timeframe missing");
  });

  it("treats an explicit undefined timeframe as missing and does not default to 1h", () => {
    expect(
      refuseIncompatibleEdge({ timeframe: undefined }, { timeframe: "1h" }),
    ).toBe("timeframe missing");
    expect(
      refuseIncompatibleEdge({ timeframe: "1h" }, { timeframe: undefined }),
    ).toBe("timeframe missing");
  });

  it("does not return false for a missing timeframe", () => {
    const result = refuseIncompatibleEdge({}, { timeframe: "1h" });
    expect(result).not.toBe(false);
    expect(typeof result).toBe("string");
  });

  it("does not return 0 for a missing timeframe", () => {
    const result = refuseIncompatibleEdge({}, { timeframe: "1h" });
    expect(result).not.toBe(0);
    expect(typeof result).toBe("string");
  });

  it("does not coerce a missing timeframe to 1h when paired with 4h", () => {
    expect(
      refuseIncompatibleEdge({}, { timeframe: "4h" }),
    ).toBe("timeframe missing");
    expect(
      refuseIncompatibleEdge({ timeframe: "1d" }, {}),
    ).toBe("timeframe missing");
  });
});

describe("refuseIncompatibleEdge: side-effect freedom", () => {
  it("does not read localStorage when called", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem");
    refuseIncompatibleEdge({ timeframe: "1h" }, { timeframe: "1h" });
    refuseIncompatibleEdge({}, { timeframe: "1h" });
    refuseIncompatibleEdge({ timeframe: "1h" }, { timeframe: "4h" });
    expect(spy).not.toHaveBeenCalled();
  });

  it("does not call fetch when called", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    refuseIncompatibleEdge({ timeframe: "1h" }, { timeframe: "1h" });
    refuseIncompatibleEdge({}, { timeframe: "1h" });
    refuseIncompatibleEdge({ timeframe: "1h" }, { timeframe: "4h" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("refuseIncompatibleEdge: illegal timeframe", () => {
  it("does not connect two 1m endpoints", () => {
    expect(
      refuseIncompatibleEdge({ timeframe: "1m" }, { timeframe: "1m" }),
    ).toBe("timeframe invalid");
  });

  it("does not connect two 1H endpoints", () => {
    expect(
      refuseIncompatibleEdge({ timeframe: "1H" }, { timeframe: "1H" }),
    ).toBe("timeframe invalid");
  });

  it("does not treat 1m against 1h as a legal mismatch", () => {
    expect(
      refuseIncompatibleEdge({ timeframe: "1m" }, { timeframe: "1h" }),
    ).toBe("timeframe invalid");
  });
});

describe("edges.ts module surface", () => {
  it("does not import a graph library", () => {
    const source = readFileSync(resolve(here, "edges.ts"), "utf8");
    expect(source).not.toMatch(/@xyflow\/react/);
    expect(source).not.toMatch(/from\s+["']reactflow["']/);
    expect(source).not.toMatch(/from\s+["']react-flow-renderer["']/);
    expect(source).not.toMatch(/from\s+["']d3["']/);
    expect(source).not.toMatch(/from\s+["']cytoscape["']/);
    expect(source).not.toMatch(/from\s+["']vis-network["']/);
  });
});