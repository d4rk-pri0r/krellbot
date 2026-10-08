import { useEffect, useReducer, useRef, useState, type JSX } from "react";
import type {
  PaperArmDraftSummary,
  PaperClient,
  PaperCommandResult,
  PaperStatus,
} from "./client";
import { PaperStatusCsvExport } from "./PaperStatusCsvExport";
import { RehearsalPanel } from "./RehearsalPanel";
import type { RehearsalClient } from "./rehearsalClient";
import { summarizePaperCommandRefusal } from "./paperCommandRefusalSummary";

export type {
  PaperArmDraftSummary,
  PaperClient,
  PaperCommandResult,
  PaperStatus,
} from "./client";

export type StatusPanelProps = {
  client: PaperClient;
};

type EntriesSentence = "Entries active" | "Entries paused";

type CommandName = "pause" | "resume" | "disarm";

/** Arm venues offered by the paper surface (paper mode only). */
const ARM_VENUES: readonly string[] = ["kraken"];

const DEFAULT_PAPER_BALANCE = "1000";

/**
 * A plain decimal string, the shape the backend parses with ``Decimal``.
 * ``1``, ``1.5``, ``0.25`` — but not ``1e3``, ``.5`` or an empty string.
 */
const DECIMAL_PATTERN = /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;

export function isValidPaperBalance(value: string): boolean {
  return DECIMAL_PATTERN.test(value);
}

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

