/**
 * Pure formatter for the operations deployment `mode` field.
 *
 * The raw value is the stored armed mode ("paper" | "live" | "sandbox").
 * Anything else — including null/undefined and the empty string — is surfaced
 * as "(unknown mode)" so a future mode value never renders as a confusing
 * bare token. Always returns a fresh object; never throws.
 */

export type OperationMode = "paper" | "live" | "sandbox" | string;

export type OperationModeLabel = {
  label: string;
  mode: OperationMode;
  isPaper: boolean;
  isLive: boolean;
  isSandbox: boolean;
  isUnknown: boolean;
  isKnown: boolean;
};

const KNOWN_LABELS: Record<string, string> = {
  paper: "Paper",
  live: "Live",
  sandbox: "Sandbox",
};

export function summarizeOperationMode(
  mode: OperationMode | null | undefined,
): OperationModeLabel {
  const value =
    typeof mode === "string" && mode.length > 0 ? mode : "(unknown mode)";
  const hasValue = value !== "(unknown mode)";
  const knownLabel = KNOWN_LABELS[value];
  const isKnown = knownLabel !== undefined;
  return {
    label: isKnown
      ? knownLabel
      : hasValue
        ? `(unknown mode: ${value})`
        : "(unknown mode)",
    mode: value,
    isPaper: value === "paper",
    isLive: value === "live",
    isSandbox: value === "sandbox",
    isUnknown: !isKnown,
    isKnown,
  };
}
