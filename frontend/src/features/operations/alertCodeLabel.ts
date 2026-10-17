export type AlertCode = string;

export type AlertCodeLabel = {
  label: string;
  code: string;
  isKnown: boolean;
  isUnknown: boolean;
};

const EMPTY_CODE_LABEL = "—";

const KNOWN_ALERT_CODE_LABELS: Record<AlertCode, string> = {
  kill_switch_engaged: "Kill switch engaged",
  needs_reconcile: "Needs reconcile",
  live_refused: "Live refused",
  store_refused: "Store refused",
  intent_refused: "Intent refused",
  metadata_refusal: "Metadata refusal",
  live_disabled: "Live disabled",
  entries_paused: "Entries paused",
  entries_resumed: "Entries resumed",
  kill_switch_released: "Kill switch released",
  acknowledged: "Acknowledged",
};

function sentenceCase(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.length === 0 ? spaced : spaced[0].toUpperCase() + spaced.slice(1);
}

export function summarizeAlertCode(
  code: string | null | undefined,
): AlertCodeLabel {
  if (code === null || code === undefined || code === "") {
    return {
      label: EMPTY_CODE_LABEL,
      code: "",
      isKnown: false,
      isUnknown: true,
    };
  }
  const known = KNOWN_ALERT_CODE_LABELS[code];
  if (known !== undefined) {
    return { label: known, code, isKnown: true, isUnknown: false };
  }
  return { label: sentenceCase(code), code, isKnown: false, isUnknown: true };
}
