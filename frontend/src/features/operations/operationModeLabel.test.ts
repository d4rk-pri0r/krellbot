import { describe, expect, it } from "vitest";
import { summarizeOperationMode } from "./operationModeLabel";

describe("summarizeOperationMode", () => {
  it("labels paper with a capitalized friendly label", () => {
    const result = summarizeOperationMode("paper");
    expect(result.label).toBe("Paper");
    expect(result.mode).toBe("paper");
    expect(result.isPaper).toBe(true);
    expect(result.isLive).toBe(false);
    expect(result.isSandbox).toBe(false);
    expect(result.isUnknown).toBe(false);
    expect(result.isKnown).toBe(true);
  });

  it("labels live with a capitalized friendly label", () => {
    const result = summarizeOperationMode("live");
    expect(result.label).toBe("Live");
    expect(result.mode).toBe("live");
    expect(result.isLive).toBe(true);
    expect(result.isPaper).toBe(false);
    expect(result.isSandbox).toBe(false);
    expect(result.isUnknown).toBe(false);
    expect(result.isKnown).toBe(true);
  });

  it("labels sandbox with a capitalized friendly label", () => {
    const result = summarizeOperationMode("sandbox");
    expect(result.label).toBe("Sandbox");
    expect(result.mode).toBe("sandbox");
    expect(result.isSandbox).toBe(true);
    expect(result.isPaper).toBe(false);
    expect(result.isLive).toBe(false);
    expect(result.isUnknown).toBe(false);
    expect(result.isKnown).toBe(true);
  });

  it("labels an unrecognized non-empty mode with its verbatim text", () => {
    const result = summarizeOperationMode("unknown");
    expect(result.label).toBe("(unknown mode: unknown)");
    expect(result.mode).toBe("unknown");
    expect(result.isUnknown).toBe(true);
    expect(result.isKnown).toBe(false);
    expect(result.isPaper).toBe(false);
    expect(result.isLive).toBe(false);
    expect(result.isSandbox).toBe(false);
  });

  it("treats null as an unknown mode without verbatim text", () => {
    const result = summarizeOperationMode(null);
    expect(result.label).toBe("(unknown mode)");
    expect(result.isUnknown).toBe(true);
    expect(result.isKnown).toBe(false);
    expect(result.isPaper).toBe(false);
    expect(result.isLive).toBe(false);
    expect(result.isSandbox).toBe(false);
  });

  it("treats undefined as an unknown mode without verbatim text", () => {
    const result = summarizeOperationMode(undefined);
    expect(result.label).toBe("(unknown mode)");
    expect(result.isUnknown).toBe(true);
    expect(result.isKnown).toBe(false);
  });

  it("treats the empty string as an unknown mode, not a known one", () => {
    const result = summarizeOperationMode("");
    expect(result.label).toBe("(unknown mode)");
    expect(result.isUnknown).toBe(true);
    expect(result.isKnown).toBe(false);
  });

  it("returns structurally equal results for repeated calls", () => {
    expect(summarizeOperationMode("paper")).toEqual(summarizeOperationMode("paper"));
    expect(summarizeOperationMode("weird")).toEqual(
      summarizeOperationMode("weird"),
    );
    expect(summarizeOperationMode(null)).not.toBe(summarizeOperationMode(null));
  });
});
