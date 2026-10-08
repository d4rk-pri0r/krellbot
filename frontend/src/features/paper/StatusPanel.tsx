import { useEffect, useReducer, useRef, type JSX } from "react";
import type { PaperClient, PaperCommandResult, PaperStatus } from "./client";
import { PaperStatusCsvExport } from "./PaperStatusCsvExport";

export type { PaperClient, PaperCommandResult, PaperStatus } from "./client";

export type StatusPanelProps = {
  client: PaperClient;
};

type EntriesSentence = "Entries active" | "Entries paused";

type CommandName = "pause" | "resume" | "disarm";

type PanelState = {
  status: PaperStatus | null;
  sentence: EntriesSentence;
  errorMessage: string | null;
  unavailable: boolean;
  pending: CommandName | null;
  unknownOutcome: string | null;
};

const INITIAL_STATE: PanelState = {
  status: null,
  sentence: "Entries active",
  errorMessage: null,
  unavailable: false,
  pending: null,
  unknownOutcome: null,
};

type PanelAction =
  | { type: "status"; status: PaperStatus }
  | { type: "unavailable" }
  | { type: "command-start"; command: CommandName }
  | { type: "command-refused"; message: string }
  | { type: "unknown-outcome"; message: string }
  | {
      type: "command-ok";
      status: PaperStatus | null;
      sentence?: EntriesSentence;
    };

function sentenceFor(entries_paused: boolean | undefined): EntriesSentence {
  return entries_paused ? "Entries paused" : "Entries active";
}

function commandLabel(command: CommandName): string {
  if (command === "pause") return "Pause";
  if (command === "resume") return "Resume";
  return "Disarm";
}

