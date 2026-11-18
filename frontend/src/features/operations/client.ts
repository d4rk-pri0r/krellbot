import { getCsrf } from "../../session";

export type LiveAuthorizationGrant = { venue: string; pair: string };

export type LiveAuthorizationState = {
  active: boolean;
  expires_at: number | null;
  grants: ReadonlyArray<LiveAuthorizationGrant>;
};

export type LiveStatus = {
  schema_version: string;
  live_enabled: boolean;
  authorized: ReadonlyArray<LiveAuthorizationGrant>;
  authorization?: LiveAuthorizationState;
  release_policy?: string;
  release_policy_code?: string;
  release_policy_message?: string | null;
  kill_switch: { engaged: boolean; reason: string | null; engaged_at: number | null };
  promotion_available: boolean;
  promotion_code: string;
};

export type LiveAuthorizationView = {
  schema_version: string;
  authorization: LiveAuthorizationState;
  release_policy: string;
  release_policy_code: string;
  release_policy_message: string | null;
  confirmation_required: string;
};

export type LiveAuthorizationCommandResult = {
  schema_version?: string;
  code?: string;
  ok?: boolean;
  message?: string;
  effect?: string;
  authorization?: LiveAuthorizationState;
};

export type DeploymentRow = {
  venue: string;
  pair: string;
  pack_id: string;
  pack_version: string;
  mode: string;
  entries_paused: boolean;
  promotion: { available: boolean; code: string };
};

export type AlertRow = {
  id: string;
  kind: string;
  severity: string;
  code: string | null;
  venue: string | null;
  pair: string | null;
  count: number;
  first_ts: number;
  last_ts: number;
  acknowledged: boolean;
};

export type OperationsViewModel = {
  schema_version: string;
  live: LiveStatus;
  deployments: ReadonlyArray<DeploymentRow>;
  alerts: ReadonlyArray<AlertRow>;
};

export type DeploymentRecordRow = {
  deployment_id: string;
  venue: string;
  pair: string;
  created_at_ms: number;
  state: string;
  config: Readonly<Record<string, string | number | boolean>>;
  schedule: Readonly<Record<string, string | number | boolean>>;
  last_execution_summary: string;
};

export type UnresolvedOrderRow = {
  client_order_id: string;
  age_seconds: number | null;
  last_lookup_result: string;
};

/** One raw journal record from GET /api/v1/journal (CLI journal parity). */
export type JournalRecordRow = {
  ts: number;
  kind: string;
  venue: string;
  pack: string;
  bar_ts: number;
  detail: unknown;
  /** Projected paper/live classification from the browse API (M20.5). */
  mode?: "paper" | "live";
  /** Human-readable tick/refuse/fill summary when the server projects one. */
  summary?: string;
};

export type JournalBrowseQuery = {
  /** Positive integer; omitted when using ``since``. Default server-side is 5. */
  tail?: number;
  /** CLI windows only: ``24h`` or ``14d``. Wins over ``tail`` when both set. */
  since?: "24h" | "14d";
  /** Optional paper/live filter (filter-then-tail on the server). */
  mode?: "paper" | "live";
};

/** Closed-shape scheduler status from GET/POST /api/v1/scheduler* (M2.7). */
export type SchedulerStatus = {
  schema_version: string;
  installed: boolean;
  enabled: boolean;
  last_error: string | null;
};

export type CommandResult = {
  schema_version?: string;
  code?: string;
  ok?: boolean;
  message?: string;
  effect?: string;
  venue?: string;
  pair?: string;
  alert?: AlertRow;
  kill_switch?: { engaged: boolean; reason: string | null; engaged_at: number | null };
};

export type OperationsClient = {
  getOperations(): Promise<OperationsViewModel>;
  promote(venue: string, pair: string, revisionId: string): Promise<CommandResult>;
  pauseEntries(venue: string, pair: string): Promise<CommandResult>;
  resumeEntries(venue: string, pair: string): Promise<CommandResult>;
  engageKill(reason: string): Promise<CommandResult>;
  releaseKill(): Promise<CommandResult>;
  ackAlert(alertId: string): Promise<CommandResult>;
  listDeploymentRecords?(): Promise<DeploymentRecordRow[]>;
  getDeploymentRecord?(deploymentId: string): Promise<DeploymentRecordRow>;
  listUnresolvedOrders?(): Promise<UnresolvedOrderRow[]>;
  listJournal?(query?: JournalBrowseQuery): Promise<JournalRecordRow[]>;
  getLiveAuthorization?(): Promise<LiveAuthorizationView>;
  grantLiveAuthorization?(
    venue: string,
    pair: string,
    expiresAt: number,
    confirmation: string,
  ): Promise<LiveAuthorizationCommandResult>;
  revokeLiveAuthorization?(): Promise<LiveAuthorizationCommandResult>;
  armLive?(
    revisionId: string,
    venue: string,
    confirmation: string,
  ): Promise<CommandResult>;
  getScheduler?(): Promise<SchedulerStatus>;
  installScheduler?(): Promise<SchedulerStatus>;
  enableScheduler?(): Promise<SchedulerStatus>;
};

