import { getCsrf } from "../../session";

export type ExecutionPack = Record<string, unknown>;

export const DRAFTS_PATH = "/api/v1/strategies/drafts/";

// Fixed total read deadline (read-deadline-20261027): the save must
// settle within 10000ms across the response headers AND the JSON body.
export const EXECUTION_EDIT_READ_DEADLINE_MS = 10000;

function buildUrl(revisionId: string): string {
  return `${DRAFTS_PATH}${encodeURIComponent(revisionId)}`;
}

export type ExecutionOutcome = "created" | "unchanged" | "existing";

export type ExecutionEditOutcome = {
  revisionId: string;
  pack: ExecutionPack;
  outcome?: ExecutionOutcome;
  state?: string;
};

async function sendExecutionEdit(
  revisionId: string,
  pack: ExecutionPack,
  signal: AbortSignal,
): Promise<ExecutionEditOutcome> {
  const response = await fetch(buildUrl(revisionId), {
    method: "PUT",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Krellbot-CSRF": getCsrf(),
    },
    body: JSON.stringify({ pack }),
    signal,
  });
  if (!response.ok) {
    let code: string | undefined;
    let message: string | undefined;
    try {
      const body = (await response.json()) as {
        code?: string;
        message?: string;
      };
      code = typeof body.code === "string" ? body.code : undefined;
      message = typeof body.message === "string" ? body.message : undefined;
    } catch {
      throw new Error(`execution edit failed: ${response.status}`);
    }
    if (code === "strategy_id_mismatch") {
      throw new Error(`strategy_id_mismatch: ${message ?? response.status}`);
    }
    throw new Error(
      message ? `execution edit failed: ${response.status} ${message}` : `execution edit failed: ${response.status}`,
    );
  }
  const body = (await response.json()) as {
    revision_id?: string;
    pack?: ExecutionPack;
    outcome?: unknown;
    state?: unknown;
  };
  const outcomeRaw = body.outcome;
  const outcome: ExecutionOutcome | undefined =
    outcomeRaw === "created" ||
    outcomeRaw === "unchanged" ||
    outcomeRaw === "existing"
      ? outcomeRaw
      : undefined;
  const state =
    typeof body.state === "string" ? (body.state as string) : undefined;
  return {
    revisionId: String(body.revision_id ?? ""),
    pack: (body.pack ?? {}) as ExecutionPack,
    outcome,
    state,
  };
}

/**
 * Persist a (possibly edited) pack as a (possibly new) child revision
 * of the given revision. The server returns the revision summary;
 * the caller updates the in-memory ``savedRevision`` from
 * ``revisionId`` and ``pack`` without an extra round-trip.
 *
 * The server's ``outcome`` literal (created/unchanged/existing) and
 * ``state`` are surfaced verbatim — this function never invents them.
 *
 * The whole read — response headers and JSON body — is bounded by a
 * fixed ``EXECUTION_EDIT_READ_DEADLINE_MS`` deadline. A stalled read
 * rejects with an honest read-timeout Error, aborts the request this
 * call owns, and a late response from the expired attempt can never
 * settle this save. The deadline timer is cleared on every exit.
 */
export async function applyExecutionEdit(
  revisionId: string,
  pack: ExecutionPack,
): Promise<ExecutionEditOutcome> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(
        new Error(
          `execution edit read timed out after ${EXECUTION_EDIT_READ_DEADLINE_MS}ms`,
        ),
      );
    }, EXECUTION_EDIT_READ_DEADLINE_MS);
  });
  const read = sendExecutionEdit(revisionId, pack, controller.signal);
  // The expired attempt keeps its own rejection handled so the abort
  // or a late response cannot surface as an unhandled rejection after
  // the deadline already settled this save.
  void read.catch(() => {});
  try {
    return await Promise.race([read, deadline]);
  } finally {
    clearTimeout(timer);
  }
}