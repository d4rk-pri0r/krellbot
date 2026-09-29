import { getCsrf } from "../../session";

export type ExecutionPack = Record<string, unknown>;

export const DRAFTS_PATH = "/api/v1/strategies/drafts/";

function buildUrl(revisionId: string): string {
  return `${DRAFTS_PATH}${encodeURIComponent(revisionId)}`;
}

export async function applyExecutionEdit(
  revisionId: string,
  pack: ExecutionPack,
): Promise<ExecutionPack> {
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
  const body = (await response.json()) as { pack?: ExecutionPack };
  return (body.pack ?? {}) as ExecutionPack;
}