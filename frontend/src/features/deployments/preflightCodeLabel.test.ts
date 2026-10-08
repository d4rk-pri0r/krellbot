import { describe, expect, it } from "vitest";
import { summarizePreflightCode } from "./preflightCodeLabel";

describe("summarizePreflightCode", () => {
  it("maps the ok code to a Title-Cased label", () => {
    expect(summarizePreflightCode("ok")).toEqual({
      label: "Ok",
      code: "ok",
      isKnown: true,
      isUnknown: false,
    });
  });

  it("maps mode_not_sandbox to a friendly label", () => {
    expect(summarizePreflightCode("mode_not_sandbox")).toEqual({
      label: "Mode not sandbox",
      code: "mode_not_sandbox",
      isKnown: true,
      isUnknown: false,
    });
  });

  it("maps account_mismatch to a friendly label", () => {
    expect(summarizePreflightCode("account_mismatch")).toEqual({
      label: "Account mismatch",
      code: "account_mismatch",
      isKnown: true,
      isUnknown: false,
    });
  });

  it("maps venue_unreachable to a friendly label", () => {
    expect(summarizePreflightCode("venue_unreachable")).toEqual({
      label: "Venue unreachable",
      code: "venue_unreachable",
      isKnown: true,
      isUnknown: false,
    });
  });

  it("maps the remaining known codes to their canonical labels", () => {
    expect(summarizePreflightCode("revision_mismatch").label).toBe(
      "Revision mismatch",
    );
    expect(summarizePreflightCode("rate_limited").label).toBe("Rate limited");
    expect(summarizePreflightCode("circuit_open").label).toBe("Circuit open");
    expect(summarizePreflightCode("preflight_blocked").label).toBe(
      "Preflight blocked",
    );
  });

  it("title-cases unknown snake_case codes and marks them unknown", () => {
    expect(summarizePreflightCode("unknown_kind_xyz")).toEqual({
      label: "Unknown kind xyz",
      code: "unknown_kind_xyz",
      isKnown: false,
      isUnknown: true,
    });
  });

  it("treats null as an unknown code", () => {
    expect(summarizePreflightCode(null)).toEqual({
      label: "(unknown code)",
      code: "(unknown code)",
      isKnown: false,
      isUnknown: true,
    });
  });

  it("treats undefined as an unknown code", () => {
    expect(summarizePreflightCode(undefined)).toEqual({
      label: "(unknown code)",
      code: "(unknown code)",
      isKnown: false,
      isUnknown: true,
    });
  });

  it("treats the empty string as an unknown code", () => {
    expect(summarizePreflightCode("")).toEqual({
      label: "(unknown code)",
      code: "(unknown code)",
      isKnown: false,
      isUnknown: true,
    });
  });

  it("returns a fresh object on each invocation", () => {
    const first = summarizePreflightCode("account_mismatch");
    first.label = "mutated";
    first.isKnown = false;
    expect(summarizePreflightCode("account_mismatch")).toEqual({
      label: "Account mismatch",
      code: "account_mismatch",
      isKnown: true,
      isUnknown: false,
    });
  });
});