async function getJson(url: string): Promise<OperationsViewModel> {
  const response = await fetch(url, {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    throw new Error(`operations view failed: ${response.status}`);
  }
  return adaptOperations((await response.json()) as Record<string, unknown>);
}

async function postCommand(
  command: string,
  payload: Record<string, unknown>,
): Promise<CommandResult> {
  const response = await fetch("/api/v1/commands", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Krellbot-CSRF": getCsrf(),
    },
    body: JSON.stringify({
      schema_version: "1",
      command,
      payload,
    }),
  });
  if (!response.ok) {
    throw new Error(`${command} failed: ${response.status}`);
  }
  return (await response.json()) as CommandResult;
}

function adaptKill(raw: unknown): LiveStatus["kill_switch"] {
  if (!raw || typeof raw !== "object") {
    return { engaged: false, reason: null, engaged_at: null };
  }
  const obj = raw as { engaged?: unknown; reason?: unknown; engaged_at?: unknown };
  return {
    engaged: obj.engaged === true,
    reason: typeof obj.reason === "string" ? obj.reason : null,
    engaged_at: typeof obj.engaged_at === "number" ? obj.engaged_at : null,
  };
}

function adaptGrant(raw: unknown): LiveAuthorizationGrant | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const e = raw as { venue?: unknown; pair?: unknown };
  if (typeof e.venue !== "string" || typeof e.pair !== "string") {
    return null;
  }
  return { venue: e.venue, pair: e.pair };
}

function adaptAuthorization(raw: unknown): LiveAuthorizationState {
  if (!raw || typeof raw !== "object") {
    return { active: false, expires_at: null, grants: [] };
  }
  const obj = raw as { active?: unknown; expires_at?: unknown; grants?: unknown };
  const grantsRaw = Array.isArray(obj.grants) ? obj.grants : [];
  const grants = grantsRaw
    .map(adaptGrant)
    .filter((entry): entry is LiveAuthorizationGrant => entry !== null);
  return {
    active: obj.active === true,
    expires_at: typeof obj.expires_at === "number" ? obj.expires_at : null,
    grants,
  };
}

function adaptLiveAuthorizationView(raw: unknown): LiveAuthorizationView {
  const obj = (raw ?? {}) as Record<string, unknown>;
  return {
    schema_version: typeof obj.schema_version === "string" ? obj.schema_version : "1",
    authorization: adaptAuthorization(obj.authorization),
    release_policy: typeof obj.release_policy === "string" ? obj.release_policy : "paper_only",
    release_policy_code:
      typeof obj.release_policy_code === "string"
        ? obj.release_policy_code
        : "live_disabled_paper_only_release",
    release_policy_message:
      typeof obj.release_policy_message === "string" ? obj.release_policy_message : null,
    confirmation_required:
      typeof obj.confirmation_required === "string" ? obj.confirmation_required : "LIVE",
  };
}

function adaptLive(raw: unknown): LiveStatus {
  const obj = (raw ?? {}) as Record<string, unknown>;
  const authorizedRaw = Array.isArray(obj.authorized) ? obj.authorized : [];
  const authorized = authorizedRaw
    .map(adaptGrant)
    .filter((entry): entry is LiveAuthorizationGrant => entry !== null);
  return {
    schema_version: typeof obj.schema_version === "string" ? obj.schema_version : "1",
    live_enabled: obj.live_enabled === true,
    authorized,
    authorization: adaptAuthorization(obj.authorization),
    release_policy: typeof obj.release_policy === "string" ? obj.release_policy : undefined,
    release_policy_code:
      typeof obj.release_policy_code === "string" ? obj.release_policy_code : undefined,
    release_policy_message:
      typeof obj.release_policy_message === "string"
        ? obj.release_policy_message
        : obj.release_policy_message === null
          ? null
          : undefined,
    kill_switch: adaptKill(obj.kill_switch),
    promotion_available: obj.promotion_available === true,
    promotion_code:
      typeof obj.promotion_code === "string" ? obj.promotion_code : "live_promotion_owner_deferred",
  };
}

