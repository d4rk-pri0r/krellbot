import { useEffect, useReducer, useRef, type JSX } from "react";
import type {
  RehearsalClient,
  RehearsalCommandResult,
  RehearsalStatus,
} from "./rehearsalClient";
import {
  canExit,
  canPause,
  canResume,
  canStart,
  canStop,
  classifyRehearsalStatus,
  cursorSentence,
  formatFillTs,
  lifecycleSentence,
  positionSentence,
  rehearsalBalances,
  stopSentence,
  type RehearsalCommandName,
} from "./rehearsalModel";

export type { RehearsalClient, RehearsalStatus } from "./rehearsalClient";

export type RehearsalPanelProps = {
  client: RehearsalClient | null;
};

type PanelState = {
  status: RehearsalStatus | null;
  /** null only until the first confirmed read; "unknown" after a failed one. */
  loadFailed: string | null;
  errorMessage: string | null;
  unknownOutcome: string | null;
  pending: RehearsalCommandName | null;
};

const INITIAL_STATE: PanelState = {
  status: null,
  loadFailed: null,
  errorMessage: null,
  unknownOutcome: null,
  pending: null,
};

type PanelAction =
  | { type: "status"; status: RehearsalStatus }
  | { type: "load-failed"; message: string }
  | { type: "command-start"; command: RehearsalCommandName }
  | { type: "command-refused"; message: string }
  | { type: "unknown-outcome"; message: string }
  | { type: "command-ok"; status: RehearsalStatus | null };

