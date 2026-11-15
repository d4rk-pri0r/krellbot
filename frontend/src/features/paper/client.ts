import { getCsrf, recoverPaperStatusSession } from "../../session";
import type { RehearsalClient } from "./rehearsalClient";
import { createRehearsalHttpClient } from "./rehearsalClient";

export type PaperStatus = {
  schema_version: string;
  armed: boolean;
  venue?: string;
  pair?: string;
  entries_paused?: boolean;
  mode?: string;
  pack_id?: string;
  /** How many packs are armed; status projects one of them. */
  armed_count?: number;
};

export type PaperCommandResult = {
  schema_version?: string;
  code?: string;
  ok?: boolean;
  message?: string;
  effect?: string;
  revision_before?: string | null;
  revision_after?: string | null;
};

export type PaperExportResult = {
  filename: string | null;
  bytes: string;
};

export class PaperCommandRefusalError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "PaperCommandRefusalError";
    this.code = code;
  }
}

/**
 * The payload the ``paper.arm`` handler reads: ``revision_id`` addressing a
 * saved draft, the venue, ``mode: "paper"`` and ``paper_balance`` as a
 * decimal string (the backend parses it with ``Decimal``).
 */
export type PaperArmInput = {
  revision_id: string;
  venue: string;
  mode: "paper";
  paper_balance: string;
};

export type PaperArmDraftSummary = {
  revision_id: string;
  strategy_id: string;
  state: string;
  runnable: boolean;
  label: string;
  pair: string;
};

export type PaperStatusSelect = {
  venue: string;
  pair: string;
};

export type PaperClient = {
  getStatus(select?: PaperStatusSelect): Promise<PaperStatus>;
  getPosition?(select?: PaperStatusSelect): Promise<PaperPosition>;
  pauseEntries(venue: string, pair: string): Promise<PaperCommandResult>;
  resumeEntries(venue: string, pair: string): Promise<PaperCommandResult>;
  disarm(venue: string, pair: string): Promise<PaperCommandResult>;
  raiseStop?(
    venue: string,
    pair: string,
    newStop: string,
  ): Promise<PaperCommandResult>;
  exportPaperPack?(venue: string, pair: string): Promise<PaperExportResult>;
  listOwnedDrafts?(): Promise<PaperArmDraftSummary[]>;
  arm?(input: PaperArmInput): Promise<PaperCommandResult>;
  createRehearsalClient?(): RehearsalClient;
};

export type PaperRunFill = {
  coid: string;
  side: string;
  ts_ms: number;
};

export type PaperRun = {
  venue: string;
  pair: string;
  pack_id: string;
  pack_version?: string;
  first_ts_ms: number;
  last_ts_ms: number;
  ticks_total: number;
  last_refusal_code: string | null;
  mode: string;
  status: string;
  summary: string;
  recent_fills: PaperRunFill[];
};

export type PaperHistory = {
  schema_version: string;
  runs: PaperRun[];
};

export type PaperRunsClient = {
  listRuns(): Promise<PaperHistory>;
};

export type PaperArmedRecord = {
  venue: string;
  pair: string;
  mode: string;
  pack_id: string;
  entries_paused: boolean;
};

export type PaperArmedView = {
  schema_version: string;
  armed: boolean;
  records: PaperArmedRecord[];
};

export type PaperArmedClient = {
  listArmed(): Promise<PaperArmedView>;
};

/** One armed fleet row from ``GET /api/v1/paper/fleet``. */
export type FleetArmedDeployment = {
  venue: string;
  pair: string;
  mode: string;
  pack_id: string;
  entries_paused: boolean;
  last_tick_ts_ms: number | null;
  last_tick_result: string;
  last_refusal_code: string | null;
  detail_href: string;
};

export type FleetArmedView = {
  schema_version: string;
  armed: boolean;
  deployments: FleetArmedDeployment[];
};

export type FleetArmedClient = {
  listFleet(): Promise<FleetArmedView>;
};

/** One owned holding from the persisted paper state file. */
export type PaperPositionHolding = {
  symbol: string;
  qty: string;
};

