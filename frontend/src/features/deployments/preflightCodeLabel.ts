export type PreflightCode = string;

export type PreflightCodeLabel = {
  label: string;
  code: PreflightCode;
  isKnown: boolean;
  isUnknown: boolean;
};

const UNKNOWN_CODE = "(unknown code)";

// Canonical preflight codes the LivePreflight panel may surface; each maps
// to its Title-Cased user-facing label.
const KNOWN_LABELS: Record<string, string> = {
  ok: "Ok",
  mode_not_sandbox: "Mode not sandbox",
  account_mismatch: "Account mismatch",
  revision_mismatch: "Revision mismatch",
  venue_unreachable: "Venue unreachable",
  rate_limited: "Rate limited",
  circuit_open: "Circuit open",
  preflight_blocked: "Preflight blocked",
};

// Sentence-case fallback matching the canonical label style above
// ("Mode not sandbox", "Account mismatch", ...): underscores become spaces
// and only the first character of the whole value is capitalized.
function titleCase(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.length === 0
    ? spaced
    : spaced[0].toUpperCase() + spaced.slice(1);
}

export function summarizePreflightCode(
  code: PreflightCode | null | undefined,
): PreflightCodeLabel {
  const value =
    typeof code === "string" && code.length > 0 ? code : UNKNOWN_CODE;
  const known = KNOWN_LABELS[value];
  const label = known !== undefined ? known : titleCase(value);
  return {
    label,
    code: value,
    isKnown: known !== undefined,
    isUnknown: known === undefined,
  };
}
