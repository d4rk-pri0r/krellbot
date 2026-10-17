export type ResearchJobError = {
  code: string;
  message: string;
};

export type ResearchJobErrorSummary = {
  label: string;
  code: string;
};

const LABELS: Record<string, string> = {
  rate_limited: "Rate limited",
  cancelled: "Cancelled by user",
  search_failed: "Search failed",
  search_budget: "Search budget exhausted",
  job_timeout: "Job timed out",
  venue_unreachable: "Venue unreachable",
  invalid_request: "Invalid request",
  internal_error: "Internal error",
};

function sentenceCase(code: string): string {
  const spaced = code.replace(/_/g, " ").trim();
  if (!spaced) {
    return spaced;
  }
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function summarizeResearchJobError(
  jobError: ResearchJobError,
): ResearchJobErrorSummary {
  const known = LABELS[jobError.code];
  return {
    label: known !== undefined ? known : sentenceCase(jobError.code),
    code: jobError.code,
  };
}