/**
 * The closed-shape owned-position projection served by
 * ``GET /api/v1/paper/position``. ``free_cash`` and ``qty`` are
 * Decimal-as-string values read verbatim from
 * ``<home>/run/paper-<venue>.json``; the projection fields exist only
 * when the backend reports ``armed: true``.
 */
export type PaperPosition = {
  schema_version: string;
  armed: boolean;
  venue?: string;
  pair?: string;
  mode?: string;
  free_cash?: string;
  holdings?: PaperPositionHolding[];
  as_of_run?: string | null;
  /** How many packs are armed; position projects one of them. */
  armed_count?: number;
};

function paperStatusUrl(select?: PaperStatusSelect): string {
  if (select === undefined) {
    return "/api/v1/paper/status";
  }
  const params = new URLSearchParams({
    venue: select.venue,
    pair: select.pair,
  });
  return `/api/v1/paper/status?${params.toString()}`;
}

function paperPositionUrl(select?: PaperStatusSelect): string {
  if (select === undefined) {
    return "/api/v1/paper/position";
  }
  const params = new URLSearchParams({
    venue: select.venue,
    pair: select.pair,
  });
  return `/api/v1/paper/position?${params.toString()}`;
}

function isPaperStatusUrl(url: string): boolean {
  return url === "/api/v1/paper/status" || url.startsWith("/api/v1/paper/status?");
}

async function getJson(url: string): Promise<PaperStatus> {
  const read = () => fetch(url, {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  let response = await read();
  // Only this safe status read can recover and retry, once. Commands and
  // other client families deliberately retain their existing no-retry paths.
  if (
    isPaperStatusUrl(url) &&
    response.status === 403 &&
    await recoverPaperStatusSession()
  ) {
    response = await read();
  }
  if (!response.ok) {
    throw new Error(`paper status failed: ${response.status}`);
  }
  const raw = (await response.json()) as Record<string, unknown>;
  return adaptStatus(raw);
}

async function postCommand(
  command: string,
  payload: { venue: string; pair: string },
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
      command,
      payload,
    }),
  });
  if (!response.ok) {
    throw new Error(`${command} failed: ${response.status}`);
  }
  return (await response.json()) as PaperCommandResult;
}

/**
 * POST a ``paper.raise_stop``: ``new_stop`` travels as a plain decimal
 * string (e.g. ``1``, ``1.5``, ``0.25``) because the backend parses the
 * payload with ``Decimal``. Below-or-equal stops are refused server-side
 * with ``CODE_INVALID_STOP``; the refusal body is still a
 * ``PaperCommandResult`` and is returned as-is so callers surface the
 * backend's own words. No retry.
 */
async function raiseStop(
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

/**
 * POST a ``paper.arm`` addressed by revision. The handler can refuse with
 * an HTTP 404 (``draft_not_found``) or 403 (``draft_not_runnable``) whose
 * body is still a ``PaperCommandResult``: keep the refusal code/message on
 * a typed error so the panel surfaces the backend's own words instead of
 * a bare status line. No retry.
 */
async function armPaperPack(input: PaperArmInput): Promise<PaperCommandResult> {
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
        revision_id: input.revision_id,
        venue: input.venue,
        mode: "paper",
        paper_balance: input.paper_balance,
      },
    }),
  });
  if (!response.ok) {
    let refusal: Record<string, unknown> = {};
    try {
      refusal = (await response.json()) as Record<string, unknown>;
    } catch {
      refusal = {};
    }
    const code = typeof refusal.code === "string" ? refusal.code : "http_error";
    const message =
      typeof refusal.message === "string"
        ? refusal.message
        : `paper.arm failed: ${response.status}`;
    throw new PaperCommandRefusalError(code, message);
  }
  return (await response.json()) as PaperCommandResult;
}

function adaptDraftSummary(raw: Record<string, unknown>): PaperArmDraftSummary {
  return {
    revision_id: str(raw.revision_id),
    strategy_id: str(raw.strategy_id),
    state: str(raw.state, "draft"),
    runnable: raw.runnable === true,
    label: str(raw.label),
    pair: str(raw.pair),
  };
}

