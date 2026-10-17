import { describe, expect, it } from "vitest";
import {
  indicatorSpecFilename,
  indicatorSpecToJson,
  type IndicatorSpecLike,
} from "./indicatorSpecJson";

describe("indicatorSpecToJson", () => {
  it("serializes the spec as pretty JSON with a trailing newline", () => {
    expect(indicatorSpecToJson({ name: "rsi", len: 14 })).toBe(
      '{\n  "name": "rsi",\n  "len": 14\n}\n',
    );
  });

  it("preserves key order: name before len", () => {
    const spec: IndicatorSpecLike = { len: 14, name: "rsi" };
    const json = indicatorSpecToJson(spec);
    expect(json).toBe('{\n  "name": "rsi",\n  "len": 14\n}\n');
    expect(json.indexOf('"name"')).toBeLessThan(json.indexOf('"len"'));
  });

  it("escapes without touching surrounding formatting", () => {
    expect(indicatorSpecToJson({ name: "a b", len: 2 })).toBe(
      '{\n  "name": "a b",\n  "len": 2\n}\n',
    );
  });
});

describe("indicatorSpecFilename", () => {
  it("builds the krellbot-indicator filename from a slug and timestamp", () => {
    expect(indicatorSpecFilename("rsi", "20261008T055500Z")).toBe(
      "krellbot-indicator-rsi-20261008T055500Z.json",
    );
  });

  it("replaces non [A-Za-z0-9_] characters with underscores", () => {
    expect(indicatorSpecFilename("a/b", "20261008T055500Z")).toBe(
      "krellbot-indicator-a_b-20261008T055500Z.json",
    );
  });

  it("falls back to _unnamed for an empty name", () => {
    expect(indicatorSpecFilename("", "20261008T055500Z")).toBe(
      "krellbot-indicator-_unnamed-20261008T055500Z.json",
    );
  });
});
