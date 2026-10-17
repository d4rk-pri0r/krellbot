export type AlertSeverity = string;

export type AlertSeverityLabel = {
  label: string;
  severity: AlertSeverity;
  isKnown: boolean;
  isUnknown: boolean;
};

const KNOWN_SEVERITY_LABELS: Record<string, string> = {
  critical: "Critical",
  warning: "Warning",
};

const UNKNOWN_SEVERITY_TEXT = "—";

function sentenceCase(severity: string): string {
  const words = severity.replaceAll("_", " ").trim();
  if (words.length === 0) {
    return UNKNOWN_SEVERITY_TEXT;
  }
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function summarizeAlertSeverity(
  severity: AlertSeverity | null | undefined,
): AlertSeverityLabel {
  if (severity === null || severity === undefined || severity.length === 0) {
    return {
      label: UNKNOWN_SEVERITY_TEXT,
      severity: UNKNOWN_SEVERITY_TEXT,
      isKnown: false,
      isUnknown: true,
    };
  }

  const known = KNOWN_SEVERITY_LABELS[severity];
  if (known !== undefined) {
    return {
      label: known,
      severity,
      isKnown: true,
      isUnknown: false,
    };
  }

  return {
    label: sentenceCase(severity),
    severity,
    isKnown: false,
    isUnknown: true,
  };
}
