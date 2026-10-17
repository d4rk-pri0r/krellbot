import { describe, expect, it } from "vitest";
import { summarizeResearchJobError } from "./researchJobErrorLabel";

describe("summarizeResearchJobError", () => {
  it("maps each known research job error code to its exact label", () => {
    expect(summarizeResearchJobError({ code: "rate_limited", message: "m" })).toEqual({
      label: "Rate limited",
      code: "rate_limited",
    });
    expect(summarizeResearchJobError({ code: "cancelled", message: "m" })).toEqual({
      label: "Cancelled by user",
      code: "cancelled",
    });
    expect(summarizeResearchJobError({ code: "search_failed", message: "m" })).toEqual({
      label: "Search failed",
      code: "search_failed",
    });
    expect(summarizeResearchJobError({ code: "search_budget", message: "m" })).toEqual({
      label: "Search budget exhausted",
      code: "search_budget",
    });
    expect(summarizeResearchJobError({ code: "job_timeout", message: "m" })).toEqual({
      label: "Job timed out",
      code: "job_timeout",
    });
    expect(summarizeResearchJobError({ code: "venue_unreachable", message: "m" })).toEqual({
      label: "Venue unreachable",
      code: "venue_unreachable",
    });
    expect(summarizeResearchJobError({ code: "invalid_request", message: "m" })).toEqual({
      label: "Invalid request",
      code: "invalid_request",
    });
    expect(summarizeResearchJobError({ code: "internal_error", message: "m" })).toEqual({
      label: "Internal error",
      code: "internal_error",
    });
  });

  it("sentence-cases unknown codes with underscores turned into spaces", () => {
    expect(
      summarizeResearchJobError({ code: "foo_bar_baz", message: "m" }).label,
    ).toBe("Foo bar baz");
    expect(
      summarizeResearchJobError({ code: "weather_unavailable", message: "m" }).label,
    ).toBe("Weather unavailable");
  });

  it("preserves an unknown code verbatim in the returned code field", () => {
    expect(
      summarizeResearchJobError({ code: "foo_bar_baz", message: "m" }).code,
    ).toBe("foo_bar_baz");
  });

  it("keeps an already-capitalized unknown code correct", () => {
    expect(
      summarizeResearchJobError({ code: "Numeric_out_of_range", message: "m" }).label,
    ).toBe("Numeric out of range");
  });

  it("returns the exact known label with no extra whitespace", () => {
    const label = summarizeResearchJobError({ code: "search_budget", message: "m" })
      .label;
    expect(label).toBe(label.trim());
    expect(label).toBe("Search budget exhausted");
  });

  it("is pure: same input yields the same output and the input is unchanged", () => {
    const input = { code: "rate_limited", message: "hourly quota exceeded" };
    const first = summarizeResearchJobError(input);
    const second = summarizeResearchJobError(input);
    expect(second).toEqual(first);
    expect(input).toEqual({
      code: "rate_limited",
      message: "hourly quota exceeded",
    });
  });

  it("returns a fresh object every call, not a shared reference", () => {
    const input = { code: "internal_error", message: "m" };
    expect(summarizeResearchJobError(input)).not.toBe(
      summarizeResearchJobError(input),
    );
  });

  it("covers all 8 known codes plus 3 unknown variants", () => {
    const knownCodes = [
      "rate_limited",
      "cancelled",
      "search_failed",
      "search_budget",
      "job_timeout",
      "venue_unreachable",
      "invalid_request",
      "internal_error",
    ];
    for (const code of knownCodes) {
      expect(summarizeResearchJobError({ code, message: "m" })).toEqual({
        label: expect.any(String),
        code,
      });
    }
    for (const code of ["foo_bar_baz", "weather_unavailable", "Numeric_out_of_range"]) {
      expect(summarizeResearchJobError({ code, message: "m" })).toEqual({
        label: expect.any(String),
        code,
      });
    }
  });
});
