import { getCsrf } from "../../session";

export type ValidationError = {
  field?: string;
  message: string;
};

export type DraftState = "draft" | "validated" | "deployed" | "archived";

export type Pack = Record<string, unknown>;

export type DraftOutcome = "created" | "unchanged" | "existing";

export type DraftSummary = {
  revision_id: string;
  state: DraftState;
  pack: Pack;
  errors: ValidationError[];
  outcome?: DraftOutcome;
  parent_revision_id?: string | null;
};

export type StrategyClient = {
  create(pack: Pack): Promise<DraftSummary>;
  edit(parentRevisionId: string, pack: Pack): Promise<DraftSummary>;
  validate(revisionId: string): Promise<DraftSummary>;
  arm(revisionId: string, venue: string, paperBalance: string): Promise<void>;
  saveEditor?(
    revisionId: string,
    editor: Record<string, unknown>,
  ): Promise<void>;
  loadEditor?(revisionId: string): Promise<Record<string, unknown>>;
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
  outcome?: unknown;
};

function adaptOutcome(raw: unknown): DraftOutcome | undefined {
  if (raw === "created" || raw === "unchanged" || raw === "existing") {
    return raw;
  }
  return undefined;
}

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
    outcome: adaptOutcome(raw.outcome),
    parent_revision_id:
      raw.parent_revision_id === null || typeof raw.parent_revision_id === "string"
        ? (raw.parent_revision_id as string | null)
        : undefined,
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
    throw await adaptHttpError(response);
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
    throw await adaptHttpError(response);
  }
  return adapt((await response.json()) as RawSummary);
}

async function adaptHttpError(response: Response): Promise<Error> {
  let code: string | undefined;
  let message: string | undefined;
  try {
    const body = (await response.json()) as {
      code?: string;
      message?: string;
      detail?: string;
    };
    code = typeof body.code === "string" ? body.code : undefined;
    message =
      typeof body.message === "string"
        ? body.message
        : typeof body.detail === "string"
          ? body.detail
          : undefined;
  } catch {
    return new Error(`request failed: ${response.status}`);
  }
  const status = response.status;
  const head = message ? `${status} ${code ?? ""} ${message}`.trim() : `request failed: ${status}`;
  if (code === "strategy_id_mismatch") {
    return new Error(`strategy_id_mismatch: ${head}`);
  }
  return new Error(head);
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
    async saveEditor(
      revisionId: string,
      editor: Record<string, unknown>,
    ): Promise<void> {
      const response = await fetch(
        `/api/v1/strategies/drafts/${encodeURIComponent(revisionId)}/editor`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-Krellbot-CSRF": getCsrf(),
          },
          body: JSON.stringify({ editor }),
        },
      );
      if (!response.ok) {
        throw new Error(`editor save failed: ${response.status}`);
      }
    },
    async loadEditor(revisionId: string): Promise<Record<string, unknown>> {
      const response = await fetch(
        `/api/v1/strategies/drafts/${encodeURIComponent(revisionId)}`,
        {
          method: "GET",
          credentials: "include",
          headers: { "X-Krellbot-CSRF": getCsrf() },
        },
      );
      if (!response.ok) {
        throw new Error(`editor load failed: ${response.status}`);
      }
      const body = (await response.json()) as { editor?: unknown };
      if (!body.editor || typeof body.editor !== "object" || Array.isArray(body.editor)) {
        return {};
      }
      return body.editor as Record<string, unknown>;
    },
  };
}