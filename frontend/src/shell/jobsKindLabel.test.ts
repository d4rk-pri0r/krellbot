import { describe, expect, it } from "vitest";
import { summarizeJobsKind } from "./jobsKindLabel";

describe("summarizeJobsKind", () => {
  it("labels the research backtest kind", () => {
    expect(summarizeJobsKind("research.backtest")).toEqual({
      label: "Research backtest",
      isKnown: true,
      isUnknown: false,
    });
  });

  it("labels the export reproducibility kind", () => {
    expect(summarizeJobsKind("export.reproducibility")).toEqual({
      label: "Export reproducibility",
      isKnown: true,
      isUnknown: false,
    });
  });

  it("marks each known kind as known and not unknown", () => {
    for (const kind of ["research.backtest", "export.reproducibility"]) {
      expect(summarizeJobsKind(kind).isKnown).toBe(true);
      expect(summarizeJobsKind(kind).isUnknown).toBe(false);
    }
  });

  it("sentence-cases unknown dotted kinds into spaced labels", () => {
    expect(summarizeJobsKind("some.future.kind")).toEqual({
      label: "Some future kind",
      isKnown: false,
      isUnknown: true,
    });
  });

  it("sentence-cases a single unknown segment", () => {
    expect(summarizeJobsKind("maintenance").label).toBe("Maintenance");
    expect(summarizeJobsKind("maintenance").isUnknown).toBe(true);
  });

  it("preserves underscores in unknown snake_case kinds without dot conversion", () => {
    const summary = summarizeJobsKind("legacy_snake_kind");
    expect(summary.label).toBe("Legacy_snake_kind");
    expect(summary.isKnown).toBe(false);
    expect(summary.isUnknown).toBe(true);
  });

  it("does not fuzzy-match near-miss kind tokens", () => {
    expect(summarizeJobsKind("research.backtests").label).toBe("Research backtests");
    expect(summarizeJobsKind("research.backtests").isKnown).toBe(false);
  });

  it("returns the em-dash sentinel for empty, null, and undefined kinds", () => {
    const missing: (string | null | undefined)[] = ["", null, undefined];
    for (const kind of missing) {
      expect(summarizeJobsKind(kind)).toEqual({
        label: "—",
        isKnown: false,
        isUnknown: true,
      });
    }
  });
});
