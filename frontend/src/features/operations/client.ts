import { getCsrf } from "../../session";

export type LiveStatus = {
  schema_version: string;
  live_enabled: boolean;
  authorized: ReadonlyArray<{ venue: string; pair: string }>;
  kill_switch: { engaged: boolean; reason: string | null; engaged_at: number | null };
  promotion_available: boolean;
  promotion_code: string;
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

function adaptLive(raw: unknown): LiveStatus {
  const obj = (raw ?? {}) as Record<string, unknown>;
  const authorizedRaw = Array.isArray(obj.authorized) ? obj.authorized : [];
  const authorized = authorizedRaw
    .map((entry) => {
      if (!entry || typeof entry !== "object") {
        return null;
      }
      const e = entry as { venue?: unknown; pair?: unknown };
      if (typeof e.venue !== "string" || typeof e.pair !== "string") {
        return null;
      }
      return { venue: e.venue, pair: e.pair };
    })
    .filter((entry): entry is { venue: string; pair: string } => entry !== null);
  return {
    schema_version: typeof obj.schema_version === "string" ? obj.schema_version : "1",
    live_enabled: obj.live_enabled === true,
    authorized,
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

export function createHttpClient(): OperationsClient {
  return {
    getOperations(): Promise<OperationsViewModel> {
      return getJson("/api/v1/operations");
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