import { describe, expect, it } from "vitest";
import { summarizePaperCommandRefusal } from "./paperCommandRefusalSummary";

describe("summarizePaperCommandRefusal", () => {
  it("prefers the server message and surfaces the code for a known command", () => {
    expect(
      summarizePaperCommandRefusal("Pause", {
        message: "venue down",
        code: "VENUE_OFFLINE",
      }),
    ).toEqual({
      label: "venue down",
      command: "Pause",
      code: "VENUE_OFFLINE",
      fallback: "Pause refused",
      isKnownCommand: true,
      hasServerMessage: true,
    });
  });

  it("falls back to the canonical copy when only a code is present", () => {
    expect(
      summarizePaperCommandRefusal("Resume", { code: "NOT_ARMED" }),
    ).toEqual({
      label: "Resume refused",
      command: "Resume",
      code: "NOT_ARMED",
      fallback: "Resume refused",
      isKnownCommand: true,
      hasServerMessage: false,
    });
  });

  it("treats a null result as a message-less refusal", () => {
    expect(summarizePaperCommandRefusal("Disarm", null)).toEqual({
      label: "Disarm refused",
      command: "Disarm",
      code: null,
      fallback: "Disarm refused",
      isKnownCommand: true,
      hasServerMessage: false,
    });
  });

  it("extends the same contract to an unknown future command", () => {
    expect(
      summarizePaperCommandRefusal("Stop", { message: "not supported" }),
    ).toEqual({
      label: "not supported",
      command: "Stop",
      code: null,
      fallback: "Stop refused",
      isKnownCommand: false,
      hasServerMessage: true,
    });
  });

  it("treats an undefined result like a null result", () => {
    expect(summarizePaperCommandRefusal("Cancel", undefined)).toEqual({
      label: "Cancel refused",
      command: "Cancel",
      code: null,
      fallback: "Cancel refused",
      isKnownCommand: false,
      hasServerMessage: false,
    });
  });

  it("treats an empty-string message as missing", () => {
    const summary = summarizePaperCommandRefusal("Pause", { message: "" });
    expect(summary.label).toBe("Pause refused");
    expect(summary.hasServerMessage).toBe(false);
    expect(summary.fallback).toBe("Pause refused");
  });

  // Whitespace-only messages are NOT trimmed: only a truly empty string (or an
  // absent message) falls back. This keeps the helper free of hidden
  // normalization that could mask what the server actually sent.
  it("preserves a whitespace-only message as present", () => {
    const summary = summarizePaperCommandRefusal("Pause", {
      message: "   ",
      code: "X",
    });
    expect(summary.label).toBe("   ");
    expect(summary.hasServerMessage).toBe(true);
    expect(summary.code).toBe("X");
    expect(summary.fallback).toBe("Pause refused");
  });

  it("returns a fresh object on each invocation", () => {
    const first = summarizePaperCommandRefusal("Pause", {
      message: "venue down",
    });
    first.label = "mutated";
    first.code = "MUTATED";
    const second = summarizePaperCommandRefusal("Pause", {
      message: "venue down",
    });
    expect(second.label).toBe("venue down");
    expect(second.code).toBeNull();
    expect(second).not.toBe(first);
  });
});
