import { describe, expect, it } from "vitest";
import { summarizeAlertSeverity } from "./alertSeverityLabel";

// SENTINEL: empty/null/undefined severity renders as "—" (em dash).
// This file asserts that exact string; changing it requires updating
// these tests.
describe("summarizeAlertSeverity", () => {
  it("maps the known critical severity to a sentence-cased label", () => {
    expect(summarizeAlertSeverity("critical")).toEqual({
      label: "Critical",
      severity: "critical",
      isKnown: true,
      isUnknown: false,
    });
  });

  it("maps the known warning severity to a sentence-cased label", () => {
    expect(summarizeAlertSeverity("warning")).toEqual({
      label: "Warning",
      severity: "warning",
      isKnown: true,
      isUnknown: false,
    });
  });

  it("sentence-cases an unknown single-word severity via the fallback", () => {
    expect(summarizeAlertSeverity("fatal")).toEqual({
      label: "Fatal",
      severity: "fatal",
      isKnown: false,
      isUnknown: true,
    });
  });

  it("keeps unknown severities flagged as unknown even when the casing matches", () => {
    const summary = summarizeAlertSeverity("info");
    expect(summary.label).toBe("Info");
    expect(summary.severity).toBe("info");
    expect(summary.isKnown).toBe(false);
    expect(summary.isUnknown).toBe(true);
  });

  it("converts underscores to spaces and capitalises the first letter", () => {
    expect(summarizeAlertSeverity("some_future").label).toBe("Some future");
  });

  it("capitalises only the first letter of a multi-word unknown severity", () => {
    expect(summarizeAlertSeverity("page_on_call_second").label).toBe("Page on call second");
  });

  it("returns the em-dash sentinel for null, undefined and empty string", () => {
    const expected = {
      label: "—",
      severity: "—",
      isKnown: false,
      isUnknown: true,
    };
    expect(summarizeAlertSeverity(null)).toEqual(expected);
    expect(summarizeAlertSeverity(undefined)).toEqual(expected);
    expect(summarizeAlertSeverity("")).toEqual(expected);
  });

  it("does not mutate the known-severity lookup through repeated calls", () => {
    expect(summarizeAlertSeverity("critical").label).toBe("Critical");
    expect(summarizeAlertSeverity("CRITICAL").label).toBe("CRITICAL");
    expect(summarizeAlertSeverity("critical").label).toBe("Critical");
  });
});