async function listOwnedDrafts(): Promise<PaperArmDraftSummary[]> {
  const response = await fetch("/api/v1/strategies/drafts", {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    throw new Error(`drafts list failed: ${response.status}`);
  }
  const raw = (await response.json()) as Record<string, unknown>;
  const rows = Array.isArray(raw.drafts) ? raw.drafts : [];
  return rows.map((row) =>
    adaptDraftSummary((row ?? {}) as Record<string, unknown>),
  );
}

const EXPORT_NETWORK_FAILURE = "network_failure";

function decodePackBytes(b64: string): string {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new TextDecoder().decode(bytes);
}

async function exportPaperPack(
  venue: string,
  pair: string,
): Promise<PaperExportResult> {
  let response: Response;
  try {
    response = await fetch("/api/v1/commands", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-Krellbot-CSRF": getCsrf(),
      },
      body: JSON.stringify({
        schema_version: "1",
        command: "paper.export",
        payload: { venue, pair },
      }),
    });
  } catch {
    // No retry: a single transport failure is surfaced as-is.
    throw new PaperCommandRefusalError(
      EXPORT_NETWORK_FAILURE,
      "paper.export request failed",
    );
  }
  if (!response.ok) {
    throw new PaperCommandRefusalError(
      EXPORT_NETWORK_FAILURE,
      `paper.export failed: ${response.status}`,
    );
  }
  const raw = (await response.json()) as Record<string, unknown>;
  if (raw.ok === false || raw.effect === "refused") {
    const code = typeof raw.code === "string" ? raw.code : "unknown_refusal";
    const message =
      typeof raw.message === "string" ? raw.message : "paper export refused";
    throw new PaperCommandRefusalError(code, message);
  }
  // The wire shape carries base64 (`pack_bytes_b64`); decoding reproduces the
  // on-disk bytes the engine armed, byte for byte.
  const b64 = typeof raw.pack_bytes_b64 === "string" ? raw.pack_bytes_b64 : "";
  const filename = typeof raw.pack_id === "string" ? raw.pack_id : null;
  return { filename, bytes: decodePackBytes(b64) };
}

function adaptStatus(raw: Record<string, unknown>): PaperStatus {
  const armed = raw.armed === true;
  const venue = typeof raw.venue === "string" ? raw.venue : undefined;
  const pair = typeof raw.pair === "string" ? raw.pair : undefined;
  const entries_paused =
    typeof raw.entries_paused === "boolean" ? raw.entries_paused : undefined;
  const mode = typeof raw.mode === "string" ? raw.mode : undefined;
  const pack_id = typeof raw.pack_id === "string" ? raw.pack_id : undefined;
  const schema_version =
    typeof raw.schema_version === "string" ? raw.schema_version : "1";
  const armed_count =
    typeof raw.armed_count === "number" && Number.isFinite(raw.armed_count)
      ? raw.armed_count
      : undefined;
  const out: PaperStatus = { schema_version, armed };
  if (venue !== undefined) out.venue = venue;
  if (pair !== undefined) out.pair = pair;
  if (entries_paused !== undefined) out.entries_paused = entries_paused;
  if (mode !== undefined) out.mode = mode;
  if (pack_id !== undefined) out.pack_id = pack_id;
  if (armed_count !== undefined) out.armed_count = armed_count;
  return out;
}

function str(raw: unknown, fallback = ""): string {
  return typeof raw === "string" ? raw : fallback;
}

function num(raw: unknown): number {
  return typeof raw === "number" && Number.isFinite(raw) ? raw : 0;
}

function adaptHistory(raw: Record<string, unknown>): PaperHistory {
  const runsRaw = Array.isArray(raw.runs) ? raw.runs : [];
  const runs: PaperRun[] = runsRaw.map((item) => {
    const run = (item ?? {}) as Record<string, unknown>;
    const fillsRaw = Array.isArray(run.recent_fills) ? run.recent_fills : [];
    const adapted: PaperRun = {
      venue: str(run.venue),
      pair: str(run.pair),
      pack_id: str(run.pack_id),
      first_ts_ms: num(run.first_ts_ms),
      last_ts_ms: num(run.last_ts_ms),
      ticks_total: num(run.ticks_total),
      last_refusal_code:
        typeof run.last_refusal_code === "string" ? run.last_refusal_code : null,
      mode: str(run.mode, "paper"),
      status: str(run.status, "closed"),
      summary: str(run.summary),
      recent_fills: fillsRaw.map((fill) => {
        const f = (fill ?? {}) as Record<string, unknown>;
        return {
          coid: str(f.coid),
          side: str(f.side),
          ts_ms: num(f.ts_ms),
        };
      }),
    };
    if (typeof run.pack_version === "string") {
      adapted.pack_version = run.pack_version;
    }
    return adapted;
  });
  return { schema_version: str(raw.schema_version, "1"), runs };
}

