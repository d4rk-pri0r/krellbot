export type AlertKind = string;

export type AlertKindLabel = {
  label: string;
  kind: AlertKind;
  isKnown: boolean;
  isUnknown: boolean;
};

const UNKNOWN_KIND_TEXT = "(unknown kind)";

const KNOWN_LABELS: Record<string, string> = {
  live_refused: "Live refused",
  deploy_failed: "Deploy failed",
  venue_unreachable: "Venue unreachable",
  deploy_succeeded: "Deploy succeeded",
  venue_recovered: "Venue recovered",
  preflight_blocked: "Preflight blocked",
  rate_limited: "Rate limited",
  circuit_open: "Circuit open",
  metadata_refusal: "Metadata refusal",
  tick_failure: "Tick failure",
  scheduler_stale: "Scheduler stale",
  unresolved_order_aging: "Unresolved order aging",
  restore_fence: "Restore fence",
  kill_switch: "Kill switch",
};

function fallbackLabel(value: string): string {
  if (value === UNKNOWN_KIND_TEXT) {
    return UNKNOWN_KIND_TEXT;
  }
  return `${value.charAt(0).toUpperCase()}${value.slice(1).replace(/_/g, " ")}`;
}

export function summarizeAlertKind(
  kind: AlertKind | null | undefined,
): AlertKindLabel {
  const value =
    typeof kind === "string" && kind.length > 0 ? kind : UNKNOWN_KIND_TEXT;
  const known = KNOWN_LABELS[value];
  const isKnown = known !== undefined;
  return {
    label: known ?? fallbackLabel(value),
    kind: value,
    isKnown,
    isUnknown: !isKnown,
  };
}
