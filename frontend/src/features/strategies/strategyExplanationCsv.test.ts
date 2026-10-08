import { describe, expect, it } from "vitest";
import {
  explanationCsvBody,
  explanationCsvField,
  explanationCsvHeader,
  explanationIndicatorRows,
  explanationMarketRows,
  explanationMetadataRows,
  type ExplanationCsvRow,
} from "./strategyExplanationCsv";

describe("explanationCsvHeader", () => {
  it("returns the deterministic three-column header", () => {
    expect(explanationCsvHeader()).toEqual(["section", "key", "value"]);
  });
});

describe("explanationMetadataRows", () => {
  it("returns five fixed rows in label/packId/version/author/origin order", () => {
    expect(
      explanationMetadataRows({
        label: "m",
        packId: "p",
        version: "v",
        author: "a",
        origin: "o",
      }),
    ).toEqual([
      { section: "metadata", key: "label", value: "m" },
      { section: "metadata", key: "packId", value: "p" },
      { section: "metadata", key: "version", value: "v" },
      { section: "metadata", key: "author", value: "a" },
      { section: "metadata", key: "origin", value: "o" },
    ]);
  });

  it("keeps missing fields as empty values instead of omitting rows", () => {
    const rows = explanationMetadataRows({
      label: null,
      packId: "",
      version: "1.0.0",
      author: null,
      origin: null,
    });
    expect(rows).toHaveLength(5);
    expect(rows[0]).toEqual({ section: "metadata", key: "label", value: "" });
    expect(rows[1]).toEqual({ section: "metadata", key: "packId", value: "" });
    expect(rows[3]).toEqual({ section: "metadata", key: "author", value: "" });
  });
});

describe("explanationIndicatorRows", () => {
  it("maps each indicator to one row keyed by its name", () => {
    expect(
      explanationIndicatorRows([
        { name: "ema", text: "exponential moving average 14", supported: true },
      ]),
    ).toEqual([
      { section: "indicator", key: "ema", value: "exponential moving average 14" },
    ]);
  });

  it("keeps unsupported indicators as rows carrying their explanatory text", () => {
    expect(
      explanationIndicatorRows([
        { name: "weird", text: 'an unsupported function ("nope")', supported: false },
      ]),
    ).toEqual([
      { section: "indicator", key: "weird", value: 'an unsupported function ("nope")' },
    ]);
  });
});

describe("explanationMarketRows", () => {
  it("maps each market to one row keyed by venue and pair", () => {
    expect(
      explanationMarketRows([
        { venue: "kraken", pair: "XBT/USD", supported: true, text: "kraken XBT/USD" },
      ]),
    ).toEqual([{ section: "market", key: "kraken XBT/USD", value: "XBT/USD" }]);
  });
});

describe("explanationCsvBody", () => {
  it("joins the header and every row with CRLF without a trailing break", () => {
    const rows: ExplanationCsvRow[] = [
      { section: "metadata", key: "label", value: "Trend follow" },
      { section: "indicator", key: "sma20", value: '"sma20" = sma of close over the last 20 bars' },
    ];
    expect(explanationCsvBody(rows)).toBe(
      [
        "section,key,value",
        "metadata,label,Trend follow",
        'indicator,sma20,"""sma20"" = sma of close over the last 20 bars"',
      ].join("\r\n"),
    );
  });

  it("returns the empty string for an empty row list", () => {
    expect(explanationCsvBody([])).toBe("");
  });
});

describe("explanationCsvField", () => {
  it("leaves plain fields unquoted", () => {
    expect(explanationCsvField("kraken")).toBe("kraken");
    expect(explanationCsvField("")).toBe("");
  });

  it("quotes fields containing commas, quotes or line breaks per RFC 4180", () => {
    expect(explanationCsvField("a,b")).toBe('"a,b"');
    expect(explanationCsvField('say "hi"')).toBe('"say ""hi"""');
    expect(explanationCsvField("line1\nline2")).toBe('"line1\nline2"');
    expect(explanationCsvField("line1\r\nline2")).toBe('"line1\r\nline2"');
  });
});
