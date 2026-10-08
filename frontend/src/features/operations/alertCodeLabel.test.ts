import { describe, expect, it } from "vitest";
import { summarizeAlertCode } from "./alertCodeLabel";

const KNOWN = [
  ["kill_switch_engaged", "Kill switch engaged"],
  ["needs_reconcile", "Needs reconcile"],
  ["live_refused", "Live refused"],
  ["store_refused", "Store refused"],
  ["intent_refused", "Intent refused"],
  ["metadata_refusal", "Metadata refusal"],
  ["live_disabled", "Live disabled"],
  ["entries_paused", "Entries paused"],
  ["entries_resumed", "Entries resumed"],
  ["kill_switch_released", "Kill switch released"],
  ["acknowledged", "Acknowledged"],
] as const;

describe("summarizeAlertCode known codes", () => {
  for (const [code, label] of KNOWN) {
    it(`maps ${code} to ${label}`, () => {
      expect(summarizeAlertCode(code).label).toBe(label);
    });
  }

  it("marks every known code as known and not unknown", () => {
    for (const [code] of KNOWN) {
      const result = summarizeAlertCode(code);
      expect(result.isKnown).toBe(true);
      expect(result.isUnknown).toBe(false);
      expect(result.code).toBe(code);
    }
  });
});

describe("summarizeAlertCode unknown codes", () => {
  it("sentence-cases an unknown snake_case code and echoes the original", () => {
    const result = summarizeAlertCode("some_future_code");
    expect(result.label).toBe("Some future code");
    expect(result.code).toBe("some_future_code");
    expect(result.isKnown).toBe(false);
    expect(result.isUnknown).toBe(true);
  });

  it("preserves camelCase wording without underscore conversion", () => {
    const result = summarizeAlertCode("someFutureCode");
    expect(result.label).toBe("SomeFutureCode");
    expect(result.code).toBe("someFutureCode");
    expect(result.isKnown).toBe(false);
    expect(result.isUnknown).toBe(true);
  });

  it("sentence-cases a bare single-word code", () => {
    expect(summarizeAlertCode("throttled").label).toBe("Throttled");
  });
});

describe("summarizeAlertCode empty codes", () => {
  it("returns the em-dash sentinel for an empty string", () => {
    expect(summarizeAlertCode("")).toEqual({
      label: "—",
      code: "",
      isKnown: false,
      isUnknown: true,
    });
  });

  it("returns the em-dash sentinel for null", () => {
    expect(summarizeAlertCode(null)).toEqual({
      label: "—",
      code: "",
      isKnown: false,
      isUnknown: true,
    });
  });

  it("returns the em-dash sentinel for undefined", () => {
    expect(summarizeAlertCode(undefined)).toEqual({
      label: "—",
      code: "",
      isKnown: false,
      isUnknown: true,
    });
  });
});