function adaptDeployment(raw: unknown): DeploymentRow | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const obj = raw as Record<string, unknown>;
  if (
    typeof obj.venue !== "string" ||
    typeof obj.pair !== "string" ||
    typeof obj.pack_id !== "string" ||
    typeof obj.pack_version !== "string" ||
    typeof obj.mode !== "string"
  ) {
    return null;
  }
  const promo = obj.promotion;
  const promoCode =
    promo && typeof promo === "object" && typeof (promo as { code?: unknown }).code === "string"
      ? (promo as { code: string }).code
      : "live_promotion_owner_deferred";
  return {
    venue: obj.venue,
    pair: obj.pair,
    pack_id: obj.pack_id,
    pack_version: obj.pack_version,
    mode: obj.mode,
    entries_paused: obj.entries_paused === true,
    promotion: { available: false, code: promoCode },
  };
}

function adaptAlert(raw: unknown): AlertRow | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const obj = raw as Record<string, unknown>;
  if (
    typeof obj.id !== "string" ||
    typeof obj.kind !== "string" ||
    typeof obj.severity !== "string" ||
    typeof obj.count !== "number" ||
    typeof obj.first_ts !== "number" ||
    typeof obj.last_ts !== "number" ||
    typeof obj.acknowledged !== "boolean"
  ) {
    return null;
  }
  return {
    id: obj.id,
    kind: obj.kind,
    severity: obj.severity,
    code: typeof obj.code === "string" ? obj.code : null,
    venue: typeof obj.venue === "string" ? obj.venue : null,
    pair: typeof obj.pair === "string" ? obj.pair : null,
    count: obj.count,
    first_ts: obj.first_ts,
    last_ts: obj.last_ts,
    acknowledged: obj.acknowledged,
  };
}

function adaptOperations(raw: Record<string, unknown>): OperationsViewModel {
  const live = adaptLive(raw.live);
  const deploymentsRaw = Array.isArray(raw.deployments) ? raw.deployments : [];
  const deployments = deploymentsRaw
    .map(adaptDeployment)
    .filter((d): d is DeploymentRow => d !== null);
  const alertsRaw = Array.isArray(raw.alerts) ? raw.alerts : [];
  const alerts = alertsRaw.map(adaptAlert).filter((a): a is AlertRow => a !== null);
  return {
    schema_version: typeof raw.schema_version === "string" ? raw.schema_version : "1",
    live,
    deployments,
    alerts,
  };
}

function adaptDeploymentRecord(raw: unknown): DeploymentRecordRow | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const obj = raw as Record<string, unknown>;
  if (
    typeof obj.deployment_id !== "string" ||
    typeof obj.venue !== "string" ||
    typeof obj.pair !== "string" ||
    typeof obj.created_at_ms !== "number" ||
    typeof obj.state !== "string"
  ) {
    return null;
  }
  return {
    deployment_id: obj.deployment_id,
    venue: obj.venue,
    pair: obj.pair,
    created_at_ms: obj.created_at_ms,
    state: obj.state,
    config: adaptSubset(obj.config),
    schedule: adaptSubset(obj.schedule),
    last_execution_summary:
      typeof obj.last_execution_summary === "string" ? obj.last_execution_summary : "",
  };
}

function adaptJournalRecord(raw: unknown): JournalRecordRow | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const obj = raw as Record<string, unknown>;
  if (typeof obj.ts !== "number" || !Number.isFinite(obj.ts)) {
    return null;
  }
  if (typeof obj.kind !== "string" || typeof obj.venue !== "string") {
    return null;
  }
  if (typeof obj.pack !== "string") {
    return null;
  }
  const barTs = typeof obj.bar_ts === "number" && Number.isFinite(obj.bar_ts) ? obj.bar_ts : 0;
  const mode = obj.mode === "paper" || obj.mode === "live" ? obj.mode : undefined;
  const summary = typeof obj.summary === "string" ? obj.summary : undefined;
  return {
    ts: obj.ts,
    kind: obj.kind,
    venue: obj.venue,
    pack: obj.pack,
    bar_ts: barTs,
    detail: obj.detail,
    ...(mode !== undefined ? { mode } : {}),
    ...(summary !== undefined ? { summary } : {}),
  };
}

