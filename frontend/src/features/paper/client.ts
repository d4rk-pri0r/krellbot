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

export type PaperClient = {
  getStatus(): Promise<PaperStatus>;
  pauseEntries(venue: string, pair: string): Promise<PaperCommandResult>;
  resumeEntries(venue: string, pair: string): Promise<PaperCommandResult>;
  disarm(venue: string, pair: string): Promise<PaperCommandResult>;
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

export function createHttpClient(): PaperClient {
  return {
    getStatus(): Promise<PaperStatus> {
      return getJson("/api/v1/paper/status");
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
  };
}