async function listRuns(): Promise<PaperHistory> {
  const response = await fetch("/api/v1/paper/history", {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    // A refusal body is PaperCommandResult-flavoured: keep its code or
    // message in the thrown error so the panel can surface why the
    // read was refused rather than a bare status code.
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
    throw new Error(`paper history refused: ${reason}`);
  }
  const raw = (await response.json()) as Record<string, unknown>;
  return adaptHistory(raw);
}

function adaptArmedView(raw: Record<string, unknown>): PaperArmedView {
  const schema_version =
    typeof raw.schema_version === "string" ? raw.schema_version : "1";
  const rawRecords = Array.isArray(raw.records) ? raw.records : [];
  const records: PaperArmedRecord[] = [];
  for (const entry of rawRecords) {
    if (entry === null || typeof entry !== "object") {
      continue;
    }
    const row = entry as Record<string, unknown>;
    if (
      typeof row.venue !== "string" ||
      typeof row.pair !== "string" ||
      typeof row.mode !== "string" ||
      typeof row.pack_id !== "string" ||
      typeof row.entries_paused !== "boolean"
    ) {
      continue;
    }
    records.push({
      venue: row.venue,
      pair: row.pair,
      mode: row.mode,
      pack_id: row.pack_id,
      entries_paused: row.entries_paused,
    });
  }
  return {
    schema_version,
    armed: records.length > 0,
    records,
  };
}

async function getArmedJson(url: string): Promise<PaperArmedView> {
  const response = await fetch(url, {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    throw new Error(`paper armed list failed: ${response.status}`);
  }
  const raw = (await response.json()) as Record<string, unknown>;
  return adaptArmedView(raw);
}

function adaptFleetView(raw: Record<string, unknown>): FleetArmedView {
  const schema_version =
    typeof raw.schema_version === "string" ? raw.schema_version : "1";
  const rawRows = Array.isArray(raw.deployments) ? raw.deployments : [];
  const deployments: FleetArmedDeployment[] = [];
  for (const entry of rawRows) {
    if (entry === null || typeof entry !== "object") {
      continue;
    }
    const row = entry as Record<string, unknown>;
    if (
      typeof row.venue !== "string" ||
      typeof row.pair !== "string" ||
      typeof row.mode !== "string" ||
      typeof row.pack_id !== "string" ||
      typeof row.entries_paused !== "boolean" ||
      typeof row.last_tick_result !== "string" ||
      typeof row.detail_href !== "string"
    ) {
      continue;
    }
    const lastTick =
      typeof row.last_tick_ts_ms === "number" && Number.isFinite(row.last_tick_ts_ms)
        ? row.last_tick_ts_ms
        : null;
    deployments.push({
      venue: row.venue,
      pair: row.pair,
      mode: row.mode,
      pack_id: row.pack_id,
      entries_paused: row.entries_paused,
      last_tick_ts_ms: lastTick,
      last_tick_result: row.last_tick_result,
      last_refusal_code:
        typeof row.last_refusal_code === "string" ? row.last_refusal_code : null,
      detail_href: row.detail_href,
    });
  }
  return {
    schema_version,
    armed: deployments.length > 0,
    deployments,
  };
}

async function listFleet(): Promise<FleetArmedView> {
  const response = await fetch("/api/v1/paper/fleet", {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    throw new Error(`paper fleet list failed: ${response.status}`);
  }
  const raw = (await response.json()) as Record<string, unknown>;
  return adaptFleetView(raw);
}

/**
 * Decode the closed-shape ``GET /api/v1/paper/position`` body. The
 * adapter is strict: an armed body without the projection fields, or a
 * holdings row that is not a ``{symbol, qty}`` string pair, is refused
 * with a thrown error rather than rendered as a zero position — the
 * displayed sentence must quote the wire, never a repaired variant.
 */
function adaptPosition(raw: Record<string, unknown>): PaperPosition {
  const armed = raw.armed === true;
  const out: PaperPosition = {
    schema_version: typeof raw.schema_version === "string" ? raw.schema_version : "1",
    armed,
  };
  if (!armed) {
    return out;
  }
  const pair = typeof raw.pair === "string" ? raw.pair : undefined;
  const freeCash = typeof raw.free_cash === "string" ? raw.free_cash : undefined;
  const holdingsRaw = Array.isArray(raw.holdings) ? raw.holdings : undefined;
  if (pair === undefined || freeCash === undefined || holdingsRaw === undefined) {
    throw new Error("paper position body missing projection fields");
  }
  const holdings: PaperPositionHolding[] = [];
  for (const entry of holdingsRaw) {
    if (entry === null || typeof entry !== "object") {
      throw new Error("paper position holding row malformed");
    }
    const row = entry as Record<string, unknown>;
    if (typeof row.symbol !== "string" || typeof row.qty !== "string") {
      throw new Error("paper position holding row malformed");
    }
    holdings.push({ symbol: row.symbol, qty: row.qty });
  }
  out.pair = pair;
  out.free_cash = freeCash;
  out.holdings = holdings;
  if (typeof raw.venue === "string") out.venue = raw.venue;
  if (typeof raw.mode === "string") out.mode = raw.mode;
  out.as_of_run = typeof raw.as_of_run === "string" ? raw.as_of_run : null;
  if (typeof raw.armed_count === "number" && Number.isFinite(raw.armed_count)) {
    out.armed_count = raw.armed_count;
  }
  return out;
}

/**
 * GET ``/api/v1/paper/position``: the owned paper position (free cash +
 * holdings) read from the persisted ``paper-<venue>.json`` state. Same
 * authenticated GET envelope as the other paper reads; no retry.
 */
async function getPaperPosition(select?: PaperStatusSelect): Promise<PaperPosition> {
  const response = await fetch(paperPositionUrl(select), {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    throw new Error(`paper position failed: ${response.status}`);
  }
  const raw = (await response.json()) as Record<string, unknown>;
  return adaptPosition(raw);
}

export function createHttpClient(): PaperClient &
  PaperRunsClient &
  PaperArmedClient &
  FleetArmedClient &
  Required<Pick<PaperClient, "raiseStop">> {
  return {
    getStatus(select?: PaperStatusSelect): Promise<PaperStatus> {
      return getJson(paperStatusUrl(select));
    },
    getPosition(select?: PaperStatusSelect): Promise<PaperPosition> {
      return getPaperPosition(select);
    },
    listArmed(): Promise<PaperArmedView> {
      return getArmedJson("/api/v1/paper/armed");
    },
    listFleet,
    pauseEntries(venue: string, pair: string): Promise<PaperCommandResult> {
      return postCommand("paper.pause_entries", { venue, pair });
    },
    resumeEntries(venue: string, pair: string): Promise<PaperCommandResult> {
      return postCommand("paper.resume_entries", { venue, pair });
    },
    disarm(venue: string, pair: string): Promise<PaperCommandResult> {
      return postCommand("paper.disarm", { venue, pair });
    },
    raiseStop(
      venue: string,
      pair: string,
      newStop: string,
    ): Promise<PaperCommandResult> {
      return raiseStop(venue, pair, newStop);
    },
    listRuns,
    exportPaperPack(venue: string, pair: string): Promise<PaperExportResult> {
      return exportPaperPack(venue, pair);
    },
    listOwnedDrafts,
    arm(input: PaperArmInput): Promise<PaperCommandResult> {
      return armPaperPack(input);
    },
    createRehearsalClient(): RehearsalClient {
      return createRehearsalHttpClient();
    },
  };
}

export function createFleetHttpClient(): FleetArmedClient {
  return { listFleet };
}

export function createLastRunsHttpClient(): PaperRunsClient {
  return { listRuns };
}