function transportDetail(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

function commandLabel(command: RehearsalCommandName): string {
  switch (command) {
    case "start":
      return "Start";
    case "pause":
      return "Pause";
    case "resume":
      return "Resume";
    case "exit":
      return "Exit";
    default:
      return "Stop";
  }
}

function refusalLabel(
  command: RehearsalCommandName,
  result: RehearsalCommandResult | null | undefined,
): string {
  const message =
    typeof result?.message === "string" && result.message.length > 0
      ? result.message
      : null;
  return message ?? `${commandLabel(command)} refused`;
}

function isConfirmedOk(result: RehearsalCommandResult | null | undefined): boolean {
  // Only an explicit backend `ok: true` counts as success; anything
  // else (malformed, flag-less, refused) is treated conservatively.
  return result?.ok === true;
}

function reducer(state: PanelState, action: PanelAction): PanelState {
  switch (action.type) {
    case "status": {
      return {
        ...state,
        status: action.status,
        loadFailed: null,
      };
    }
    case "load-failed": {
      // Keep the last confirmed status; never manufacture an idle one.
      return { ...state, loadFailed: action.message };
    }
    case "command-start": {
      return {
        ...state,
        pending: action.command,
        errorMessage: null,
        unknownOutcome: null,
      };
    }
    case "command-refused": {
      return { ...state, pending: null, errorMessage: action.message };
    }
    case "unknown-outcome": {
      // Transport threw or the readback could not reconcile: keep the
      // last confirmed status and never claim a lifecycle change.
      return { ...state, pending: null, unknownOutcome: action.message };
    }
    case "command-ok": {
      return {
        ...state,
        pending: null,
        errorMessage: null,
        unknownOutcome: null,
        status: action.status ?? state.status,
      };
    }
  }
}

const POLL_INTERVAL_MS = 1000;

export function RehearsalPanel({ client }: RehearsalPanelProps): JSX.Element {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  // Synchronous double-click guard, mirroring StatusPanel.
  const inFlightRef = useRef(false);
  const epochRef = useRef(0);

  useEffect(() => {
    if (client === null) {
      return;
    }
    const epoch = ++epochRef.current;
    client
      .getStatus()
      .then((status) => {
        if (epoch !== epochRef.current) {
          return;
        }
        dispatch({ type: "status", status });
      })
      .catch((reason: unknown) => {
        if (epoch !== epochRef.current) {
          return;
        }
        // A failed first read is an honest unavailable state, never an
        // idle claim; the user can refresh explicitly.
        dispatch({
          type: "load-failed",
          message: transportDetail(reason),
        });
      });
    return () => {
      epochRef.current += 1;
    };
  }, [client]);

  const lifecycle = classifyRehearsalStatus(state.status);

  // Poll the backend only while the loop is actually running and nothing
  // is unresolved: this is display refresh of a live evaluation, not a
  // command retry. Any read failure stops the loop until an explicit
  // user refresh reconciles the state; it never restarts itself.
  const shouldPoll =
    client !== null &&
    lifecycle === "running" &&
    state.pending === null &&
    state.unknownOutcome === null;
  useEffect(() => {
    if (!shouldPoll || client === null) {
      return;
    }
    let cancelled = false;
    const timer = window.setInterval(() => {
      if (cancelled || inFlightRef.current) {
        return;
      }
      const epoch = ++epochRef.current;
      client
        .getStatus()
        .then((status) => {
          if (cancelled || epoch !== epochRef.current) {
            return;
          }
          dispatch({ type: "status", status });
        })
        .catch((reason: unknown) => {
          if (cancelled || epoch !== epochRef.current) {
            return;
          }
          dispatch({
            type: "unknown-outcome",
            message:
              `Rehearsal status refresh failed: ${transportDetail(reason)}. ` +
              "The last confirmed state is shown; refresh to reconcile.",
          });
        });
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [shouldPoll, client]);

  const refreshStatus = async (): Promise<void> => {
    if (client === null || inFlightRef.current) {
      return;
    }
    inFlightRef.current = true;
    const epoch = ++epochRef.current;
    try {
      const status = await client.getStatus();
      if (epoch !== epochRef.current) {
        return;
      }
      dispatch({ type: "status", status });
    } catch (reason) {
      if (epoch !== epochRef.current) {
        return;
      }
      dispatch({
        type: "unknown-outcome",
        message:
          `Rehearsal status refresh failed: ${transportDetail(reason)}. ` +
          "The last confirmed state is shown; refresh to reconcile.",
      });
    } finally {
      inFlightRef.current = false;
    }
  };

  const runCommand = async (
    command: RehearsalCommandName,
    action: () => Promise<RehearsalCommandResult>,
  ): Promise<void> => {
    if (client === null || inFlightRef.current) {
      return;
    }
    inFlightRef.current = true;
    const epoch = ++epochRef.current;
    dispatch({ type: "command-start", command });
    try {
      let result: RehearsalCommandResult;
      try {
        result = await action();
      } catch (reason) {
        // Transport threw: the outcome is unknown. No optimistic
        // lifecycle, no automatic retry; only an explicit user refresh
        // reconciles the state.
        if (epoch === epochRef.current) {
          dispatch({
            type: "unknown-outcome",
            message:
              `${commandLabel(command)} outcome unknown: ${transportDetail(reason)}. ` +
              "Refresh status to see the server state before retrying.",
          });
        }
        return;
      }
      if (epoch !== epochRef.current) {
        return;
      }
      if (!isConfirmedOk(result)) {
        // Refused or ambiguous response: keep the last confirmed status
        // and show the backend's own message.
        dispatch({
          type: "command-refused",
          message: refusalLabel(command, result),
        });
        return;
      }
      // The readback in the response is the backend's own projection;
      // when it is absent the panel keeps its last confirmed status and
      // reconciles with one follow-up read.
      dispatch({ type: "command-ok", status: result.status ?? null });
      if (result.status === undefined) {
        try {
          const status = await client.getStatus();
          if (epoch === epochRef.current) {
            dispatch({ type: "status", status });
          }
        } catch {
          // The command itself was confirmed; only the reconciliation
          // read failed, and the follow-up refresh covers it.
        }
      }
    } finally {
      inFlightRef.current = false;
    }
  };

  if (client === null) {
    return (
      <section
        className="kbot-rehearsal"
        role="region"
        aria-label="Synthetic paper rehearsal"
        data-testid="rehearsal-unavailable"
      >
        <header className="kbot-rehearsal__head">
          <h2 className="kbot-rehearsal__title">Synthetic paper rehearsal</h2>
        </header>
        <p className="kbot-rehearsal__empty">
          Rehearsal controls unavailable
        </p>
      </section>
    );
  }

  const busy = state.pending !== null;
  const label =
    state.status?.label !== undefined && state.status.label.length > 0
      ? state.status.label
      : "Synthetic paper rehearsal — simulated data, not market performance evidence";

  const balances = state.status !== null ? rehearsalBalances(state.status) : null;

  return (
    <section
      className="kbot-rehearsal"
      role="region"
      aria-label="Synthetic paper rehearsal"
      data-testid="rehearsal-panel"
      data-rehearsal-status={lifecycle}
      data-rehearsal-pending={state.pending ?? ""}
    >
      <header className="kbot-rehearsal__head">
        <h2 className="kbot-rehearsal__title">Synthetic paper rehearsal</h2>
        <p className="kbot-rehearsal__label" data-testid="rehearsal-label">
          {label}
        </p>
      </header>
      <div className="kbot-rehearsal__body">
        {state.loadFailed !== null && state.status === null ? (
          <>
            <p
              className="kbot-rehearsal__empty"
              role="alert"
              data-testid="rehearsal-load-failed"
            >
              Rehearsal status unavailable
            </p>
            <p className="kbot-rehearsal__error" data-testid="rehearsal-error">
              {state.loadFailed}
            </p>
            <button
              type="button"
              className="kbot-rehearsal__action"
              onClick={() => {
                void refreshStatus();
              }}
            >
              Retry status
            </button>
          </>
        ) : (
          <>
            <p
              className="kbot-rehearsal__sentence"
              data-testid="rehearsal-sentence"
            >
              {lifecycleSentence(lifecycle)}
            </p>
            {state.status !== null ? (
              <dl className="kbot-rehearsal__facts">
                <div>
                  <dt>Cursor</dt>
                  <dd data-testid="rehearsal-cursor">{cursorSentence(state.status)}</dd>
                </div>
                <div>
                  <dt>Position</dt>
                  <dd data-testid="rehearsal-position">{positionSentence(state.status)}</dd>
                </div>
                <div>
                  <dt>Stop</dt>
                  <dd data-testid="rehearsal-stop">{stopSentence(state.status)}</dd>
                </div>
                {balances !== null
                  ? balances.entries.map((entry) => (
                      <div key={entry.asset}>
                        <dt>Balance {entry.asset}</dt>
                        <dd data-testid="rehearsal-balance">{entry.amount}</dd>
                      </div>
                    ))
                  : null}
              </dl>
            ) : null}
            {state.status !== null && state.status.recent_fills.length > 0 ? (
              <table className="kbot-rehearsal__fills">
                <caption className="kbot-rehearsal__fills-caption">
                  Simulated fills
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Time</th>
                    <th scope="col">Side</th>
                    <th scope="col">Qty</th>
                    <th scope="col">Price</th>
                    <th scope="col">Coid</th>
                  </tr>
                </thead>
                <tbody>
                  {state.status.recent_fills.map((fill) => (
                    <tr key={`${fill.coid}-${fill.ts_ms}`} data-testid="rehearsal-fill">
                      <td>{formatFillTs(fill.ts_ms)}</td>
                      <td>{fill.side}</td>
                      <td>{fill.qty}</td>
                      <td>{fill.price}</td>
                      <td>{fill.coid}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            <div className="kbot-rehearsal__actions">
              <button
                type="button"
                className="kbot-rehearsal__action"
                disabled={busy || !canStart(lifecycle)}
                onClick={() => {
                  void runCommand("start", () => client.start());
                }}
              >
                {state.pending === "start" ? "Starting…" : "Start rehearsal"}
              </button>
              <button
                type="button"
                className="kbot-rehearsal__action"
                disabled={busy || !canPause(lifecycle)}
                onClick={() => {
                  void runCommand("pause", () => client.pause());
                }}
              >
                {state.pending === "pause" ? "Pausing…" : "Pause rehearsal"}
              </button>
              <button
                type="button"
                className="kbot-rehearsal__action"
                disabled={busy || !canResume(lifecycle)}
                onClick={() => {
                  void runCommand("resume", () => client.resume());
                }}
              >
                {state.pending === "resume" ? "Resuming…" : "Resume rehearsal"}
              </button>
              <button
                type="button"
                className="kbot-rehearsal__action"
                disabled={busy || !canExit(lifecycle)}
                onClick={() => {
                  void runCommand("exit", () => client.exit());
                }}
              >
                {state.pending === "exit" ? "Exiting…" : "Exit rehearsal"}
              </button>
              <button
                type="button"
                className="kbot-rehearsal__action"
                disabled={busy || !canStop(lifecycle)}
                onClick={() => {
                  void runCommand("stop", () => client.stop());
                }}
              >
                {state.pending === "stop" ? "Stopping…" : "Stop rehearsal"}
              </button>
              <button
                type="button"
                className="kbot-rehearsal__action"
                disabled={busy}
                onClick={() => {
                  void refreshStatus();
                }}
              >
                Refresh status
              </button>
            </div>
            {state.unknownOutcome !== null ? (
              <p
                className="kbot-rehearsal__unknown"
                role="alert"
                data-testid="rehearsal-unknown"
              >
                {state.unknownOutcome}
              </p>
            ) : null}
            {state.errorMessage !== null ? (
              <p
                className="kbot-rehearsal__error"
                role="alert"
                data-testid="rehearsal-error"
              >
                {state.errorMessage}
              </p>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}
