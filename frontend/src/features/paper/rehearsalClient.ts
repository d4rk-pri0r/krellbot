import { getCsrf } from "../../session";

/**
 * Wire types for the frozen synthetic-rehearsal contract:
 * ``GET /api/v1/rehearsal/status`` and the ``rehearsal.*`` commands.
 * The label is the backend's own synthetic/simulated disclaimer — the
 * panel renders it verbatim and never replaces it with a performance
 * claim.
 */

export type RehearsalFill = {
  coid: string;
  side: string;
  qty: string;
  price: string;
  ts_ms: number;
  kind: string;
};

export type RehearsalStatus = {
  schema_version: string;
  label: string;
  status: string;
  cursor: number;
  total_bars: number;
  balances: Record<string, string>;
  position: string;
  resting_stop: string | null;
  recent_fills: RehearsalFill[];
};

export type RehearsalCommandResult = {
  schema_version?: string;
  code?: string;
  ok?: boolean;
  message?: string;
  effect?: string;
  status?: RehearsalStatus;
};

export type RehearsalClient = {
  getStatus(): Promise<RehearsalStatus>;
  start(): Promise<RehearsalCommandResult>;
  pause(): Promise<RehearsalCommandResult>;
  resume(): Promise<RehearsalCommandResult>;
  exit(): Promise<RehearsalCommandResult>;
  stop(): Promise<RehearsalCommandResult>;
};

function str(raw: unknown, fallback = ""): string {
  return typeof raw === "string" ? raw : fallback;
}

function num(raw: unknown): number {
  return typeof raw === "number" && Number.isFinite(raw) ? raw : 0;
}

export function adaptRehearsalStatus(
  raw: Record<string, unknown>,
): RehearsalStatus {
  const fillsRaw = Array.isArray(raw.recent_fills) ? raw.recent_fills : [];
  const balancesRaw =
    raw.balances && typeof raw.balances === "object" && !Array.isArray(raw.balances)
      ? (raw.balances as Record<string, unknown>)
      : {};
  const balances: Record<string, string> = {};
  for (const [asset, value] of Object.entries(balancesRaw)) {
    balances[asset] = typeof value === "string" ? value : String(value ?? "0");
  }
  // The frozen contract names the field ``position``; accept the same
  // value under ``position_qty`` without inventing one when neither is
  // present.
  const positionRaw = raw.position ?? raw.position_qty;
  return {
    schema_version: str(raw.schema_version, "1"),
    label: str(raw.label),
    status: str(raw.status, "idle"),
    cursor: num(raw.cursor),
    total_bars: num(raw.total_bars),
    balances,
    position: typeof positionRaw === "string" ? positionRaw : "0",
    resting_stop: typeof raw.resting_stop === "string" ? raw.resting_stop : null,
    recent_fills: fillsRaw.map((fill) => {
      const f = (fill ?? {}) as Record<string, unknown>;
      return {
        coid: str(f.coid),
        side: str(f.side),
        qty: str(f.qty, "0"),
        price: str(f.price, "0"),
        ts_ms: num(f.ts_ms),
        kind: str(f.kind, "fill"),
      };
    }),
  };
}

async function getStatus(): Promise<RehearsalStatus> {
  const response = await fetch("/api/v1/rehearsal/status", {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    throw new Error(`rehearsal status failed: ${response.status}`);
  }
  const raw = (await response.json()) as Record<string, unknown>;
  return adaptRehearsalStatus(raw);
}

async function postCommand(
  command:
    | "rehearsal.start"
    | "rehearsal.pause"
    | "rehearsal.resume"
    | "rehearsal.exit"
    | "rehearsal.stop",
): Promise<RehearsalCommandResult> {
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
      payload: {},
    }),
  });
  if (!response.ok) {
    // A non-2xx answer is a refusal, not a silent retry: surface the
    // body's own code/message when it parses, otherwise the status.
    let refusal: Record<string, unknown> = {};
    try {
      refusal = (await response.json()) as Record<string, unknown>;
    } catch {
      refusal = {};
    }
    const code = typeof refusal.code === "string" ? refusal.code : "";
    const message =
      typeof refusal.message === "string" ? refusal.message : "";
    const reason = code || message || String(response.status);
    throw new Error(`${command} refused: ${reason}`);
  }
  const raw = (await response.json()) as Record<string, unknown>;
  const result: RehearsalCommandResult = {
    schema_version: str(raw.schema_version, "1"),
    code: str(raw.code),
    ok: raw.ok === true,
    message: str(raw.message),
    effect: str(raw.effect),
  };
  if (
    raw.status !== null &&
    typeof raw.status === "object" &&
    !Array.isArray(raw.status)
  ) {
    result.status = adaptRehearsalStatus(raw.status as Record<string, unknown>);
  }
  return result;
}

export function createRehearsalHttpClient(): RehearsalClient {
  return {
    getStatus,
    start: () => postCommand("rehearsal.start"),
    pause: () => postCommand("rehearsal.pause"),
    resume: () => postCommand("rehearsal.resume"),
    exit: () => postCommand("rehearsal.exit"),
    stop: () => postCommand("rehearsal.stop"),
  };
}
