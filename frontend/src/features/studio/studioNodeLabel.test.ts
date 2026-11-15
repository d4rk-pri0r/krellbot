import { describe, expect, it } from "vitest";
import { studioNodeLabel } from "./studioNodeLabel";

describe("studioNodeLabel — human-readable Studio canvas titles", () => {
  it("labels pack roles in prose", () => {
    expect(studioNodeLabel("pack")).toBe("Pack");
    expect(studioNodeLabel("entry")).toBe("Entry");
    expect(studioNodeLabel("exit")).toBe("Exit");
  });

  it("labels demo and sample workload ids without exposing raw keys as the title", () => {
    expect(studioNodeLabel("n0")).toBe("Demo 0");
    expect(studioNodeLabel("n2")).toBe("Demo 2");
    expect(studioNodeLabel("w0")).toBe("Sample 0");
    expect(studioNodeLabel("w199")).toBe("Sample 199");
  });

  it("humanizes indicator keys with digit and underscore boundaries", () => {
    expect(studioNodeLabel("sma2")).toBe("SMA 2");
    expect(studioNodeLabel("sma20")).toBe("SMA 20");
    expect(studioNodeLabel("ema_fast")).toBe("EMA Fast");
    expect(studioNodeLabel("fast")).toBe("Fast");
    expect(studioNodeLabel("slow")).toBe("Slow");
  });

  it("falls back safely for empty ids", () => {
    expect(studioNodeLabel("")).toBe("Node");
    expect(studioNodeLabel("   ")).toBe("Node");
  });
});
