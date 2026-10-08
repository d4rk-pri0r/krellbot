import { getCsrf } from "../../session";
import type { DraftState } from "./client";

export type OwnedDraftSummary = {
  revision_id: string;
  strategy_id: string;
  parent_revision_id: string | null;
  state: DraftState;
  runnable: boolean;
  created_at: string;
  /** The canonical pack's identity fields. Empty when absent. */
  id: string;
  label: string;
  pair: string;
  timeframe: string;
};

/** The bytes + read-only identity the Editor already takes as ``initial``. */
export type OwnedRevisionBytes = {
  revision_id: string;
  state: DraftState;
  bytes: string;
};

export type LibraryClient = {
  listOwned(): Promise<OwnedDraftSummary[]>;
  getJson(revisionId: string): Promise<OwnedRevisionBytes>;
};

type RawOwnedSummary = {
  revision_id?: unknown;
  strategy_id?: unknown;
  parent_revision_id?: unknown;
  state?: unknown;
  runnable?: unknown;
  created_at?: unknown;
  id?: unknown;
  label?: unknown;
  pair?: unknown;
  timeframe?: unknown;
};

function asDraftState(raw: unknown): DraftState {
  return raw === "validated" ||
    raw === "deployed" ||
    raw === "archived" ||
    raw === "draft"
    ? raw
    : "draft";
}

function asString(raw: unknown): string {
  return typeof raw === "string" ? raw : "";
}

function adaptSummary(raw: RawOwnedSummary): OwnedDraftSummary {
  return {
    revision_id: asString(raw.revision_id),
    strategy_id: asString(raw.strategy_id),
    parent_revision_id:
      typeof raw.parent_revision_id === "string" ? raw.parent_revision_id : null,
    state: asDraftState(raw.state),
    runnable: raw.runnable === true,
    created_at: asString(raw.created_at),
    id: asString(raw.id),
    label: asString(raw.label),
    pair: asString(raw.pair),
    timeframe: asString(raw.timeframe),
  };
}

async function getJson<T>(url: string, failure: string): Promise<T> {
  const response = await fetch(url, {
    method: "GET",
    credentials: "include",
    headers: { "X-Krellbot-CSRF": getCsrf() },
  });
  if (!response.ok) {
    throw new Error(`${failure}: ${response.status}`);
  }
  return (await response.json()) as T;
}

export function createLibraryClient(): LibraryClient {
  return {
    async listOwned(): Promise<OwnedDraftSummary[]> {
      const body = await getJson<{ drafts?: unknown }>(
        "/api/v1/strategies/drafts",
        "library list failed",
      );
      if (!Array.isArray(body.drafts)) {
        return [];
      }
      return body.drafts.map((row) =>
        adaptSummary((row ?? {}) as RawOwnedSummary),
      );
    },
    async getJson(revisionId: string): Promise<OwnedRevisionBytes> {
      const body = await getJson<{
        revision_id?: unknown;
        state?: unknown;
        pack?: unknown;
      }>(
        `/api/v1/strategies/drafts/${encodeURIComponent(revisionId)}`,
        "library open failed",
      );
      const pack =
        body.pack && typeof body.pack === "object" && !Array.isArray(body.pack)
          ? (body.pack as Record<string, unknown>)
          : {};
      return {
        revision_id: asString(body.revision_id) || revisionId,
        state: asDraftState(body.state),
        bytes: JSON.stringify(pack),
      };
    },
  };
}
