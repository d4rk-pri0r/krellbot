export type EdgeEndpoint = {
  timeframe?: string;
};

const LEGAL_TIMEFRAMES = new Set(["1h", "4h", "1d"]);

export type EdgeRefusal =
  | "timeframe missing"
  | "timeframe invalid"
  | "timeframe mismatch";

function presentTimeframe(value: string | undefined): string | null {
  if (typeof value !== "string" || value.length === 0) {
    return null;
  }
  return value;
}

export function refuseIncompatibleEdge(
  source: EdgeEndpoint,
  target: EdgeEndpoint,
): EdgeRefusal | null {
  const sourceTimeframe = presentTimeframe(source.timeframe);
  const targetTimeframe = presentTimeframe(target.timeframe);
  if (sourceTimeframe === null || targetTimeframe === null) {
    return "timeframe missing";
  }
  if (
    !LEGAL_TIMEFRAMES.has(sourceTimeframe) ||
    !LEGAL_TIMEFRAMES.has(targetTimeframe)
  ) {
    return "timeframe invalid";
  }
  if (sourceTimeframe !== targetTimeframe) {
    return "timeframe mismatch";
  }
  return null;
}