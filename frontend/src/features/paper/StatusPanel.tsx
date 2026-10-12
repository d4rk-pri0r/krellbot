import { useCallback, useEffect, useReducer, useRef, useState, type JSX } from "react";
import "./StatusPanel.signal.css";
import { getCsrf } from "../../session";
import type {
  PaperArmDraftSummary,
  PaperClient,
  PaperCommandResult,
  PaperPosition,
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
  PaperPosition,
  PaperStatus,
} from "./client";

export type StatusPanelProps = {
  client: PaperClient;
};

type EntriesSentence = "Entries active" | "Entries paused";

type CommandName = "pause" | "resume" | "disarm" | "raise_stop";

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

/** Remembers the last successfully armed balance across mounts. */
const LAST_ARMED_BALANCE_STORAGE_KEY = "krellbot.paper.lastArmedBalance";

function readLastArmedBalance(): string | null {
  if (
    typeof window === "undefined" ||
    typeof window.localStorage === "undefined"
  ) {
    return null;
  }
  try {
    return window.localStorage.getItem(LAST_ARMED_BALANCE_STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeLastArmedBalance(value: string): void {
  if (
    typeof window === "undefined" ||
    typeof window.localStorage === "undefined"
  ) {
    return;
  }
  try {
    window.localStorage.setItem(LAST_ARMED_BALANCE_STORAGE_KEY, value);
  } catch {
    // Storage may be unavailable (quota, privacy mode): the affordance is
    // best-effort and never blocks arming.
  }
}

/** A stored value is offered again only as a usable decimal balance. */
function initialArmBalance(): string {
  const stored = readLastArmedBalance();
  if (
    stored !== null &&
    isValidPaperBalance(stored) &&
    Number(stored) > 0
  ) {
    return stored;
  }
  return DEFAULT_PAPER_BALANCE;
}

type PanelState = {
  status: PaperStatus | null;
  sentence: EntriesSentence;
  errorMessage: string | null;
  unavailable: boolean;
  pending: CommandName | null;
  unknownOutcome: string | null;
  /** Backend-confirmed raise-stop echo, mirrored verbatim from `message`. */
  raiseStopEcho: string | null;
  /** Owned position read from `GET /api/v1/paper/position`; null = none read. */
  position: PaperPosition | null;
  /** Honest failure surface for a position read that did not decode. */
  positionError: string | null;
};

const INITIAL_STATE: PanelState = {
  status: null,
  sentence: "Entries active",
  errorMessage: null,
  unavailable: false,
  pending: null,
  unknownOutcome: null,
  raiseStopEcho: null,
  position: null,
  positionError: null,
};

type PanelAction =
  | { type: "status"; status: PaperStatus }
  | { type: "unavailable" }
  | { type: "command-start"; command: CommandName }
  | { type: "command-refused"; message: string }
  | { type: "unknown-outcome"; message: string }
  | { type: "position"; position: PaperPosition }
  | { type: "position-failed"; message: string }
  | {
      type: "command-ok";
      status: PaperStatus | null;
      sentence?: EntriesSentence;
      raiseStopEcho?: string | null;
    };

function sentenceFor(entries_paused: boolean | undefined): EntriesSentence {
  return entries_paused ? "Entries paused" : "Entries active";
}

function commandLabel(command: CommandName | "arm"): string {
  if (command === "pause") return "Pause";
  if (command === "resume") return "Resume";
  if (command === "arm") return "Arm";
  if (command === "raise_stop") return "Raise stop";
  return "Disarm";
}

/**
 * The raise-stop read surface is closed-shape (no `stop` on status reads),
 * so the backend's success message — ``stop set: <venue> <pair> -> <new>``
 * — is the only in-tree source for the new resting stop. Mirror it verbatim;
 * the visible sentence quotes it rather than recomputing a value.
 */
function raiseStopSentenceFromMessage(message: unknown): string | null {
  if (typeof message !== "string") {
    return null;
  }
  const arrow = message.lastIndexOf("-> ");
  if (arrow === -1) {
    return null;
  }
  const tail = message.slice(arrow + 3).trim();
  return tail.length > 0 ? `raised stop to ${tail}` : null;
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

/**
 * The owned-position sentence the armed paper branch renders. Every value
 * is quoted verbatim from the `GET /api/v1/paper/position` body — the
 * decimal strings are never re-formatted or zero-trimmed, so the sentence
 * is evidence about the persisted `paper-<venue>.json`, not a computation.
 */
function positionSentence(position: PaperPosition): string {
  const parts = (position.holdings ?? []).map((row) => `${row.qty} ${row.symbol}`);
  const owned = parts.length > 0 ? parts.join(", ") : "no open position";
  const quote = position.pair !== undefined ? position.pair.slice(-3) : "";
  const cash =
    position.free_cash !== undefined
      ? `${position.free_cash}${quote !== "" ? ` ${quote}` : ""}`
      : "";
  return cash !== "" ? `Owned position: ${owned} — free cash ${cash}` : `Owned position: ${owned}`;
}

/**
 * POST ``paper.raise_stop`` with the same command envelope the paper client
 * uses, dispatched directly from the panel: deliberately not a PaperClient
 * method so this slice touches no client surface. Refusals arrive as
 * HTTP 200 bodies with ``ok: false``; a non-2xx response is a transport
 * failure and maps to the unknown-outcome path, exactly like disarm.
 */
async function postRaiseStop(
  venue: string,
  pair: string,
  newStop: string,
): Promise<PaperCommandResult> {
  const response = await fetch("/api/v1/commands", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Krellbot-CSRF": getCsrf(),
    },
    body: JSON.stringify({
      schema_version: "1",
      command: "paper.raise_stop",
      payload: { venue, pair, new_stop: newStop },
    }),
  });
  if (!response.ok) {
    throw new Error(`paper.raise_stop failed: ${response.status}`);
  }
  return (await response.json()) as PaperCommandResult;
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
        // A confirmed disarm/unarmed read invalidates the cached owned
        // position: the armed branch that renders it is gone, and the
        // next arm must re-read rather than reuse a stale sentence.
        position: next.armed ? state.position : null,
        positionError: next.armed ? state.positionError : null,
      };
    }
    case "unavailable": {
      // Availability is unknown: drop the cached status rather than keep
      // acting on it, and never manufacture an unarmed response.
      return {
        ...state,
        status: null,
        unavailable: true,
        unknownOutcome: null,
        position: null,
        positionError: null,
      };
    }
    case "command-start": {
      return {
        ...state,
        pending: action.command,
        errorMessage: null,
        unknownOutcome: null,
        raiseStopEcho: null,
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
    case "position": {
      return { ...state, position: action.position, positionError: null };
    }
    case "position-failed": {
      // A refused wire variant or a failed read is surfaced, never
      // rendered as a zero position.
      return { ...state, position: null, positionError: action.message };
    }
    case "command-ok": {
      return {
        ...state,
        pending: null,
        errorMessage: null,
        unknownOutcome: null,
        status: action.status,
        sentence: action.sentence ?? state.sentence,
        raiseStopEcho: action.raiseStopEcho ?? state.raiseStopEcho,
        position: action.status?.armed ? state.position : null,
        positionError: action.status?.armed ? state.positionError : null,
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
function ArmForm({
  client,
  onArmConfirmed,
}: {
  client: PaperClient;
  /**
   * Fired exactly once per backend-confirmed arm (never on a refusal or an
   * unknown transport outcome): the panel bumps its arm epoch and performs
   * one bounded status read so the armed controls appear immediately.
   */
  onArmConfirmed: () => void;
}): JSX.Element | null {
  const canArm =
    typeof client === "object" &&
    client !== null &&
    typeof client.arm === "function" &&
    typeof client.listOwnedDrafts === "function";

  const [drafts, setDrafts] = useState<PaperArmDraftSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [revisionId, setRevisionId] = useState("");
  const [venue, setVenue] = useState(ARM_VENUES[0]);
  const [balance, setBalance] = useState(initialArmBalance);
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
      // Offer this balance again on the next arm attempt in this session.
      writeLastArmedBalance(balance);
      // Signal the panel: its post-arm read makes the armed controls render
      // without a manual refresh, navigation or remount.
      onArmConfirmed();
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
            className="kbot-paper-status__action kbot-feature__status-panel-root__action"
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
              className="kbot-paper-status__select kbot-feature__status-panel-root__control"
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
              className="kbot-paper-status__select kbot-feature__status-panel-root__control"
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
              className="kbot-paper-status__input kbot-feature__status-panel-root__control"
              data-testid="paper-arm-balance"
              type="text"
              inputMode="decimal"
              value={balance}
              onChange={(event) => {
                const next = event.target.value;
                if (next === "") {
                  // An explicit clear is remembered: never silently refill
                  // the field with a stale balance next time.
                  writeLastArmedBalance("");
                }
                setBalance(next);
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
            className="kbot-paper-status__action kbot-feature__status-panel-root__action"
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
  // Same discipline for the owned-position read, which is a separate
  // request from the status read.
  const positionEpochRef = useRef(0);

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

  // Bumped exactly once per backend-confirmed arm (never on refusal or
  // unknown outcome): mirrors the epoch-guarded refreshSignal shape the
  // Editor inline control uses. Zero until the first confirmed arm.
  const [armEpoch, setArmEpoch] = useState(0);

  useEffect(() => {
    if (armEpoch === 0) {
      return;
    }
    const epoch = ++epochRef.current;
    let cancelled = false;
    client
      .getStatus()
      .then((next) => {
        if (cancelled || epoch !== epochRef.current) {
          return;
        }
        dispatch({ type: "status", status: next });
      })
      .catch(() => {
        if (cancelled || epoch !== epochRef.current) {
          return;
        }
        // The post-arm read failed: availability is unknown, never an
        // unarmed claim and never a second automatic read.
        dispatch({ type: "unavailable" });
      });
    return () => {
      cancelled = true;
      epochRef.current += 1;
    };
    // `armEpoch` is the only automatic re-read trigger besides the client
    // itself: one bounded read per confirmed arm, no timer, no polling.
  }, [client, armEpoch]);

  const handleArmConfirmed = useCallback((): void => {
    setArmEpoch((current) => current + 1);
  }, []);


  // The owned position is a separate read from the status: the status body
  // is closed-shape and never carries cash or quantity, so the armed branch
  // reconciles the position sentence from `GET /api/v1/paper/position`
  // whenever a confirmed status says a pack is armed. One read per confirmed
  // armed status, never polling; a legacy client without the method keeps
  // the honest unavailable line instead of a manufactured position.
  const positionReadable =
    typeof client === "object" &&
    client !== null &&
    typeof client.getPosition === "function";
  useEffect(() => {
    if (!positionReadable || state.status?.armed !== true) {
      return;
    }
    const epoch = ++positionEpochRef.current;
    const read = client.getPosition;
    if (read === undefined) {
      return;
    }
    read
      .call(client)
      .then((position) => {
        if (epoch !== positionEpochRef.current) {
          return;
        }
        dispatch({ type: "position", position });
      })
      .catch((reason: unknown) => {
        if (epoch !== positionEpochRef.current) {
          return;
        }
        // A refused wire variant or a failed transport is never rendered
        // as a zero position: say the position is unavailable.
        dispatch({
          type: "position-failed",
          message: transportDetail(reason),
        });
      });
    return () => {
      positionEpochRef.current += 1;
    };
  }, [client, positionReadable, state.status]);
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
        raiseStopEcho:
          command === "raise_stop"
            ? (raiseStopSentenceFromMessage(result.message) ??
              (typeof result.message === "string" && result.message.length > 0
                ? result.message
                : null))
            : undefined,
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

  const [raiseStopValue, setRaiseStopValue] = useState("");
  const raiseStopValid = isValidPaperBalance(raiseStopValue);

  const handleRaiseStop = (): Promise<void> => {
    const current = state.status;
    return runCommand(
      "raise_stop",
      () =>
        postRaiseStop(
          current?.venue ?? "",
          current?.pair ?? "",
          raiseStopValue,
        ),
      // The read surface never carries the stop, so the confirmed state
      // stays as-is; the visible truth is the backend echo plus the
      // follow-up reconciliation read inside runCommand.
      () => ({ status: current }),
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
      className="kbot-paper-status kbot-feature__status-panel-root"
      role="region"
      aria-label="Paper controls"
      data-testid="paper-status-panel"
      data-pending={state.pending ?? ""}
    >
      <header className="kbot-paper-status__head">
        <h2 className="kbot-paper-status__title">Paper status</h2>
        {/* Honest preview identity in the same seafoam badge + caption
            vocabulary as Navigation / PaperStatusCsvExport: purely
            presentational, it never gates any control below. */}
        <p className="kbot-feature__status-panel-root__meta">
          <span
            className="kbot-feature__status-panel-root__badge"
            data-testid="paper-status-local-preview"
          >
            Local preview
          </span>
          <span
            className="kbot-feature__status-panel-root__note"
            data-testid="paper-status-live-unavailable"
          >
            Live trading unavailable
          </span>
        </p>
      </header>
      <div className="kbot-paper-status__body">
        {paperControls ? (
          <>
            <p
              className={
                "kbot-paper-status__entries kbot-feature__status-panel-root__entries" +
                (state.sentence === "Entries paused"
                  ? " kbot-feature__status-panel-root__entries--paused"
                  : "")
              }
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
            {/* The owned position + free cash, read verbatim from the
                persisted paper state via `GET /api/v1/paper/position`.
                Quoted, never computed: a refused wire variant or a failed
                read renders the honest unavailable line instead of a
                zero position. */}
            {state.positionError !== null ? (
              <p
                className="kbot-paper-status__empty"
                role="alert"
                data-testid="paper-position-unavailable"
              >
                Owned position unavailable: {state.positionError}
              </p>
            ) : state.position !== null ? (
              <p
                className="kbot-paper-status__position"
                data-testid="paper-position"
              >
                {positionSentence(state.position)}
              </p>
            ) : positionReadable ? (
              <p
                className="kbot-paper-status__empty"
                data-testid="paper-position-pending"
              >
                Reading owned position…
              </p>
            ) : (
              <p
                className="kbot-paper-status__empty"
                data-testid="paper-position-unavailable"
              >
                Owned position unavailable
              </p>
            )}
            <div className="kbot-paper-status__actions">
              <button
                type="button"
                className="kbot-paper-status__action kbot-feature__status-panel-root__action"
                disabled={busy}
                onClick={() => {
                  void handlePause();
                }}
              >
                {state.pending === "pause" ? "Pausing…" : "Pause entries"}
              </button>
              <button
                type="button"
                className="kbot-paper-status__action kbot-feature__status-panel-root__action"
                disabled={busy}
                onClick={() => {
                  void handleResume();
                }}
              >
                {state.pending === "resume" ? "Resuming…" : "Resume entries"}
              </button>
              <button
                type="button"
                className="kbot-paper-status__action kbot-feature__status-panel-root__action kbot-feature__status-panel-root__action--danger"
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
                className="kbot-paper-status__action kbot-feature__status-panel-root__action"
                disabled={busy}
                onClick={() => {
                  void refreshStatus();
                }}
              >
                Refresh status
              </button>
            </div>
            {/* Raise the resting stop. Mounted only in the armed paper
                branch: the closed-shape status read never carries the
                current stop, so there is nothing to prefill and no
                below-current check client-side — the backend's
                invalid_stop refusal is the single validator. */}
            <div
              className="kbot-paper-status__raise-stop"
              data-testid="paper-raise-stop"
            >
              <label
                className="kbot-paper-status__field"
                htmlFor="paper-raise-stop-input"
              >
                New resting stop
                <input
                  id="paper-raise-stop-input"
                  className="kbot-paper-status__input kbot-feature__status-panel-root__control"
                  data-testid="paper-raise-stop-input"
                  type="text"
                  inputMode="decimal"
                  value={raiseStopValue}
                  onChange={(event) => {
                    setRaiseStopValue(event.target.value);
                  }}
                  disabled={busy}
                />
              </label>
              <button
                type="button"
                className="kbot-paper-status__action kbot-feature__status-panel-root__action"
                data-testid="paper-raise-stop-apply"
                disabled={busy || !raiseStopValid}
                onClick={() => {
                  void handleRaiseStop();
                }}
              >
                {state.pending === "raise_stop"
                  ? "Raising…"
                  : "Apply new stop"}
              </button>
              {!raiseStopValid ? (
                <p
                  className="kbot-paper-status__error"
                  data-testid="paper-raise-stop-error"
                >
                  Enter the new stop as a plain decimal, e.g. 1050 or 250.50
                </p>
              ) : null}
            </div>
            {state.raiseStopEcho !== null ? (
              <p
                className="kbot-feature__status-panel-root__ok"
                data-testid="paper-raise-stop-ok"
              >
                {state.raiseStopEcho}
              </p>
            ) : null}
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
                className="kbot-paper-status__action kbot-feature__status-panel-root__action"
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
          // Confirmed unarmed: offer the arm form.
          <>
            <p className="kbot-paper-status__empty" data-testid="paper-status-empty">
              No pack armed
            </p>
            <ArmForm client={client} onArmConfirmed={handleArmConfirmed} />
          </>
        )}
        {/* The isolated synthetic rehearsal surface is mounted exactly once
            outside the armed/unarmed paper branch: its own client, commands
            and disclosure stay accessible whatever the ordinary paper pack
            state is, and it never remounts on a paper state transition. */}
        <RehearsalPanel client={rehearsalClient} />
      </div>
    </section>
  );
}