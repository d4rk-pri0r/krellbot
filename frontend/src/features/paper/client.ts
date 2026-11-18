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

export type PaperPnlPoint = {
  ts_ms: number;
  value: string;
};

export type PaperPositionPoint = {
  ts_ms: number;
  qty: string;
};

export type PaperMarkPoint = {
  ts_ms: number;
  price: string;
};

/**
 * Closed-shape chart body from ``GET /api/v1/paper/chart``.
 * Series quote journal ticks and paper-state fills; empty when
 * evidence is missing.
 */
export type PaperChart = {
  schema_version: string;
  armed: boolean;
  venue?: string;
  pair?: string;
  mode?: string;
  pack_id?: string;
  starting_cash?: string;
  pnl: PaperPnlPoint[];
  position: PaperPositionPoint[];
  marks: PaperMarkPoint[];
};

export type PaperChartClient = {
  getChart(): Promise<PaperChart>;
};

export type PaperStatusSelect = {
  venue: string;
  pair: string;
};

export type PaperClient = {
  getStatus(select?: PaperStatusSelect): Promise<PaperStatus>;
  getPosition?(select?: PaperStatusSelect): Promise<PaperPosition>;
  getChart?(): Promise<PaperChart>;
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

/** One projected event from ``GET /api/v1/paper/ledger``. */
export type ForwardPaperLedgerEvent = {
  ts: number;
  kind: string;
  venue: string;
  pack: string;
  pair: string | null;
  detail: Record<string, unknown>;
};

/** Closed-shape forward paper ledger body (oldest→newest evidence). */
export type ForwardPaperLedger = {
  schema_version: string;
  mode: string;
  order: string;
  presentation: string;
  disclaimer: string;
  events: ForwardPaperLedgerEvent[];
};

export type ForwardPaperLedgerClient = {
  listForwardLedger(): Promise<ForwardPaperLedger>;
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

/** One ``(venue, pair)`` group from the multi-pair fleet API (M16.1). */
export type FleetArmedGroup = {
  venue: string;
  pair: string;
  deployments: FleetArmedDeployment[];
};

export type FleetArmedView = {
  schema_version: string;
  armed: boolean;
  /** Unfiltered armed total; present on M16.1+ wire. */
  armed_count?: number;
  deployments: FleetArmedDeployment[];
  /** Deployments keyed by ``(venue, pair)``; empty when none armed. */
  groups?: FleetArmedGroup[];
};

export type FleetArmedClient = {
  listFleet(select?: { venue?: string; pair?: string }): Promise<FleetArmedView>;
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

function adaptForwardLedger(raw: Record<string, unknown>): ForwardPaperLedger {
  const eventsRaw = Array.isArray(raw.events) ? raw.events : [];
  const events: ForwardPaperLedgerEvent[] = [];
  for (const item of eventsRaw) {
    if (item === null || typeof item !== "object") {
      continue;
    }
    const row = item as Record<string, unknown>;
    const detail =
      row.detail !== null && typeof row.detail === "object"
        ? (row.detail as Record<string, unknown>)
        : {};
    events.push({
      ts: typeof row.ts === "number" ? row.ts : Number(row.ts) || 0,
      kind: typeof row.kind === "string" ? row.kind : "",
      venue: typeof row.venue === "string" ? row.venue : "",
      pack: typeof row.pack === "string" ? row.pack : "",
      pair: typeof row.pair === "string" ? row.pair : null,
      detail,
    });
  }
  return {
    schema_version:
      typeof raw.schema_version === "string" ? raw.schema_version : "1",
    mode: typeof raw.mode === "string" ? raw.mode : "paper",
    order: typeof raw.order === "string" ? raw.order : "forward",
    presentation:
      typeof raw.presentation === "string"
        ? raw.presentation
        : "local_evidence",
    disclaimer:
      typeof raw.disclaimer === "string"
        ? raw.disclaimer
        : "Paper evidence — not live P&L",
    events,
  };
}

async function listForwardLedger(): Promise<ForwardPaperLedger> {
  const response = await fetch("/api/v1/paper/ledger", {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
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
    throw new Error(`paper ledger refused: ${reason}`);
  }
  const raw = (await response.json()) as Record<string, unknown>;
  return adaptForwardLedger(raw);
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

function adaptFleetDeployment(row: Record<string, unknown>): FleetArmedDeployment | null {
  if (
    typeof row.venue !== "string" ||
    typeof row.pair !== "string" ||
    typeof row.mode !== "string" ||
    typeof row.pack_id !== "string" ||
    typeof row.entries_paused !== "boolean" ||
    typeof row.last_tick_result !== "string" ||
    typeof row.detail_href !== "string"
  ) {
    return null;
  }
  const lastTick =
    typeof row.last_tick_ts_ms === "number" && Number.isFinite(row.last_tick_ts_ms)
      ? row.last_tick_ts_ms
      : null;
  return {
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
  };
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
    const adapted = adaptFleetDeployment(entry as Record<string, unknown>);
    if (adapted !== null) {
      deployments.push(adapted);
    }
  }
  const groups: FleetArmedGroup[] = [];
  if (Array.isArray(raw.groups)) {
    for (const entry of raw.groups) {
      if (entry === null || typeof entry !== "object") {
        continue;
      }
      const group = entry as Record<string, unknown>;
      if (typeof group.venue !== "string" || typeof group.pair !== "string") {
        continue;
      }
      const groupRows = Array.isArray(group.deployments) ? group.deployments : [];
      const adaptedRows: FleetArmedDeployment[] = [];
      for (const row of groupRows) {
        if (row === null || typeof row !== "object") {
          continue;
        }
        const adapted = adaptFleetDeployment(row as Record<string, unknown>);
        if (adapted !== null) {
          adaptedRows.push(adapted);
        }
      }
      groups.push({
        venue: group.venue,
        pair: group.pair,
        deployments: adaptedRows,
      });
    }
  }
  const armed_count =
    typeof raw.armed_count === "number" && Number.isFinite(raw.armed_count)
      ? Math.max(0, Math.trunc(raw.armed_count))
      : deployments.length;
  return {
    schema_version,
    armed: deployments.length > 0,
    armed_count,
    deployments,
    groups,
  };
}

async function listFleet(select?: {
  venue?: string;
  pair?: string;
}): Promise<FleetArmedView> {
  const params = new URLSearchParams();
  if (select?.venue) {
    params.set("venue", select.venue);
  }
  if (select?.pair) {
    params.set("pair", select.pair);
  }
  const query = params.toString();
  const path =
    query.length > 0 ? `/api/v1/paper/fleet?${query}` : "/api/v1/paper/fleet";
  const response = await fetch(path, {
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

function adaptChartPoint(
  raw: unknown,
  valueKey: "value" | "qty" | "price",
): { ts_ms: number; [key: string]: string | number } | null {
  if (raw === null || typeof raw !== "object") {
    return null;
  }
  const row = raw as Record<string, unknown>;
  const ts =
    typeof row.ts_ms === "number" && Number.isFinite(row.ts_ms)
      ? row.ts_ms
      : null;
  const value = typeof row[valueKey] === "string" ? row[valueKey] : null;
  if (ts === null || value === null) {
    return null;
  }
  return { ts_ms: ts, [valueKey]: value };
}

/**
 * Decode the closed-shape ``GET /api/v1/paper/chart`` body. An armed body
 * missing series arrays is refused rather than repaired into empty
 * charts — the workstation must quote the wire.
 */
function adaptChart(raw: Record<string, unknown>): PaperChart {
  const armed = raw.armed === true;
  const out: PaperChart = {
    schema_version:
      typeof raw.schema_version === "string" ? raw.schema_version : "1",
    armed,
    pnl: [],
    position: [],
    marks: [],
  };
  if (!armed) {
    return out;
  }
  if (
    !Array.isArray(raw.pnl) ||
    !Array.isArray(raw.position) ||
    !Array.isArray(raw.marks)
  ) {
    throw new Error("paper chart body missing series arrays");
  }
  const pnl: PaperPnlPoint[] = [];
  for (const item of raw.pnl) {
    const point = adaptChartPoint(item, "value");
    if (point === null || typeof point.value !== "string") {
      throw new Error("paper chart pnl point malformed");
    }
    pnl.push({ ts_ms: point.ts_ms, value: point.value });
  }
  const position: PaperPositionPoint[] = [];
  for (const item of raw.position) {
    const point = adaptChartPoint(item, "qty");
    if (point === null || typeof point.qty !== "string") {
      throw new Error("paper chart position point malformed");
    }
    position.push({ ts_ms: point.ts_ms, qty: point.qty });
  }
  const marks: PaperMarkPoint[] = [];
  for (const item of raw.marks) {
    const point = adaptChartPoint(item, "price");
    if (point === null || typeof point.price !== "string") {
      throw new Error("paper chart mark point malformed");
    }
    marks.push({ ts_ms: point.ts_ms, price: point.price });
  }
  out.pnl = pnl;
  out.position = position;
  out.marks = marks;
  if (typeof raw.venue === "string") out.venue = raw.venue;
  if (typeof raw.pair === "string") out.pair = raw.pair;
  if (typeof raw.mode === "string") out.mode = raw.mode;
  if (typeof raw.pack_id === "string") out.pack_id = raw.pack_id;
  if (typeof raw.starting_cash === "string") {
    out.starting_cash = raw.starting_cash;
  }
  return out;
}

/**
 * GET ``/api/v1/paper/chart``: P&L + position (or mark) series from
 * journal ticks and paper-state fills. Same authenticated GET envelope
 * as the other paper reads; no retry.
 */
async function getPaperChart(): Promise<PaperChart> {
  const response = await fetch("/api/v1/paper/chart", {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    throw new Error(`paper chart failed: ${response.status}`);
  }
  const raw = (await response.json()) as Record<string, unknown>;
  return adaptChart(raw);
}

export function createHttpClient(): PaperClient &
  PaperRunsClient &
  PaperArmedClient &
  PaperChartClient &
  FleetArmedClient &
  ForwardPaperLedgerClient &
  Required<Pick<PaperClient, "raiseStop">> {
  return {
    getStatus(select?: PaperStatusSelect): Promise<PaperStatus> {
      return getJson(paperStatusUrl(select));
    },
    getPosition(select?: PaperStatusSelect): Promise<PaperPosition> {
      return getPaperPosition(select);
    },
    getChart(): Promise<PaperChart> {
      return getPaperChart();
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
    listForwardLedger,
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

export function createForwardPaperLedgerHttpClient(): ForwardPaperLedgerClient {
  return { listForwardLedger };
}