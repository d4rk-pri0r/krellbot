export type EdgeRefusal =
  | "timeframe missing"
  | "timeframe invalid"
  | "timeframe mismatch"
  | string;

export type EdgeRefusalLabel = {
  label: string;
  reason: EdgeRefusal;
  isKnown: boolean;
  isUnknown: boolean;
};

const KNOWN_LABELS: Record<string, string> = {
  "timeframe missing": "Timeframe missing",
  "timeframe invalid": "Timeframe invalid",
  "timeframe mismatch": "Timeframe mismatch",
};

const UNKNOWN_REFUSAL = "(unknown refusal)";

function isKnownRefusal(value: string): boolean {
  return Object.prototype.hasOwnProperty.call(KNOWN_LABELS, value);
}

// The canonical examples only capitalize the leading word:
// "venue_unreachable" -> "Venue unreachable".
function toTitleCase(value: string): string {
  const normalized = value.replace(/[\s_]+/g, " ").trim();
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function summarizeEdgeRefusal(
  reason: EdgeRefusal | null | undefined,
): EdgeRefusalLabel {
  const wasProvided = typeof reason === "string" && reason.length > 0;
  const value = wasProvided ? reason : UNKNOWN_REFUSAL;
  const isKnown = isKnownRefusal(value);
  let label: string;
  if (isKnown) {
    label = KNOWN_LABELS[value];
  } else if (wasProvided) {
    label = toTitleCase(value);
  } else {
    label = UNKNOWN_REFUSAL;
  }
  return { label, reason: value, isKnown, isUnknown: !isKnown };
}
