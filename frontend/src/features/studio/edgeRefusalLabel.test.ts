import { describe, expect, it } from "vitest";
import { summarizeEdgeRefusal } from "./edgeRefusalLabel";

describe("summarizeEdgeRefusal", () => {
  it("labels the timeframe missing refusal as known", () => {
    expect(summarizeEdgeRefusal("timeframe missing")).toEqual({
      label: "Timeframe missing",
      reason: "timeframe missing",
      isKnown: true,
      isUnknown: false,
    });
  });

  it("labels the timeframe invalid refusal as known", () => {
    expect(summarizeEdgeRefusal("timeframe invalid")).toEqual({
      label: "Timeframe invalid",
      reason: "timeframe invalid",
      isKnown: true,
      isUnknown: false,
    });
  });

  it("labels the timeframe mismatch refusal as known", () => {
    expect(summarizeEdgeRefusal("timeframe mismatch")).toEqual({
      label: "Timeframe mismatch",
      reason: "timeframe mismatch",
      isKnown: true,
      isUnknown: false,
    });
  });

  it("title-cases unknown reasons and marks them unknown", () => {
    expect(summarizeEdgeRefusal("some_unknown_thing")).toEqual({
      label: "Some unknown thing",
      reason: "some_unknown_thing",
      isKnown: false,
      isUnknown: true,
    });
  });

  it("collapses extra spaces when title-casing", () => {
    expect(summarizeEdgeRefusal("venue  unreachable").label).toBe(
      "Venue unreachable",
    );
  });

  it("treats null as an unknown refusal", () => {
    expect(summarizeEdgeRefusal(null)).toEqual({
      label: "(unknown refusal)",
      reason: "(unknown refusal)",
      isKnown: false,
      isUnknown: true,
    });
  });

  it("treats undefined as an unknown refusal", () => {
    expect(summarizeEdgeRefusal(undefined)).toEqual({
      label: "(unknown refusal)",
      reason: "(unknown refusal)",
      isKnown: false,
      isUnknown: true,
    });
  });

  it("treats an empty string as an unknown refusal", () => {
    expect(summarizeEdgeRefusal("")).toEqual({
      label: "(unknown refusal)",
      reason: "(unknown refusal)",
      isKnown: false,
      isUnknown: true,
    });
  });

  it("returns a fresh object on each invocation", () => {
    const first = summarizeEdgeRefusal("timeframe missing");
    first.label = "mutated";
    first.isKnown = false;
    expect(summarizeEdgeRefusal("timeframe missing")).toEqual({
      label: "Timeframe missing",
      reason: "timeframe missing",
      isKnown: true,
      isUnknown: false,
    });
  });
});
