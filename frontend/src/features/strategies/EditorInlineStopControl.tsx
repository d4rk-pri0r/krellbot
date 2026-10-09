import { useEffect, useReducer, useRef, useState, type JSX } from "react";
import type {
  PaperClient,
  PaperCommandResult,
  PaperStatus,
} from "../paper/client";
import { summarizePaperCommandRefusal } from "../paper/paperCommandRefusalSummary";

export type { PaperClient } from "../paper/client";

export type EditorInlineStopControlProps = {
  paperClient: PaperClient;
};

type EntriesSentence = "Entries active" | "Entries paused";

type CommandName = "pause" | "resume" | "disarm" | "raise_stop";

type InlineState = {
  status: PaperStatus | null;
  sentence: EntriesSentence;
  errorMessage: string | null;
  pending: CommandName | null;
  unavailable: boolean;
  unknownOutcome: string | null;
  stopAt: string | null;
};

const INITIAL_STATE: InlineState = {
  status: null,
  sentence: "Entries active",
  errorMessage: null,
  pending: null,
  unavailable: false,
  unknownOutcome: null,
  stopAt: null,
};

type InlineAction =
  | { type: "status"; status: PaperStatus }
  | { type: "unavailable" }
  | { type: "command-start"; command: CommandName }
  | { type: "command-refused"; message: string }
  | { type: "unknown-outcome"; message: string }
  | {
      type: "command-ok";
      status: PaperStatus | null;
      sentence?: EntriesSentence;
      stopAt?: string | null;
    };

/**
 * A plain decimal string, the shape the backend parses with ``Decimal``:
 * ``1``, ``1.5``, ``0.25`` — but not ``1e3``, ``.5``, ``NaN``,
 * ``Infinity`` or an empty string.
 */
const STOP_DECIMAL_PATTERN = /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;

export function isValidRaiseStopDecimal(value: string): boolean {
  return STOP_DECIMAL_PATTERN.test(value);
}

/**
 * The read surface never carries the resting stop, so the only in-tree
 * source for the new resting stop is the success message echo
 * ``stop set: <venue> <pair> -> <new_stop>``.
 */
export function stopFromRaiseStopMessage(
  message: string | undefined,
): string | null {
  if (typeof message !== "string") {
    return null;
  }
  const marker = "->";
  const at = message.lastIndexOf(marker);
  if (at === -1) {
    return null;
  }
  const value = message.slice(at + marker.length).trim();
  return value.length > 0 ? value : null;
}

function sentenceFor(entries_paused: boolean | undefined): EntriesSentence {
  return entries_paused ? "Entries paused" : "Entries active";
}

function commandLabel(command: CommandName): string {
  if (command === "pause") return "Pause";
  if (command === "resume") return "Resume";
  if (command === "raise_stop") return "Apply new stop";
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
  return summarizePaperCommandRefusal(commandLabel(command), result).label;
}

function unknownMessage(command: CommandName, reason: unknown): string {
  return (
    `${commandLabel(command)} outcome unknown: ${transportDetail(reason)}. ` +
    "Refresh status to see the server state before retrying."
  );
}

function reducer(state: InlineState, action: InlineAction): InlineState {
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
        stopAt: action.stopAt !== undefined ? action.stopAt : state.stopAt,
      };
    }
  }
}

/**
 * Inline "stop this run" affordance for the strategy Editor: after arming
 * from the Editor the user can disarm, pause entries or resume entries
 * without leaving the Editor view. It reuses the same paper command
 * contract as the Paper tab's StatusPanel — only an explicit backend
 * ``ok: true`` changes visible state; refusals surface the backend's own
 * words, transport failures are surfaced as unknown and never retried.
 */
