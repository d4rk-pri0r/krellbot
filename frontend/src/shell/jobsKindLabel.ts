export type JobsKindLabel = {
  label: string;
  isKnown: boolean;
  isUnknown: boolean;
};

const KNOWN_JOBS_KINDS: Record<string, string> = {
  "research.backtest": "Research backtest",
  "export.reproducibility": "Export reproducibility",
};

const UNKNOWN_LABEL = "—";

function sentenceCase(value: string): string {
  if (value.length === 0) {
    return value;
  }
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function summarizeJobsKind(kind: string | null | undefined): JobsKindLabel {
  if (typeof kind !== "string" || kind.trim().length === 0) {
    return { label: UNKNOWN_LABEL, isKnown: false, isUnknown: true };
  }
  const known = KNOWN_JOBS_KINDS[kind];
  if (typeof known === "string") {
    return { label: known, isKnown: true, isUnknown: false };
  }
  return {
    label: sentenceCase(kind.replace(/\./g, " ")),
    isKnown: false,
    isUnknown: true,
  };
}
