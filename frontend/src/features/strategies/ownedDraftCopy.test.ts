import { describe, expect, it } from "vitest";
import {
  buildOwnedDraftCopy,
  type OwnedCopyOrigin,
} from "./ownedDraftCopy";

// A real, schema-valid owned pack exactly as the owned-strategy subset
// produces it (schema_version 1, one MA indicator over close, leaf
// conditions, pct stop, single kraken market).
const ownedPackBytes = JSON.stringify({
  schema_version: 1,
  id: "trend-follow",
  version: "1.0.0",
  label: "Trend follow",
  author: "local workstation",
  timeframe: "1h",
  indicators: {
    ma: { fn: "ema", src: "close", len: 24 },
  },
  entry: ["close", "crosses_above", "ma"],
  exit: ["close", "crosses_below", "ma"],
  risk: {
    max_account_pct: 25,
    stop: { type: "pct", pct: 4.5 },
  },
  markets: [{ venue: "kraken", pair: "SUIUSD" }],
});

const origin: OwnedCopyOrigin = {
  revision_id: "rev-owned-1",
  state: "validated",
  created_at: "2026-10-07T12:00:00Z",
  strategy_id: "trend-follow",
  label: "Trend follow",
};

function derived(bytes: string): Record<string, unknown> {
  const copy = buildOwnedDraftCopy(bytes, origin);
  expect(copy).not.toBeNull();
  return JSON.parse(copy!.bytes) as Record<string, unknown>;
}

describe("buildOwnedDraftCopy — identity", () => {
  it("returns null for bytes that are not a JSON object", () => {
    expect(buildOwnedDraftCopy("not json", origin)).toBeNull();
    expect(buildOwnedDraftCopy("[1,2,3]", origin)).toBeNull();
    expect(buildOwnedDraftCopy("null", origin)).toBeNull();
  });

  it("derives a fresh id distinct from the origin pack id and keeps it schema-valid", () => {
    const pack = derived(ownedPackBytes);
    expect(pack.id).toMatch(/^[a-z0-9][a-z0-9-]{0,31}$/);
    expect(pack.id).not.toBe("trend-follow");
  });

  it("derives a distinct fresh id on each copy", () => {
    const first = derived(ownedPackBytes);
    const second = derived(ownedPackBytes);
    expect(first.id).not.toBe(second.id);
  });

  it("marks the label as a copy while staying within the schema's 120-char bound", () => {
    const pack = derived(ownedPackBytes);
    expect(String(pack.label)).toMatch(/^Trend follow \(copy of rev-owned-1\)$/);
    expect(String(pack.label).length).toBeLessThanOrEqual(120);
  });

  it("truncates the copy label when the origin label is long", () => {
    const longBytes = JSON.stringify({
      ...JSON.parse(ownedPackBytes),
      label: "x".repeat(119),
    });
    const pack = derived(longBytes);
    expect(String(pack.label).length).toBeLessThanOrEqual(120);
    expect(String(pack.label)).toMatch(/copy of rev-owned-1\)$/);
  });

  it("reports the origin revision clearly in the returned origin summary", () => {
    const copy = buildOwnedDraftCopy(ownedPackBytes, origin);
    expect(copy?.originLabel).toBe("Trend follow");
    expect(copy?.origin.revision_id).toBe("rev-owned-1");
    expect(copy?.origin.state).toBe("validated");
  });
});

describe("buildOwnedDraftCopy — preservation", () => {
  it("preserves exact rule, indicator, risk and market settings", () => {
    const origin_ = JSON.parse(ownedPackBytes) as Record<string, unknown>;
    const pack = derived(ownedPackBytes);
    expect(pack.timeframe).toBe(origin_.timeframe);
    expect(pack.indicators).toEqual(origin_.indicators);
    expect(pack.entry).toEqual(origin_.entry);
    expect(pack.exit).toEqual(origin_.exit);
    expect(pack.risk).toEqual(origin_.risk);
    expect(pack.markets).toEqual(origin_.markets);
    expect(pack.author).toBe(origin_.author);
    expect(pack.version).toBe(origin_.version);
  });

  it("preserves the author and origin field of an entitlement-bearing pack", () => {
    const entitledBytes = JSON.stringify({
      ...JSON.parse(ownedPackBytes),
      author: "licensed-account",
      origin: "kraken-import-2026",
    });
    const pack = derived(entitledBytes);
    expect(pack.author).toBe("licensed-account");
    expect(pack.origin).toBe("kraken-import-2026");
  });

  it("never mutates the original bytes string", () => {
    const before = ownedPackBytes;
    buildOwnedDraftCopy(ownedPackBytes, origin);
    expect(ownedPackBytes).toBe(before);
    const parsed = JSON.parse(ownedPackBytes) as { id: string; label: string };
    expect(parsed.id).toBe("trend-follow");
    expect(parsed.label).toBe("Trend follow");
  });

  it("only changes id and label; every other key is byte-identical in value", () => {
    const before = JSON.parse(ownedPackBytes) as Record<string, unknown>;
    const after = derived(ownedPackBytes);
    for (const key of Object.keys(before)) {
      if (key === "id" || key === "label") {
        continue;
      }
      expect(after[key]).toEqual(before[key]);
    }
    expect(Object.keys(after).sort()).toEqual(Object.keys(before).sort());
  });
});