function commandLabel(command: CommandName | "arm"): string {
  if (command === "pause") return "Pause";
  if (command === "resume") return "Resume";
  if (command === "arm") return "Arm";
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
  command: CommandName | "arm",
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

/**
 * The paper arm form: pick an existing owned, runnable revision, enter a
 * paper balance and arm it through the authenticated ``paper.arm``
 * command. Only backend-confirmed outcomes change the visible state; a
 * refusal keeps the form, a transport failure is surfaced as unknown.
 */
function ArmForm({ client }: { client: PaperClient }): JSX.Element | null {
  const canArm =
    typeof client === "object" &&
    client !== null &&
    typeof client.arm === "function" &&
    typeof client.listOwnedDrafts === "function";

  const [drafts, setDrafts] = useState<PaperArmDraftSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [revisionId, setRevisionId] = useState("");
  const [venue, setVenue] = useState(ARM_VENUES[0]);
  const [balance, setBalance] = useState(DEFAULT_PAPER_BALANCE);
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [unknownOutcome, setUnknownOutcome] = useState<string | null>(null);
  const inFlightRef = useRef(false);

  useEffect(() => {
    if (!canArm) {
      return;
    }
    let cancelled = false;
    const list = client.listOwnedDrafts;
    if (list === undefined) {
      return;
    }
    list
      .call(client)
      .then((rows) => {
        if (cancelled) {
          return;
        }
        // Only runnable (validated/deployed) revisions may be armed;
        // the backend refuses the rest, so they are not offered.
        const armable = rows.filter((row) => row.runnable === true);
        setDrafts(armable);
        setLoadError(null);
        setRevisionId((current) =>
          current === "" && armable.length > 0 ? armable[0].revision_id : current,
        );
      })
      .catch((reason: unknown) => {
        if (cancelled) {
          return;
        }
        // A failed listing is unknown, never an empty-list claim.
        setDrafts(null);
        setLoadError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [client, canArm]);

  if (!canArm) {
    // A legacy injected client without the arm surface: say so instead
    // of pretending arming is possible.
    return (
      <div
        className="kbot-paper-status__arm"
        data-testid="paper-arm-unavailable"
      >
        <h3 className="kbot-paper-status__arm-title">Arm a paper pack</h3>
        <p className="kbot-paper-status__empty">
          Arming controls unavailable
        </p>
      </div>
    );
  }

  const balanceValid = isValidPaperBalance(balance);
  const armDisabled = pending || !balanceValid || revisionId === "";

  const handleArm = async (): Promise<void> => {
    const arm = client.arm;
    if (arm === undefined || inFlightRef.current || revisionId === "") {
      return;
    }
    inFlightRef.current = true;
    setPending(true);
    setErrorMessage(null);
    setUnknownOutcome(null);
    try {
      let result: PaperCommandResult;
      try {
        result = await arm.call(client, {
          revision_id: revisionId,
          venue,
          mode: "paper",
          paper_balance: balance,
        });
      } catch (reason) {
        // Transport threw or the backend refused with an HTTP error
        // whose body the client kept on a typed error: the command may
        // or may not have been applied. No optimistic state, no retry.
        setUnknownOutcome(
          reason instanceof Error ? reason.message : String(reason),
        );
        return;
      }
      if (!isConfirmedOk(result)) {
        setErrorMessage(refusalMessage("arm", result));
        return;
      }
      // The arm is confirmed by the backend. The visible armed state
      // itself comes from the panel's status refresh, never from here.
      setUnknownOutcome(null);
      setErrorMessage(null);
    } finally {
      setPending(false);
      inFlightRef.current = false;
    }
  };

  return (
    <div className="kbot-paper-status__arm" data-testid="paper-arm-form">
      <h3 className="kbot-paper-status__arm-title">Arm a paper pack</h3>
      {loadError !== null && drafts === null ? (
        <>
          <p
            className="kbot-paper-status__empty"
            role="alert"
            data-testid="paper-arm-load-failed"
          >
            Saved revisions unavailable
          </p>
          <p className="kbot-paper-status__error" data-testid="paper-arm-error">
            {loadError}
          </p>
          <button
            type="button"
            className="kbot-paper-status__action"
            onClick={() => {
              // An explicit retry is a new user action: reload the list.
              const list = client.listOwnedDrafts;
              if (list === undefined || inFlightRef.current) {
                return;
              }
              setLoadError(null);
              list
                .call(client)
                .then((rows) => {
                  const armable = rows.filter((row) => row.runnable === true);
                  setDrafts(armable);
                  setRevisionId((current) =>
                    current === "" && armable.length > 0
                      ? armable[0].revision_id
                      : current,
                  );
                })
                .catch((reason: unknown) => {
                  setDrafts(null);
                  setLoadError(
                    reason instanceof Error ? reason.message : String(reason),
                  );
                });
            }}
          >
            Retry revisions
          </button>
        </>
      ) : drafts === null ? (
        <p className="kbot-paper-status__empty" data-testid="paper-arm-loading">
          Loading saved revisions…
        </p>
      ) : drafts.length === 0 ? (
        <p className="kbot-paper-status__empty" data-testid="paper-arm-empty">
          No runnable saved revisions
        </p>
      ) : (
        <>
          <label
            className="kbot-paper-status__field"
            htmlFor="paper-arm-revision"
          >
            Saved revision
            <select
              id="paper-arm-revision"
              className="kbot-paper-status__select"
              data-testid="paper-arm-revision"
              value={revisionId}
              onChange={(event) => {
                setRevisionId(event.target.value);
              }}
              disabled={pending}
            >
              {drafts.map((row) => (
                <option key={row.revision_id} value={row.revision_id}>
                  {row.revision_id}
                  {row.label !== "" ? ` — ${row.label}` : ""}
                  {row.pair !== "" ? ` (${row.pair})` : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="kbot-paper-status__field" htmlFor="paper-arm-venue">
            Venue
            <select
              id="paper-arm-venue"
              className="kbot-paper-status__select"
              data-testid="paper-arm-venue"
              value={venue}
              onChange={(event) => {
                setVenue(event.target.value);
              }}
              disabled={pending}
            >
              {ARM_VENUES.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label
            className="kbot-paper-status__field"
            htmlFor="paper-arm-balance"
          >
            Paper balance
            <input
              id="paper-arm-balance"
              className="kbot-paper-status__input"
              data-testid="paper-arm-balance"
              type="text"
              inputMode="decimal"
              value={balance}
              onChange={(event) => {
                setBalance(event.target.value);
              }}
              disabled={pending}
            />
          </label>
          {!balanceValid ? (
            <p
              className="kbot-paper-status__error"
              data-testid="paper-arm-balance-error"
            >
              Enter the paper balance as a plain decimal, e.g. 1000 or 250.50
            </p>
          ) : null}
          <button
            type="button"
            className="kbot-paper-status__action"
            disabled={armDisabled}
            onClick={() => {
              void handleArm();
            }}
          >
            {pending ? "Arming…" : "Arm paper pack"}
          </button>
          {unknownOutcome !== null ? (
            <p
              className="kbot-paper-status__unknown"
              role="alert"
              data-testid="paper-arm-unknown"
            >
              Arm outcome unknown: {unknownOutcome}. Refresh status to see the
              server state before retrying.
            </p>
          ) : null}
          {errorMessage !== null ? (
            <p
              className="kbot-paper-status__error"
              role="alert"
              data-testid="paper-arm-error"
            >
              {errorMessage}
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

export function StatusPanel({ client }: StatusPanelProps): JSX.Element {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  // Synchronous guard so a rapid double click cannot dispatch a duplicate
  // command before React re-renders the disabled buttons.
  const inFlightRef = useRef(false);
  // Bumped on every request start and on unmount so a late response from a
  // superseded request never updates the panel.
  const epochRef = useRef(0);

  // The rehearsal surface is a separate client behind the same paper
  // panel: a legacy injected client without the factory renders the
  // honest unavailable state instead of crashing.
  const canRehearse =
    typeof client === "object" &&
    client !== null &&
    typeof client.createRehearsalClient === "function";
  const [rehearsalClient] = useState<RehearsalClient | null>(() =>
    canRehearse
      ? (client.createRehearsalClient as () => RehearsalClient)()
      : null,
  );

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
          // Confirmed unarmed: offer the arm form and the rehearsal
          // surface in the existing paper panel.
          <>
            <p className="kbot-paper-status__empty" data-testid="paper-status-empty">
              No pack armed
            </p>
            <ArmForm client={client} />
            <RehearsalPanel client={rehearsalClient} />
          </>
        )}
      </div>
    </section>
  );
}