export function EditorInlineStopControl({
  paperClient,
}: EditorInlineStopControlProps): JSX.Element {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  // Typed raise-stop input value; validation happens on Apply.
  const [stopInput, setStopInput] = useState("");
  // Synchronous guard so a rapid double click cannot dispatch a duplicate
  // command before React re-renders the disabled buttons.
  const inFlightRef = useRef(false);
  // Bumped on every request start and on unmount so a late response from a
  // superseded request never updates the control.
  const epochRef = useRef(0);

  useEffect(() => {
    const epoch = ++epochRef.current;
    paperClient
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
  }, [paperClient]);

  const refreshStatus = async (): Promise<void> => {
    if (inFlightRef.current) {
      return;
    }
    inFlightRef.current = true;
    const epoch = ++epochRef.current;
    try {
      const next = await paperClient.getStatus();
      if (epoch !== epochRef.current) {
        return;
      }
      dispatch({ type: "status", status: next });
    } catch (reason) {
      if (epoch !== epochRef.current) {
        return;
      }
      // A read failure must be surfaced, never swallowed: the control keeps
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
    onConfirmed: (
      result: PaperCommandResult,
    ) => {
      status: PaperStatus | null;
      sentence?: EntriesSentence;
      stopAt?: string | null;
    },
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
      const applied = onConfirmed(result);
      dispatch({
        type: "command-ok",
        status: applied.status,
        sentence: applied.sentence,
        stopAt: applied.stopAt,
      });
      if (command !== "disarm") {
        // Reconcile with the server after a confirmed command: a single
        // follow-up read, not polling.
        try {
          const next = await paperClient.getStatus();
          if (epoch === epochRef.current) {
            dispatch({ type: "status", status: next });
          }
        } catch (reason) {
          // The state already reflects the backend-confirmed command;
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
      () => paperClient.pauseEntries(current?.venue ?? "", current?.pair ?? ""),
      () => ({ status: current, sentence: "Entries paused" as EntriesSentence }),
    );
  };

  const handleResume = (): Promise<void> => {
    const current = state.status;
    return runCommand(
      "resume",
      () => paperClient.resumeEntries(current?.venue ?? "", current?.pair ?? ""),
      () => ({ status: current, sentence: "Entries active" as EntriesSentence }),
    );
  };

  const handleDisarm = (): Promise<void> => {
    const current = state.status;
    return runCommand(
      "disarm",
      () => paperClient.disarm(current?.venue ?? "", current?.pair ?? ""),
      () => ({
        // The backend confirmed the disarm: the workstation has no armed
        // pack anymore, so the controls disappear.
        status: { schema_version: "1", armed: false },
        sentence: "Entries active" as EntriesSentence,
        stopAt: null,
      }),
    );
  };

  const armed =
    state.status?.armed === true &&
    state.status.venue !== undefined &&
    state.status.venue !== "" &&
    state.status.pair !== undefined &&
    state.status.pair !== "";

  const stopInputValid = isValidRaiseStopDecimal(stopInput);
  // The real HTTP client supplies raiseStop; a hand-rolled client that
  // cannot raise stops leaves the Apply control inert rather than broken.
  const canRaiseStop = armed && typeof paperClient.raiseStop === "function";

  const handleRaiseStop = (): Promise<void> => {
    const current = state.status;
    const raise = paperClient.raiseStop;
    // Local validation is shape-only: NaN/Infinity/1e3/.5/empty never
    // reach the wire. Below-or-equal is backend-only (CODE_INVALID_STOP).
    if (!stopInputValid || typeof raise !== "function") {
      return Promise.resolve();
    }
    const newStop = stopInput;
    return runCommand(
      "raise_stop",
      () => raise(current?.venue ?? "", current?.pair ?? "", newStop),
      (result) => ({
        status: current,
        // The success message echo is the only in-tree source for the
        // new resting stop ("stop set: <venue> <pair> -> <new_stop>").
        stopAt: stopFromRaiseStopMessage(result.message),
      }),
    );
  };

  const busy = state.pending !== null;

  return (
    <div
      className="kbot-strategy-editor__inline-stop"
      data-testid="editor-inline-stop"
    >
      <p
        className="kbot-strategy-editor__inline-stop-state"
        data-testid={
          armed
            ? "editor-inline-stop-entries"
            : state.unavailable
              ? "editor-inline-stop-unavailable"
              : state.status === null
                ? "editor-inline-stop-loading"
                : "editor-inline-stop-empty"
        }
      >
        {armed
          ? state.sentence
          : state.unavailable
            ? "Paper status unavailable"
            : state.status === null
              ? "Checking paper status…"
              : "No pack armed"}
      </p>
      <div className="kbot-strategy-editor__inline-stop-actions">
        <button
          type="button"
          data-testid="editor-inline-stop-pause"
          disabled={!armed || busy}
          onClick={() => {
            void handlePause();
          }}
        >
          {state.pending === "pause" ? "Pausing…" : "Pause entries"}
        </button>
        <button
          type="button"
          data-testid="editor-inline-stop-resume"
          disabled={!armed || busy}
          onClick={() => {
            void handleResume();
          }}
        >
          {state.pending === "resume" ? "Resuming…" : "Resume entries"}
        </button>
        <button
          type="button"
          data-testid="editor-inline-stop-disarm"
          disabled={!armed || busy}
          onClick={() => {
            void handleDisarm();
          }}
        >
          {state.pending === "disarm" ? "Disarming…" : "Disarm"}
        </button>
        {armed || state.unavailable ? (
          <button
            type="button"
            data-testid="editor-inline-stop-refresh"
            disabled={busy}
            onClick={() => {
              void refreshStatus();
            }}
          >
            Refresh status
          </button>
        ) : null}
      </div>
      {armed ? (
        <div className="kbot-strategy-editor__inline-stop-raise">
          <label
            htmlFor="editor-inline-stop-new-stop"
            data-testid="editor-inline-stop-new-stop-label"
          >
            New stop
          </label>
          <input
            id="editor-inline-stop-new-stop"
            type="text"
            inputMode="decimal"
            autoComplete="off"
            data-testid="editor-inline-stop-new-stop"
            disabled={busy}
            value={stopInput}
            onChange={(event) => {
              setStopInput(event.target.value);
            }}
            aria-invalid={!stopInputValid}
            placeholder="e.g. 1.25"
          />
          <button
            type="button"
            data-testid="editor-inline-stop-apply"
            disabled={!canRaiseStop || busy || !stopInputValid}
            title={
              !armed
                ? "Apply new stop is disabled while no pack is armed"
                : !canRaiseStop
                  ? "This paper client cannot raise stops"
                  : !stopInputValid
                    ? "Enter the new stop as a plain decimal, e.g. 1, 1.5 or 0.25"
                    : "Raise the resting stop to this value"
            }
            onClick={() => {
              void handleRaiseStop();
            }}
          >
            {state.pending === "raise_stop" ? "Applying…" : "Apply new stop"}
          </button>
          {armed && state.stopAt !== null ? (
            <span data-testid="editor-inline-stop-at">
              stop at {state.stopAt}
            </span>
          ) : null}
        </div>
      ) : null}
      {state.unknownOutcome !== null ? (
        <p
          role="alert"
          data-testid="editor-inline-stop-unknown"
          className="kbot-strategy-editor__error"
        >
          {state.unknownOutcome}
        </p>
      ) : null}
      {state.errorMessage !== null ? (
        <p
          role="alert"
          data-testid="editor-inline-stop-error"
          className="kbot-strategy-editor__error"
        >
          {state.errorMessage}
        </p>
      ) : null}
    </div>
  );
}
