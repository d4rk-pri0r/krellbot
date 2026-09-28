import { getCsrf } from "../../session";

export type ValidationError = {
  field?: string;
  message: string;
};

export type DraftState = "draft" | "validated" | "deployed" | "archived";

export type Pack = Record<string, unknown>;

export type DraftSummary = {
  revision_id: string;
  state: DraftState;
  pack: Pack;
  errors: ValidationError[];
};

export type StrategyClient = {
  create(pack: Pack): Promise<DraftSummary>;
  edit(parentRevisionId: string, pack: Pack): Promise<DraftSummary>;
  validate(revisionId: string): Promise<DraftSummary>;
  arm(revisionId: string, venue: string, paperBalance: string): Promise<void>;
};

type RawSummary = {
  schema_version?: string;
  strategy_id?: string;
  revision_id?: string;
  parent_revision_id?: string | null;
  state?: string;
  runnable?: boolean;
  created_at?: string;
  errors?: Array<{ field?: string; message: string }>;
  pack?: Pack;
};

function adapt(raw: RawSummary): DraftSummary {
  const stateRaw = raw.state ?? "draft";
  const state: DraftState =
    stateRaw === "draft" ||
    stateRaw === "validated" ||
    stateRaw === "deployed" ||
    stateRaw === "archived"
      ? stateRaw
      : "draft";
  return {
    revision_id: String(raw.revision_id ?? ""),
    state,
    pack: (raw.pack ?? {}) as Pack,
    errors: Array.isArray(raw.errors) ? raw.errors : [],
  };
}

async function postJson(url: string, body: unknown): Promise<DraftSummary> {
  const response = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Krellbot-CSRF": getCsrf(),
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
  return adapt((await response.json()) as RawSummary);
}

async function putJson(url: string, body: unknown): Promise<DraftSummary> {
  const response = await fetch(url, {
    method: "PUT",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Krellbot-CSRF": getCsrf(),
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
  return adapt((await response.json()) as RawSummary);
}

export function createHttpClient(): StrategyClient {
  return {
    async create(pack: Pack): Promise<DraftSummary> {
      return postJson("/api/v1/strategies/drafts", { pack });
    },
    async edit(
      parentRevisionId: string,
      pack: Pack,
    ): Promise<DraftSummary> {
      return putJson(
        `/api/v1/strategies/drafts/${encodeURIComponent(parentRevisionId)}`,
        { pack },
      );
    },
    async validate(revisionId: string): Promise<DraftSummary> {
      return postJson(
        `/api/v1/strategies/drafts/${encodeURIComponent(revisionId)}/validate`,
        {},
      );
    },
    async arm(
      revisionId: string,
      venue: string,
      paperBalance: string,
    ): Promise<void> {
      const response = await fetch("/api/v1/commands", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Krellbot-CSRF": getCsrf(),
        },
        body: JSON.stringify({
          schema_version: "1",
          command: "paper.arm",
          payload: {
            revision_id: revisionId,
            venue,
            paper_balance: paperBalance,
          },
        }),
      });
      if (!response.ok) {
        throw new Error(`arm failed: ${response.status}`);
      }
      const body = (await response.json()) as { ok?: boolean; code?: string };
      if (body.ok === false) {
        throw new Error(body.code || "arm refused");
      }
    },
  };
}