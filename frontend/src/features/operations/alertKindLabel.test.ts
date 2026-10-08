import { describe, expect, it } from "vitest";
import { summarizeAlertKind } from "./alertKindLabel";

describe("summarizeAlertKind", () => {
  it("labels live_refused as a known kind", () => {
    const result = summarizeAlertKind("live_refused");
    expect(result).toEqual({
      label: "Live refused",
      kind: "live_refused",
      isKnown: true,
      isUnknown: false,
    });
  });

  it("labels deploy_failed as a known kind", () => {
    const result = summarizeAlertKind("deploy_failed");
    expect(result.label).toBe("Deploy failed");
    expect(result.isKnown).toBe(true);
    expect(result.isUnknown).toBe(false);
  });

  it("labels venue_unreachable as a known kind", () => {
    const result = summarizeAlertKind("venue_unreachable");
    expect(result.label).toBe("Venue unreachable");
    expect(result.isKnown).toBe(true);
  });

  it("labels circuit_open as a known kind", () => {
    const result = summarizeAlertKind("circuit_open");
    expect(result.label).toBe("Circuit open");
    expect(result.isKnown).toBe(true);
  });

  it("labels rate_limited as a known kind", () => {
    const result = summarizeAlertKind("rate_limited");
    expect(result.label).toBe("Rate limited");
    expect(result.isKnown).toBe(true);
  });

  it("title-cases unknown snake_case kinds and flags them unknown", () => {
    const result = summarizeAlertKind("unknown_kind_xyz");
    expect(result.label).toBe("Unknown kind xyz");
    expect(result.kind).toBe("unknown_kind_xyz");
    expect(result.isKnown).toBe(false);
    expect(result.isUnknown).toBe(true);
  });

  it("treats null as (unknown kind)", () => {
    const result = summarizeAlertKind(null);
    expect(result).toEqual({
      label: "(unknown kind)",
      kind: "(unknown kind)",
      isKnown: false,
      isUnknown: true,
    });
  });

  it("treats undefined as (unknown kind)", () => {
    const result = summarizeAlertKind(undefined);
    expect(result.label).toBe("(unknown kind)");
    expect(result.isKnown).toBe(false);
  });

  it("treats empty string as (unknown kind)", () => {
    const result = summarizeAlertKind("");
    expect(result.label).toBe("(unknown kind)");
    expect(result.isKnown).toBe(false);
    expect(result.isUnknown).toBe(true);
  });

  it("returns a fresh object on each invocation", () => {
    const first = summarizeAlertKind("live_refused");
    first.label = "mutated";
    first.isKnown = false;
    const second = summarizeAlertKind("live_refused");
    expect(second.label).toBe("Live refused");
    expect(second.isKnown).toBe(true);
    expect(second).not.toBe(first);
  });
});