function journalBrowseUrl(query?: JournalBrowseQuery): string {
  const params = new URLSearchParams();
  if (query?.since === "24h" || query?.since === "14d") {
    params.set("since", query.since);
  } else if (typeof query?.tail === "number" && Number.isFinite(query.tail)) {
    params.set("tail", String(Math.trunc(query.tail)));
  }
  if (query?.mode === "paper" || query?.mode === "live") {
    params.set("mode", query.mode);
  }
  const encoded = params.toString();
  return encoded ? `/api/v1/journal?${encoded}` : "/api/v1/journal";
}

function adaptUnresolvedOrder(raw: unknown): UnresolvedOrderRow | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const obj = raw as Record<string, unknown>;
  if (typeof obj.client_order_id !== "string" || !obj.client_order_id) {
    return null;
  }
  if (typeof obj.last_lookup_result !== "string") {
    return null;
  }
  const age =
    obj.age_seconds === null
      ? null
      : typeof obj.age_seconds === "number" && Number.isFinite(obj.age_seconds)
        ? obj.age_seconds
        : null;
  return {
    client_order_id: obj.client_order_id,
    age_seconds: age,
    last_lookup_result: obj.last_lookup_result,
  };
}

function adaptSubset(raw: unknown): Readonly<Record<string, string | number | boolean>> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {};
  }
  const out: Record<string, string | number | boolean> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      out[key] = value;
    }
  }
  return out;
}

export function adaptSchedulerStatus(raw: unknown): SchedulerStatus {
  const obj = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  return {
    schema_version: typeof obj.schema_version === "string" ? obj.schema_version : "1",
    installed: obj.installed === true,
    enabled: obj.enabled === true,
    last_error: typeof obj.last_error === "string" ? obj.last_error : null,
  };
}

async function postScheduler(url: string, label: string): Promise<SchedulerStatus> {
  const response = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Krellbot-CSRF": getCsrf(),
    },
    body: "{}",
  });
  if (!response.ok) {
    throw new Error(`${label} failed: ${response.status}`);
  }
  return adaptSchedulerStatus(await response.json());
}

