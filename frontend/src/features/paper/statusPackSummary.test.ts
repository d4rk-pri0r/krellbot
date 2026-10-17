import { describe, expect, it } from "vitest";

import { summarizeStatusPack } from "./statusPackSummary";

describe("summarizeStatusPack", () => {
  it("joins a complete pack, venue, and pair", () => {
    const result = summarizeStatusPack("p1", "kraken", "BTC-USD");
    expect(result.label).toBe("p1 on kraken BTC-USD");
    expect(result.isComplete).toBe(true);
    expect(result.isPartial).toBe(false);
    expect(result.isMissing).toBe(false);
    expect(result.isPackOnly).toBe(false);
    expect(result.isVenueOnly).toBe(false);
    expect(result.isPairOnly).toBe(false);
  });

  it("reports pack-only when just the pack id is set", () => {
    const result = summarizeStatusPack("p1", null, null);
    expect(result.label).toBe("p1");
    expect(result.isPackOnly).toBe(true);
    expect(result.isPartial).toBe(false);
    expect(result.isComplete).toBe(false);
    expect(result.isMissing).toBe(false);
  });

  it("reports venue-only when just the venue is set", () => {
    const result = summarizeStatusPack(null, "kraken", null);
    expect(result.label).toBe("kraken");
    expect(result.isVenueOnly).toBe(true);
    expect(result.isPartial).toBe(false);
  });

  it("reports pair-only when just the pair is set", () => {
    const result = summarizeStatusPack(null, null, "BTC-USD");
    expect(result.label).toBe("BTC-USD");
    expect(result.isPairOnly).toBe(true);
    expect(result.isPartial).toBe(false);
  });

  it("marks all-null input as missing", () => {
    const result = summarizeStatusPack(null, null, null);
    expect(result.label).toBe("(no pack)");
    expect(result.isMissing).toBe(true);
    expect(result.isComplete).toBe(false);
    expect(result.isPartial).toBe(false);
    expect(result.isPackOnly).toBe(false);
    expect(result.isVenueOnly).toBe(false);
    expect(result.isPairOnly).toBe(false);
  });

  it("marks all-undefined input as missing", () => {
    const result = summarizeStatusPack(undefined, undefined, undefined);
    expect(result.label).toBe("(no pack)");
    expect(result.isMissing).toBe(true);
  });

  it("treats empty strings as missing", () => {
    const result = summarizeStatusPack("", "", "");
    expect(result.label).toBe("(no pack)");
    expect(result.isMissing).toBe(true);
  });

  it("drops a missing pair from a partial label", () => {
    const result = summarizeStatusPack("p1", "kraken", null);
    expect(result.label).toBe("p1 on kraken");
    expect(result.isPartial).toBe(true);
    expect(result.isComplete).toBe(false);
    expect(result.isMissing).toBe(false);
  });

  it("drops a missing venue from a partial label", () => {
    const result = summarizeStatusPack("p1", null, "BTC-USD");
    expect(result.label).toBe("p1 on BTC-USD");
    expect(result.isPartial).toBe(true);
  });

  it("drops a missing pack from a partial label", () => {
    const result = summarizeStatusPack(null, "kraken", "BTC-USD");
    expect(result.label).toBe("kraken BTC-USD");
    expect(result.isPartial).toBe(true);
  });

  it("returns structurally equal results for identical input", () => {
    const a = summarizeStatusPack("p1", "kraken", "BTC-USD");
    const b = summarizeStatusPack("p1", "kraken", "BTC-USD");
    expect(a).toEqual(b);
    expect(a).not.toBe(b);
  });
});
