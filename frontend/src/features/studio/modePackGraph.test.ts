/**
 * M15.5 — Studio graph load for built-in trading-mode packs.
 *
 * Loading DCA / grid / rebalance must yield human-readable nodes (M6.2),
 * never demo ``n*`` ids, and Save-path ``packFromGraph`` must keep mode
 * metadata while emitting validating structure.
 */

import { describe, expect, it } from "vitest";
import {
  edgesFromPack,
  packFromGraph,
  type PackGraphIndicator,
} from "./packGraph";
import { nodesFromPack } from "./packNodes";
import { studioNodeLabel } from "./studioNodeLabel";

const modeDca = {
  schema_version: 1,
  id: "mode-dca",
  version: "1.0.0",
  label: "DCA",
  author: "krellbot",
  origin: "Built-in DCA mode. Not live market performance.",
  timeframe: "1d",
  indicators: {
    anchor: { fn: "sma", src: "close", len: 2 },
  },
  entry: {
    all: [
      ["close", ">", 0],
      ["anchor", ">", 0],
    ],
  },
  exit: ["close", "<=", 0],
  risk: { max_account_pct: 5, stop: { type: "pct", pct: 15 } },
  markets: [{ venue: "kraken", pair: "SUIUSD" }],
  mode: { kind: "dca" },
} as const;

const modeGrid = {
  schema_version: 1,
  id: "mode-grid",
  version: "1.0.0",
  label: "Grid",
  author: "krellbot",
  origin: "Built-in grid mode. Long-only DSL; not a venue grid bot.",
  timeframe: "1h",
  mode: { kind: "grid", levels: 5 },
  indicators: {
    band_high: { fn: "highest", src: "close", len: 20 },
    band_low: { fn: "lowest", src: "close", len: 20 },
  },
  entry: ["close", "<=", "band_low"],
  exit: ["close", ">=", "band_high"],
  risk: { max_account_pct: 20, stop: { type: "pct", pct: 5 } },
  markets: [{ venue: "kraken", pair: "SUIUSD" }],
} as const;

const modeRebalance = {
  schema_version: 1,
  id: "mode-rebalance",
  version: "1.0.0",
  label: "Rebalance",
  author: "krellbot",
  origin: "Built-in rebalance mode. Strategy-owned inventory only.",
  timeframe: "1d",
  indicators: {
    sma20: { fn: "sma", src: "close", len: 20 },
  },
  entry: ["close", ">", "sma20"],
  exit: ["close", "<", "sma20"],
  risk: { max_account_pct: 25, stop: { type: "pct", pct: 5 } },
  markets: [{ venue: "kraken", pair: "BTCUSD" }],
  mode: {
    kind: "rebalance",
    threshold_pct: 5,
    targets: [
      { symbol: "BTC", weight_pct: 60 },
      { symbol: "USD", weight_pct: 40 },
    ],
  },
} as const;

const MODE_PACKS = [
  { name: "dca", pack: modeDca, indicatorIds: ["anchor"] },
  { name: "grid", pack: modeGrid, indicatorIds: ["band_high", "band_low"] },
  {
    name: "rebalance",
    pack: modeRebalance,
    indicatorIds: ["sma20"],
  },
] as const;

describe("Studio mode pack graph load (M15.5)", () => {
  it.each(MODE_PACKS)(
    "loads $name as readable nodes without demo ids",
    ({ pack, indicatorIds }) => {
      const nodes = nodesFromPack({ ...pack });
      const ids = nodes.map((node) => node.id);
      expect(ids).toEqual(
        expect.arrayContaining(["pack", "entry", "exit", ...indicatorIds]),
      );
      expect(ids.some((id) => /^n\d+$/i.test(id))).toBe(false);
      expect(ids.some((id) => /^w\d+$/i.test(id))).toBe(false);
      for (const node of nodes) {
        const label = String(node.data?.label ?? "");
        expect(label.length).toBeGreaterThan(0);
        expect(label).toBe(studioNodeLabel(node.id));
        expect(label).not.toMatch(/^n\d+$/i);
        expect(label.toLowerCase()).not.toContain("demo");
      }
      expect(studioNodeLabel("pack")).toBe("Pack");
      expect(studioNodeLabel("entry")).toBe("Entry");
      expect(studioNodeLabel("exit")).toBe("Exit");
    },
  );

  it.each(MODE_PACKS)(
    "preserves $name mode metadata through packFromGraph save path",
    ({ pack }) => {
      const edges = edgesFromPack({ ...pack });
      const indicators = pack.indicators as Record<string, PackGraphIndicator>;
      const rebuilt = packFromGraph({
        base: { ...pack },
        indicators,
        edges,
      });
      expect(rebuilt.id).toBe(pack.id);
      expect(rebuilt.mode).toEqual(pack.mode);
      expect(rebuilt.timeframe).toBe(pack.timeframe);
      expect(rebuilt.risk).toEqual(pack.risk);
      expect(rebuilt.markets).toEqual(pack.markets);
      expect(rebuilt.indicators).toEqual(pack.indicators);
      expect(rebuilt.entry).toBeDefined();
      expect(rebuilt.exit).toBeDefined();
      const nodes = nodesFromPack(rebuilt);
      expect(nodes.map((n) => n.id).some((id) => /^n\d+$/i.test(id))).toBe(
        false,
      );
    },
  );
});
