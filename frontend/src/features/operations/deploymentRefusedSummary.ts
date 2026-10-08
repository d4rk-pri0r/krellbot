export type DeploymentRefusedSummary = { label: string; code: string };

const KNOWN_LABELS: Record<string, string> = {
  insufficient_balance: "Insufficient balance",
  rate_limited: "Rate limited",
  circuit_open: "Circuit open",
  venue_unreachable: "Venue unreachable",
  account_not_found: "Account not found",
  revision_mismatch: "Revision mismatch",
  invalid_request: "Invalid request",
  position_locked: "Position locked",
  timeout: "Operation timed out",
};

function sentenceCase(code: string): string {
  if (code.length === 0) {
    return code;
  }
  const spaced = code.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function summarizeDeploymentRefused(code: string, message: string): DeploymentRefusedSummary {
  void message; // accepted for signature parity: surfaces choose label or code alongside their own message render
  const known = KNOWN_LABELS[code];
  return { label: known !== undefined ? known : sentenceCase(code), code };
}
