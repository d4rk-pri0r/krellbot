import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  addIndicatorNode,
  connectPackNodes,
  deletePackNode,
  edgesFromPack,
  packFromGraph,
} from "./packGraph";
import { nodesFromPack } from "./packNodes";

const here = dirname(fileURLToPath(import.meta.url));
const examplePack = JSON.parse(
  readFileSync(resolve(here, "../../../../docs/example-pack.json"), "utf8"),
) as Record<string, unknown>;

describe("packFromGraph — graph→pack", () => {
  it("builds a schema-shaped pack from indicators and entry/exit edges", () => {
    const pack = packFromGraph({
      base: {
        schema_version: 1,
        id: "trend-follow",
        version: "1.0.0",
        label: "Trend follow",
        author: "krellbot",
        timeframe: "1h",
        risk: { max_account_pct: 25, stop: { type: "pct", pct: 5 } },
        markets: [{ venue: "kraken", pair: "SUIUSD" }],
        // Stale graph fields must not leak into the result.
        entry: ["close", ">", "old"],
        exit: ["close", "<", "old"],
        indicators: { old: { fn: "sma", src: "close", len: 10 } },
      },
      indicators: {
        sma20: { fn: "sma", src: "close", len: 20 },
      },
      edges: [
        { source: "sma20", target: "entry" },
        { source: "sma20", target: "exit" },
      ],
    });

    expect(pack.schema_version).toBe(1);
    expect(pack.id).toBe("trend-follow");
    expect(pack.indicators).toEqual({
      sma20: { fn: "sma", src: "close", len: 20 },
    });
    expect(pack.entry).toEqual(["close", ">", "sma20"]);
    expect(pack.exit).toEqual(["close", "<", "sma20"]);
    expect(pack).not.toHaveProperty("editor");
  });

  it("nests multiple entry edges under all and keeps unused indicators wired", () => {
    const pack = packFromGraph({
      base: {
        schema_version: 1,
        id: "multi",
        version: "1.0.0",
        label: "Multi",
        author: "local",
        timeframe: "1h",
        risk: { max_account_pct: 10, stop: { type: "pct", pct: 2 } },
        markets: [{ venue: "kraken", pair: "XXBTZUSD" }],
      },
      indicators: {
        fast: { fn: "ema", src: "close", len: 8 },
        slow: { fn: "ema", src: "close", len: 21 },
        orphan: { fn: "sma", src: "close", len: 50 },
      },
      edges: [
        { source: "fast", target: "entry" },
        { source: "slow", target: "entry" },
        { source: "slow", target: "exit" },
      ],
    });

    expect(pack.entry).toEqual({
      all: [
        ["close", ">", "fast"],
        ["close", ">", "slow"],
        ["close", ">", "orphan"],
      ],
    });
    expect(pack.exit).toEqual(["close", "<", "slow"]);
  });

  it("round-trips example pack nodes and derived edges through packFromGraph", () => {
    const nodes = nodesFromPack(examplePack);
    const edges = edgesFromPack(examplePack);
    const indicators = examplePack.indicators as Record<
      string,
      { fn: string; src: string; len: number }
    >;

    const rebuilt = packFromGraph({
      base: examplePack,
      indicators,
      edges,
    });

    expect(nodes.map((node) => node.id)).toEqual(
      expect.arrayContaining(["pack", "sma20", "entry", "exit"]),
    );
    expect(edges).toEqual([
      { source: "sma20", target: "entry" },
      { source: "sma20", target: "exit" },
    ]);
    expect(rebuilt.indicators).toEqual(examplePack.indicators);
    expect(rebuilt.entry).toEqual(examplePack.entry);
    expect(rebuilt.exit).toEqual(examplePack.exit);
    expect(rebuilt.id).toBe(examplePack.id);
    expect(rebuilt.risk).toEqual(examplePack.risk);
    expect(rebuilt.markets).toEqual(examplePack.markets);
  });
});

describe("addIndicatorNode / connectPackNodes / deletePackNode", () => {
  it("adds a default SMA, wires entry, and keeps prior indicators referenced", () => {
    const result = addIndicatorNode(examplePack);
    expect(result.ok).toBe(true);
    if (!result.ok) {
      return;
    }
    expect(result.nodeId).toBe("sma2");
    const indicators = result.pack.indicators as Record<string, unknown>;
    expect(indicators.sma20).toEqual({
      fn: "sma",
      src: "close",
      len: 20,
    });
    expect(indicators.sma2).toEqual({
      fn: "sma",
      src: "close",
      len: 20,
    });
    expect(result.pack.entry).toEqual({
      all: [
        ["close", ">", "sma20"],
        ["close", ">", "sma2"],
      ],
    });
    expect(result.pack.exit).toEqual(["close", "<", "sma20"]);
  });

  it("connects an indicator into exit without dropping entry wiring", () => {
    const added = addIndicatorNode(examplePack, { name: "ema8", fn: "ema", len: 8 });
    expect(added.ok).toBe(true);
    if (!added.ok) {
      return;
    }
    const connected = connectPackNodes(added.pack, "ema8", "exit");
    expect(connected.ok).toBe(true);
    if (!connected.ok) {
      return;
    }
    expect(connected.pack.exit).toEqual({
      all: [
        ["close", "<", "sma20"],
        ["close", "<", "ema8"],
      ],
    });
  });

  it("deletes an indicator and rehomes entry/exit onto a survivor", () => {
    const added = addIndicatorNode(examplePack, { name: "sma50", len: 50 });
    expect(added.ok).toBe(true);
    if (!added.ok) {
      return;
    }
    const deleted = deletePackNode(added.pack, "sma20");
    expect(deleted.ok).toBe(true);
    if (!deleted.ok) {
      return;
    }
    const indicators = deleted.pack.indicators as Record<string, unknown>;
    expect(indicators).not.toHaveProperty("sma20");
    expect(indicators).toHaveProperty("sma50");
    expect(JSON.stringify(deleted.pack.entry)).not.toContain("sma20");
    expect(JSON.stringify(deleted.pack.exit)).not.toContain("sma20");
    expect(JSON.stringify(deleted.pack)).toContain("sma50");
  });

  it("refuses deleting the last indicator or a role node", () => {
    expect(deletePackNode(examplePack, "sma20")).toEqual({
      ok: false,
      reason: "last indicator",
    });
    expect(deletePackNode(examplePack, "entry")).toEqual({
      ok: false,
      reason: "role node",
    });
    expect(deletePackNode(examplePack, "pack")).toEqual({
      ok: false,
      reason: "role node",
    });
  });
});
