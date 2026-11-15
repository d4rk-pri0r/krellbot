import { useEffect, useState, type JSX } from "react";
import type { AlertRow, OperationsClient } from "../features/operations/client";
import { summarizeAlertKind } from "../features/operations/alertKindLabel";
import { summarizeAlertSeverity } from "../features/operations/alertSeverityLabel";
import "./WorkstationAlerts.signal.css";

export type WorkstationAlertsProps = {
  client: OperationsClient;
  selectedId?: string | null;
  onSelect: (alert: AlertRow | null) => void;
};

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; alerts: ReadonlyArray<AlertRow> }
  | { kind: "unavailable"; message: string };

/**
 * Compact unacknowledged-alert peek for the paper workstation. Selection
 * is reported to the shell inspector; this list never invents alerts.
 */
export function WorkstationAlerts({
  client,
  selectedId = null,
  onSelect,
}: WorkstationAlertsProps): JSX.Element {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    client
      .getOperations()
      .then((view) => {
        if (cancelled) {
          return;
        }
        const alerts = view.alerts.filter((row) => row.acknowledged !== true);
        setState({ kind: "ready", alerts });
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        setState({
          kind: "unavailable",
          message: err instanceof Error ? err.message : String(err),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const toggle = (alert: AlertRow): void => {
    onSelect(selectedId === alert.id ? null : alert);
  };

  return (
    <section
      className="kbot-workstation-alerts"
      role="region"
      aria-label="Workstation alerts"
      data-testid="workstation-alerts"
    >
      <header className="kbot-workstation-alerts__head">
        <h3 className="kbot-workstation-alerts__title">Alerts</h3>
      </header>
      <div className="kbot-workstation-alerts__body">
        {state.kind === "loading" ? (
          <p
            className="kbot-workstation-alerts__empty"
            data-testid="workstation-alerts-loading"
          >
            Reading alerts…
          </p>
        ) : null}
        {state.kind === "unavailable" ? (
          <p
            className="kbot-workstation-alerts__empty"
            role="alert"
            data-testid="workstation-alerts-unavailable"
          >
            Alerts unavailable
            {state.message !== "" ? `: ${state.message}` : ""}
          </p>
        ) : null}
        {state.kind === "ready" && state.alerts.length === 0 ? (
          <p
            className="kbot-workstation-alerts__empty"
            data-testid="workstation-alerts-empty"
          >
            No unacknowledged alerts
          </p>
        ) : null}
        {state.kind === "ready" && state.alerts.length > 0 ? (
          <ul
            className="kbot-workstation-alerts__list"
            data-testid="workstation-alerts-list"
          >
            {state.alerts.map((alert) => {
              const selected = selectedId === alert.id;
              return (
                <li key={alert.id}>
                  <button
                    type="button"
                    className={`kbot-workstation-alerts__row${
                      selected ? " kbot-workstation-alerts__row--selected" : ""
                    }`}
                    data-testid="workstation-alert-row"
                    data-alert-id={alert.id}
                    aria-pressed={selected}
                    onClick={() => {
                      toggle(alert);
                    }}
                  >
                    <span className="kbot-workstation-alerts__kind">
                      {summarizeAlertKind(alert.kind).label}
                    </span>
                    <span className="kbot-workstation-alerts__severity">
                      {summarizeAlertSeverity(alert.severity).label}
                    </span>
                    <span className="kbot-workstation-alerts__id">
                      {alert.id}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : null}
      </div>
    </section>
  );
}
