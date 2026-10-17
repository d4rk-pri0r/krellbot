import type { IndicatorExplanation, MarketExplanation, ExplainResult } from "./explainPack";

/**
 * One row of the explanation CSV: the explanation is heterogeneous (metadata
 * fields, indicators, markets), so it is emitted as rows rather than columns.
 */
export type ExplanationCsvRow = {
  section: string;
  key: string;
  value: string;
};

/**
 * Escape a single CSV field per RFC 4180: quote only when the field contains a
 * comma, a double quote, or a line break, doubling embedded double quotes.
 * Embedded newlines are preserved inside the quoted field.
 */
export function explanationCsvField(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

/** Column headers for the explanation export: section, key, value. */
export function explanationCsvHeader(): [string, string, string] {
  return ["section", "key", "value"];
}

/**
 * Stored metadata as five fixed rows in label/packId/version/author/origin
 * order. Missing fields become empty values so the file stays table-stable.
 */
export function explanationMetadataRows(meta: ExplainResult["metadata"]): ExplanationCsvRow[] {
  return [
    { section: "metadata", key: "label", value: meta.label ?? "" },
    { section: "metadata", key: "packId", value: meta.packId ?? "" },
    { section: "metadata", key: "version", value: meta.version ?? "" },
    { section: "metadata", key: "author", value: meta.author ?? "" },
    { section: "metadata", key: "origin", value: meta.origin ?? "" },
  ];
}

/** One row per indicator, keyed by its name and carrying its explanation text. */
export function explanationIndicatorRows(
  indicators: readonly IndicatorExplanation[],
): ExplanationCsvRow[] {
  return indicators.map((indicator) => ({
    section: "indicator",
    key: indicator.name,
    value: indicator.text,
  }));
}

/** One row per market, keyed by "venue pair" with the pair as the value. */
export function explanationMarketRows(
  markets: readonly MarketExplanation[],
): ExplanationCsvRow[] {
  return markets.map((market) => ({
    section: "market",
    key: `${market.venue} ${market.pair}`.trim(),
    value: market.pair,
  }));
}

/**
 * Build the full CSV document (header + rows) joined with CRLF line breaks.
 * An empty list yields the empty string so the export control can stay inert.
 */
export function explanationCsvBody(rows: readonly ExplanationCsvRow[]): string {
  if (rows.length === 0) {
    return "";
  }
  const lines = [
    explanationCsvHeader(),
    ...rows.map((row) => [row.section, row.key, row.value] as const),
  ];
  return lines.map((line) => line.map(explanationCsvField).join(",")).join("\r\n");
}
