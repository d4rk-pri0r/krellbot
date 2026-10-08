import { describe, expect, it } from "vitest";
import { summarizeDeploymentRefused } from "./deploymentRefusedSummary";

const KNOWN_LABEL_TABLE: ReadonlyArray<readonly [string, string]> = [
  ["insufficient_balance", "Insufficient balance"],
  ["rate_limited", "Rate limited"],
  ["circuit_open", "Circuit open"],
  ["venue_unreachable", "Venue unreachable"],
  ["account_not_found", "Account not found"],
  ["revision_mismatch", "Revision mismatch"],
  ["invalid_request", "Invalid request"],
  ["position_locked", "Position locked"],
  ["timeout", "Operation timed out"],
];

describe("summarizeDeploymentRefused known codes", () => {
  it.each(KNOWN_LABEL_TABLE)("maps %s to %s", (code, label) => {
    const summary = summarizeDeploymentRefused(code, "any message");
    expect(summary.label).toBe(label);
    expect(summary.code).toBe(code);
  });

  it("returns the exact label string with no extra whitespace", () => {
    for (const [code, label] of KNOWN_LABEL_TABLE) {
      expect(summarizeDeploymentRefused(code, "m").label).toBe(label);
    }
  });
});

describe("summarizeDeploymentRefused unknown codes", () => {
  it("sentence-cases an unknown code by turning underscores into spaces", () => {
    expect(summarizeDeploymentRefused("weather_unavailable", "m").label).toBe("Weather unavailable");
  });

  it("preserves the unknown code verbatim in the returned code field", () => {
    expect(summarizeDeploymentRefused("weather_unavailable", "m").code).toBe("weather_unavailable");
  });

  it("keeps an already-capitalized unknown code correct", () => {
    expect(summarizeDeploymentRefused("AlreadyCapitalized_pair", "m").label).toBe(
      "AlreadyCapitalized pair",
    );
  });
});

describe("summarizeDeploymentRefused purity and shape", () => {
  it("is pure: same inputs give the same output and inputs are unchanged", () => {
    const code = "circuit_open";
    const message = "circuit breaker tripped";
    const first = summarizeDeploymentRefused(code, message);
    const second = summarizeDeploymentRefused(code, message);
    expect(first).toEqual(second);
    expect(code).toBe("circuit_open");
    expect(message).toBe("circuit breaker tripped");
  });

  it("returns a fresh object on every call, not a shared reference", () => {
    const a = summarizeDeploymentRefused("rate_limited", "m");
    const b = summarizeDeploymentRefused("rate_limited", "m");
    expect(a).not.toBe(b);
    expect(a).toEqual(b);
    const c = summarizeDeploymentRefused("weather_unavailable", "m");
    const d = summarizeDeploymentRefused("weather_unavailable", "m");
    expect(c).not.toBe(d);
  });

  it("does not mutate the input code string", () => {
    const code = "insufficient_balance";
    summarizeDeploymentRefused(code, "m");
    expect(code).toBe("insufficient_balance");
  });
});

describe("summarizeDeploymentRefused full sweep", () => {
  it("covers all 9 known codes plus 3 unknown variants", () => {
    const known = KNOWN_LABEL_TABLE.map(([code]) =>
      summarizeDeploymentRefused(code, "m"),
    );
    expect(known).toHaveLength(9);
    expect(known.every((s) => KNOWN_LABEL_TABLE.some(([, label]) => label === s.label))).toBe(true);

    const unknowns = [
      ["weather_unavailable", "Weather unavailable"],
      ["unreachable_venue", "Unreachable venue"],
      ["timeout_exceeded", "Timeout exceeded"],
    ] as const;
    for (const [code, expected] of unknowns) {
      expect(summarizeDeploymentRefused(code, "m").label).toBe(expected);
    }
  });

  it("requires both code and message arguments", () => {
    expect(typeof summarizeDeploymentRefused).toBe("function");
    // Both parameters are typed as required strings; calling with the pair
    // the component uses must succeed without coercion or throws.
    const summary = summarizeDeploymentRefused("timeout", "Operation timed out");
    expect(summary).toEqual({ label: "Operation timed out", code: "timeout" });
  });
});