function transportDetail(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

function isConfirmedOk(result: PaperCommandResult | null | undefined): boolean {
  // Only an explicit backend `ok: true` counts as success; a malformed or
  // flag-less response is interpreted conservatively as not confirmed.
  return result?.ok === true;
}

function refusalMessage(
  command: CommandName,
  result: PaperCommandResult | null | undefined,
): string {
  return result?.message ?? result?.code ?? `${commandLabel(command)} refused`;
}

function unknownMessage(command: CommandName, reason: unknown): string {
  return (
    `${commandLabel(command)} outcome unknown: ${transportDetail(reason)}. ` +
    "Refresh status to see the server state before retrying."
  );
}

function reducer(state: PanelState, action: PanelAction): PanelState {
  switch (action.type) {
    case "status": {
      const next = action.status;
      return {
        ...state,
        status: next,
        unavailable: false,
        unknownOutcome: null,
        sentence: next.armed ? sentenceFor(next.entries_paused) : state.sentence,
      };
    }
    case "unavailable": {
      // Availability is unknown: drop the cached status rather than keep
      // acting on it, and never manufacture an unarmed response.
      return { ...state, status: null, unavailable: true, unknownOutcome: null };
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
      // Transport threw: the command may or may not have been applied.
      // Keep the last confirmed state, never claim success or disarm, and
      // never retry the command automatically.
      return { ...state, pending: null, unknownOutcome: action.message };
    }
    case "command-ok": {
      return {
        ...state,
        pending: null,
        errorMessage: null,
        unknownOutcome: null,
        status: action.status,
        sentence: action.sentence ?? state.sentence,
      };
    }
  }
}

export function StatusPanel({ client }: StatusPanelProps): JSX.Element {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  // Synchronous guard so a rapid double click cannot dispatch a duplicate
  // command before React re-renders the disabled buttons.
  const inFlightRef = useRef(false);
  // Bumped on every request start and on unmount so a late response from a
  // superseded request never updates the panel.
  const epochRef = useRef(0);

  useEffect(() => {
    const epoch = ++epochRef.current;
    client
      .getStatus()
      .then((next) => {
        if (epoch !== epochRef.current) {
          return;
        }
        dispatch({ type: "status", status: next });
      })
      .catch(() => {
        if (epoch !== epochRef.current) {
          return;
        }
        // A failed lookup means availability is unknown; never poll
        // automatically and never claim an unarmed state.
        dispatch({ type: "unavailable" });
      });
    return () => {
      epochRef.current += 1;
    };
  }, [client]);

  const refreshStatus = async (): Promise<void> => {
    if (inFlightRef.current) {
      return;
    }
    inFlightRef.current = true;
    const epoch = ++epochRef.current;
    try {
      const next = await client.getStatus();
      if (epoch !== epochRef.current) {
        return;
      }
      dispatch({ type: "status", status: next });
    } catch (reason) {
      if (epoch !== epochRef.current) {
        return;
      }
      // A read failure must be surfaced, never swallowed: the panel keeps
      // its last confirmed state and stays explicitly refreshable.
      dispatch({
        type: "unknown-outcome",
        message:
          `Status refresh failed: ${transportDetail(reason)}. ` +
          "The last confirmed state is shown; refresh to reconcile.",
      });
    } finally {
      inFlightRef.current = false;
    }
  };

  const runCommand = async (
    command: CommandName,
    action: () => Promise<PaperCommandResult>,
    onConfirmed: () => { status: PaperStatus | null; sentence?: EntriesSentence },
  ): Promise<void> => {
    if (inFlightRef.current) {
      return;
    }
    const current = state.status;
    if (!current?.armed || !current.venue || !current.pair) {
      return;
    }
    inFlightRef.current = true;
    const epoch = ++epochRef.current;
    dispatch({ type: "command-start", command });
    try {
      let result: PaperCommandResult;
      try {
        result = await action();
      } catch (reason) {
        // Transport threw: the outcome is unknown. No optimistic state, no
        // automatic retry; the user reconciles with an explicit refresh.
        if (epoch === epochRef.current) {
          dispatch({
            type: "unknown-outcome",
            message: unknownMessage(command, reason),
          });
        }
        return;
      }
      if (epoch !== epochRef.current) {
        return;
      }
      if (!isConfirmedOk(result)) {
        // Refused, or the response was malformed/ambiguous: keep the
        // confirmed state and surface the backend's own refusal message.
        dispatch({
          type: "command-refused",
          message: refusalMessage(command, result),
        });
        return;
      }
      const applied = onConfirmed();
      dispatch({
        type: "command-ok",
        status: applied.status,
        sentence: applied.sentence,
      });
      if (command !== "disarm") {
        // Reconcile the sentence with the server after a confirmed command:
        // a single follow-up read, not polling.
        try {
          const next = await client.getStatus();
          if (epoch === epochRef.current) {
            dispatch({ type: "status", status: next });
          }
        } catch (reason) {
          // The sentence already reflects the backend-confirmed command;
          // only the reconciliation read failed, so say so truthfully.
          if (epoch === epochRef.current) {
            dispatch({
              type: "unknown-outcome",
              message:
                `Status refresh failed: ${transportDetail(reason)}. ` +
                "The command was confirmed; refresh to reconcile.",
            });
          }
        }
      }
    } finally {
      inFlightRef.current = false;
    }
  };

  const handlePause = (): Promise<void> => {
    const current = state.status;
    return runCommand(
      "pause",
      () => client.pauseEntries(current?.venue ?? "", current?.pair ?? ""),
      () => ({ status: current, sentence: "Entries paused" as EntriesSentence }),
    );
  };

  const handleResume = (): Promise<void> => {
    const current = state.status;
    return runCommand(
      "resume",
      () => client.resumeEntries(current?.venue ?? "", current?.pair ?? ""),
      () => ({ status: current, sentence: "Entries active" as EntriesSentence }),
    );
  };

  const handleDisarm = (): Promise<void> => {
    const current = state.status;
    return runCommand(
      "disarm",
      () => client.disarm(current?.venue ?? "", current?.pair ?? ""),
      () => ({
        // The backend confirmed the disarm: the workstation has no armed
        // pack anymore, so the controls disappear.
        status: { schema_version: "1", armed: false },
        sentence: "Entries active" as EntriesSentence,
      }),
    );
  };

  const paperControls =
    state.status?.armed === true &&
    state.status.venue &&
    state.status.pair &&
    state.status.mode === "paper";

  const busy = state.pending !== null;
  const unknownAlert =
    state.unknownOutcome !== null ? (
      <p
        className="kbot-paper-status__unknown"
        role="alert"
        data-testid="paper-status-unknown"
      >
        {state.unknownOutcome}
      </p>
    ) : null;

  return (
    <section
      className="kbot-paper-status"
      role="region"
      aria-label="Paper controls"
      data-testid="paper-status-panel"
      data-pending={state.pending ?? ""}
    >
      <header className="kbot-paper-status__head">
        <h2 className="kbot-paper-status__title">Paper status</h2>
      </header>
      <div className="kbot-paper-status__body">
        {paperControls ? (
          <>
            <p
              className="kbot-paper-status__entries"
              data-testid="paper-status-entries"
            >
              {state.sentence}
            </p>
            <p
              className="kbot-paper-status__pack"
              data-testid="paper-status-pack"
            >
              {state.status?.pack_id} on {state.status?.venue}{" "}
              {state.status?.pair}
            </p>
            <div className="kbot-paper-status__actions">
              <button
                type="button"
                className="kbot-paper-status__action"
                disabled={busy}
                onClick={() => {
                  void handlePause();
                }}
              >
                {state.pending === "pause" ? "Pausing…" : "Pause entries"}
              </button>
              <button
                type="button"
                className="kbot-paper-status__action"
                disabled={busy}
                onClick={() => {
                  void handleResume();
                }}
              >
                {state.pending === "resume" ? "Resuming…" : "Resume entries"}
              </button>
              <button
                type="button"
                className="kbot-paper-status__action"
                disabled={busy}
                onClick={() => {
                  void handleDisarm();
                }}
              >
                {state.pending === "disarm" ? "Disarming…" : "Disarm"}
              </button>
              <PaperStatusCsvExport status={state.status} />
              <button
                type="button"
                className="kbot-paper-status__action"
                disabled={busy}
                onClick={() => {
                  void refreshStatus();
                }}
              >
                Refresh status
              </button>
            </div>
            {unknownAlert}
            {state.errorMessage !== null ? (
              <p
                className="kbot-paper-status__error"
                role="alert"
                data-testid="paper-status-error"
              >
                {state.errorMessage}
              </p>
            ) : null}
          </>
        ) : state.status?.armed ? (
          <p className="kbot-paper-status__empty" data-testid="paper-status-empty">
            Controls unavailable
          </p>
        ) : state.unavailable ? (
          <>
            <p
              className="kbot-paper-status__empty"
              role="alert"
              data-testid="paper-status-unavailable"
            >
              Paper status unavailable
            </p>
            <div className="kbot-paper-status__actions">
              <button
                type="button"
                className="kbot-paper-status__action"
                onClick={() => {
                  void refreshStatus();
                }}
              >
                Retry status
              </button>
            </div>
            {unknownAlert}
          </>
        ) : state.status === null ? (
          // No response yet: availability is unknown, so no unarmed claim
          // and no command controls until a real status arrives.
          <p className="kbot-paper-status__empty" data-testid="paper-status-loading">
            Checking paper status…
          </p>
        ) : (
          <p
            className="kbot-paper-status__empty"
            data-testid="paper-status-empty"
          >
            No pack armed
          </p>
        )}
      </div>
    </section>
  );
}