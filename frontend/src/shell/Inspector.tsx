import type { JSX } from "react";
import type { AlertRow } from "../features/operations/client";
import type {
  PaperArmedRecord,
  PaperPosition,
} from "../features/paper/client";
import { summarizeAlertKind } from "../features/operations/alertKindLabel";
import { summarizeAlertSeverity } from "../features/operations/alertSeverityLabel";
import "./Inspector.signal.css";

/**
 * Workstation selection kinds the inspector can present. The shell owns
 * selection; the inspector only presents what it is given — it never
 * fetches, never infers, and never invents a subject.
 */
export type InspectorSelectionKind = "deployment" | "position" | "alert";

/**
 * The subject the shell is currently inspecting, if any.
 */
export type InspectorSelection = {
  id: string;
  kind?: InspectorSelectionKind;
  label?: string;
  detail?: string;
};

export type InspectorProps = {
  selection?: InspectorSelection | null;
  loading?: boolean;
  error?: string | null;
  onClose?: () => void;
};

const KIND_LABEL: Record<InspectorSelectionKind, string> = {
  deployment: "Deployment",
  position: "Position",
  alert: "Alert",
};

const EMPTY_COPY =
  "Nothing selected — pick a deployment, position, or alert on this page to inspect it here.";

/** Map an armed paper record into inspector selection context. */
export function selectionFromDeployment(
  record: PaperArmedRecord,
): InspectorSelection {
  return {
    id: `${record.venue}:${record.pair}`,
    kind: "deployment",
    label: `${record.pack_id} · ${record.mode}`,
    detail: record.entries_paused ? "Entries paused" : "Entries active",
  };
}

/** Map an owned paper position into inspector selection context. */
export function selectionFromPosition(
  position: PaperPosition,
): InspectorSelection {
  const venue = position.venue ?? "";
  const pair = position.pair ?? "";
  const id =
    venue !== "" || pair !== ""
      ? `${venue}:${pair}`
      : "position";
  const holdings = (position.holdings ?? [])
    .map((row) => `${row.qty} ${row.symbol}`)
    .join(", ");
  const owned = holdings !== "" ? holdings : "no open position";
  const quote = pair.length >= 3 ? pair.slice(-3) : "";
  const cash =
    position.free_cash !== undefined
      ? `${position.free_cash}${quote !== "" ? ` ${quote}` : ""}`
      : "";
  return {
    id,
    kind: "position",
    label: owned,
    detail: cash !== "" ? `Free cash ${cash}` : undefined,
  };
}

/** Map an operations alert row into inspector selection context. */
export function selectionFromAlert(alert: AlertRow): InspectorSelection {
  const kindLabel = summarizeAlertKind(alert.kind).label;
  const severityLabel = summarizeAlertSeverity(alert.severity).label;
  const market =
    alert.venue !== null || alert.pair !== null
      ? [alert.venue ?? "", alert.pair ?? ""].filter(Boolean).join(" ")
      : "";
  const code = alert.code ?? "";
  const bits = [
    market !== "" ? market : null,
    code !== "" ? code : null,
    `×${alert.count}`,
  ].filter((part): part is string => part !== null);
  return {
    id: alert.id,
    kind: "alert",
    label: `${kindLabel} · ${severityLabel}`,
    detail: bits.length > 0 ? bits.join(" · ") : undefined,
  };
}

function kindEyebrow(selection: InspectorSelection): string {
  return selection.kind !== undefined
    ? KIND_LABEL[selection.kind]
    : "Selected";
}

export function Inspector({
  selection = null,
  loading = false,
  error = null,
  onClose,
}: InspectorProps = {}): JSX.Element {
  return (
    <section
      className="kbot-shell__inspector-root"
      role="region"
      aria-label="Inspector"
      data-testid="inspector-root"
    >
      <header className="kbot-inspector__head">
        <h2 className="kbot-inspector__title">Inspector</h2>
        {onClose ? (
          <button
            type="button"
            className="kbot-inspector__close"
            data-testid="inspector-close"
            aria-label="Close inspector"
            onClick={onClose}
          >
            Close
          </button>
        ) : null}
      </header>
      <div className="kbot-inspector__body">
        {error ? (
          <p
            className="kbot-inspector__error"
            role="alert"
            data-testid="inspector-error"
          >
            Could not inspect the selection — {error}
          </p>
        ) : null}
        {!error && loading && selection ? (
          <p
            className="kbot-inspector__loading"
            data-testid="inspector-loading"
          >
            Inspecting selection…
          </p>
        ) : null}
        {!error && !loading && selection ? (
          <div
            className="kbot-inspector__selected"
            data-testid="inspector-selection"
            data-kind={selection.kind ?? ""}
          >
            <p className="kbot-inspector__selected-label">
              {kindEyebrow(selection)}
            </p>
            <p className="kbot-inspector__selected-id">{selection.id}</p>
            {selection.label ? (
              <p className="kbot-inspector__selected-detail">
                {selection.label}
              </p>
            ) : null}
            {selection.detail ? (
              <p
                className="kbot-inspector__selected-facts"
                data-testid="inspector-selection-detail"
              >
                {selection.detail}
              </p>
            ) : null}
          </div>
        ) : null}
        {!error && !selection ? (
          <p className="kbot-inspector__empty" data-testid="inspector-empty">
            {EMPTY_COPY}
          </p>
        ) : null}
      </div>
    </section>
  );
}