async function getOperationsReadJson(url: string, label: string): Promise<unknown> {
  const response = await fetch(url, {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    let refusal = "";
    try {
      const errorBody = (await response.json()) as { code?: unknown };
      if (typeof errorBody.code === "string") {
        refusal = ` ${errorBody.code}`;
      }
    } catch {
      // The error body is optional; the status alone identifies the refusal.
    }
    throw new Error(`${label} failed: ${response.status}${refusal}`);
  }
  return response.json();
}

export function createHttpClient(): OperationsClient {
  return {
    getOperations(): Promise<OperationsViewModel> {
      return getJson("/api/v1/operations");
    },
    listDeploymentRecords(): Promise<DeploymentRecordRow[]> {
      return getOperationsReadJson("/api/v1/operations/deployments", "deployment history").then(
        (raw) => {
          const body = (raw ?? {}) as Record<string, unknown>;
          const rows = Array.isArray(body.deployments) ? body.deployments : [];
          return rows
            .map(adaptDeploymentRecord)
            .filter((row): row is DeploymentRecordRow => row !== null);
        },
      );
    },
    getDeploymentRecord(deploymentId: string): Promise<DeploymentRecordRow> {
      return getOperationsReadJson(
        `/api/v1/operations/deployments/${encodeURIComponent(deploymentId)}`,
        "deployment history",
      ).then((raw) => {
        const row = adaptDeploymentRecord(raw);
        if (row === null) {
          throw new Error("deployment history returned an unusable record");
        }
        return row;
      });
    },
    listUnresolvedOrders(): Promise<UnresolvedOrderRow[]> {
      return getOperationsReadJson(
        "/api/v1/operations/unresolved-orders",
        "unresolved orders",
      ).then((raw) => {
        const body = (raw ?? {}) as Record<string, unknown>;
        const rows = Array.isArray(body.orders) ? body.orders : [];
        return rows
          .map(adaptUnresolvedOrder)
          .filter((row): row is UnresolvedOrderRow => row !== null);
      });
    },
    listJournal(query?: JournalBrowseQuery): Promise<JournalRecordRow[]> {
      return getOperationsReadJson(journalBrowseUrl(query), "journal").then((raw) => {
        const body = (raw ?? {}) as Record<string, unknown>;
        const rows = Array.isArray(body.records) ? body.records : [];
        return rows
          .map(adaptJournalRecord)
          .filter((row): row is JournalRecordRow => row !== null);
      });
    },
    getLiveAuthorization(): Promise<LiveAuthorizationView> {
      return getOperationsReadJson(
        "/api/v1/operations/live-authorization",
        "live authorization",
      ).then((raw) => adaptLiveAuthorizationView(raw));
    },
    async grantLiveAuthorization(
      venue: string,
      pair: string,
      expiresAt: number,
      confirmation: string,
    ): Promise<LiveAuthorizationCommandResult> {
      const response = await fetch("/api/v1/operations/live-authorization", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Krellbot-CSRF": getCsrf(),
        },
        body: JSON.stringify({
          venue,
          pair,
          expires_at: expiresAt,
          confirmation,
        }),
      });
      if (!response.ok) {
        throw new Error(`live authorization grant failed: ${response.status}`);
      }
      const raw = (await response.json()) as Record<string, unknown>;
      return {
        schema_version: typeof raw.schema_version === "string" ? raw.schema_version : "1",
        code: typeof raw.code === "string" ? raw.code : undefined,
        ok: raw.ok === true,
        message: typeof raw.message === "string" ? raw.message : undefined,
        effect: typeof raw.effect === "string" ? raw.effect : undefined,
        authorization: adaptAuthorization(raw.authorization),
      };
    },
    async revokeLiveAuthorization(): Promise<LiveAuthorizationCommandResult> {
      const response = await fetch("/api/v1/operations/live-authorization", {
        method: "DELETE",
        credentials: "include",
        headers: {
          "X-Krellbot-CSRF": getCsrf(),
        },
      });
      if (!response.ok) {
        throw new Error(`live authorization revoke failed: ${response.status}`);
      }
      const raw = (await response.json()) as Record<string, unknown>;
      return {
        schema_version: typeof raw.schema_version === "string" ? raw.schema_version : "1",
        code: typeof raw.code === "string" ? raw.code : undefined,
        ok: raw.ok === true,
        message: typeof raw.message === "string" ? raw.message : undefined,
        effect: typeof raw.effect === "string" ? raw.effect : undefined,
        authorization: adaptAuthorization(raw.authorization),
      };
    },
    async armLive(
      revisionId: string,
      venue: string,
      confirmation: string,
    ): Promise<CommandResult> {
      const response = await fetch("/api/v1/commands", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Krellbot-CSRF": getCsrf(),
        },
        body: JSON.stringify({
          schema_version: "1",
          command: "live.arm",
          payload: {
            venue,
            revision_id: revisionId,
            mode: "live",
            confirmation,
          },
        }),
      });
      let raw: Record<string, unknown> = {};
      try {
        raw = (await response.json()) as Record<string, unknown>;
      } catch {
        raw = {};
      }
      return {
        schema_version: typeof raw.schema_version === "string" ? raw.schema_version : "1",
        code: typeof raw.code === "string" ? raw.code : undefined,
        ok: raw.ok === true,
        message: typeof raw.message === "string" ? raw.message : undefined,
        effect: typeof raw.effect === "string" ? raw.effect : undefined,
        venue: typeof raw.venue === "string" ? raw.venue : undefined,
        pair: typeof raw.pair === "string" ? raw.pair : undefined,
      };
    },
    getScheduler(): Promise<SchedulerStatus> {
      return getOperationsReadJson("/api/v1/scheduler", "scheduler status").then((raw) =>
        adaptSchedulerStatus(raw),
      );
    },
    installScheduler(): Promise<SchedulerStatus> {
      return postScheduler("/api/v1/scheduler/install", "scheduler install");
    },
    enableScheduler(): Promise<SchedulerStatus> {
      return postScheduler("/api/v1/scheduler/enable", "scheduler enable");
    },
    promote(venue, pair, revisionId): Promise<CommandResult> {
      return postCommand("live.promote", { venue, pair, revision_id: revisionId });
    },
    pauseEntries(venue, pair): Promise<CommandResult> {
      return postCommand("paper.pause_entries", { venue, pair });
    },
    resumeEntries(venue, pair): Promise<CommandResult> {
      return postCommand("paper.resume_entries", { venue, pair });
    },
    engageKill(reason): Promise<CommandResult> {
      return postCommand("operations.kill", { reason });
    },
    releaseKill(): Promise<CommandResult> {
      return postCommand("operations.release_kill", {});
    },
    ackAlert(alertId): Promise<CommandResult> {
      return postCommand("alerts.ack", { alert_id: alertId });
    },
  };
}