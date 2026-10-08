import { getCsrf } from "../../session";

export type PaperStatus = {
  schema_version: string;
  armed: boolean;
  venue?: string;
  pair?: string;
  entries_paused?: boolean;
  mode?: string;
  pack_id?: string;
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

export type PaperClient = {
  getStatus(): Promise<PaperStatus>;
  pauseEntries(venue: string, pair: string): Promise<PaperCommandResult>;
  resumeEntries(venue: string, pair: string): Promise<PaperCommandResult>;
  disarm(venue: string, pair: string): Promise<PaperCommandResult>;
  exportPaperPack?(venue: string, pair: string): Promise<PaperExportResult>;
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

async function getJson(url: string): Promise<PaperStatus> {
  const response = await fetch(url, {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
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
  const out: PaperStatus = { schema_version, armed };
  if (venue !== undefined) out.venue = venue;
  if (pair !== undefined) out.pair = pair;
  if (entries_paused !== undefined) out.entries_paused = entries_paused;
  if (mode !== undefined) out.mode = mode;
  if (pack_id !== undefined) out.pack_id = pack_id;
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

export function createHttpClient(): PaperClient & PaperRunsClient & PaperArmedClient {
  return {
    getStatus(): Promise<PaperStatus> {
      return getJson("/api/v1/paper/status");
    },
    listArmed(): Promise<PaperArmedView> {
      return getArmedJson("/api/v1/paper/armed");
    },
    pauseEntries(venue: string, pair: string): Promise<PaperCommandResult> {
      return postCommand("paper.pause_entries", { venue, pair });
    },
    resumeEntries(venue: string, pair: string): Promise<PaperCommandResult> {
      return postCommand("paper.resume_entries", { venue, pair });
    },
    disarm(venue: string, pair: string): Promise<PaperCommandResult> {
      return postCommand("paper.disarm", { venue, pair });
    },
    listRuns,
    exportPaperPack(venue: string, pair: string): Promise<PaperExportResult> {
      return exportPaperPack(venue, pair);
    },
  };
}

export function createLastRunsHttpClient(): PaperRunsClient {
  return { listRuns };
}