import { getCsrf } from "../../session";

export type ExecutionPack = Record<string, unknown>;

export const DRAFTS_PATH = "/api/v1/strategies/drafts/";

function buildUrl(revisionId: string): string {
  return `${DRAFTS_PATH}${encodeURIComponent(revisionId)}`;
}

export type ExecutionEditOutcome = {
  revisionId: string;
  pack: ExecutionPack;
};

/**
 * Persist a (possibly edited) pack as a NEW child revision of the
 * given revision. The server returns the new revision summary;
 * we surface ``revision_id`` (renamed ``revisionId``) and ``pack`` so
 * the caller can update the in-memory ``savedRevision`` without an
 * extra round-trip.
 */
export async function applyExecutionEdit(
  revisionId: string,
  pack: ExecutionPack,
): Promise<ExecutionEditOutcome> {
  const response = await fetch(buildUrl(revisionId), {
    method: "PUT",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Krellbot-CSRF": getCsrf(),
    },
    body: JSON.stringify({ pack }),
  });
  if (!response.ok) {
    throw new Error(`execution edit failed: ${response.status}`);
  }
  const body = (await response.json()) as {
    revision_id?: string;
    pack?: ExecutionPack;
  };
  return {
    revisionId: String(body.revision_id ?? ""),
    pack: (body.pack ?? {}) as ExecutionPack,
  };
}