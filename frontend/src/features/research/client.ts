import { getCsrf } from "../../session";

export type RunRequest = {
  datasetPath: string;
  feeBps: number;
  fromMs: number;
  toMs: number;
  packPath?: string;
  revisionId?: string;
  holdoutFromMs?: number;
  holdoutToMs?: number;
};

export type ResearchJobSummary = {
  id: string;
  state: string;
};

export type StoredResult = {
  legacy_receipt: Record<string, unknown>;
  trace: Array<Record<string, unknown>>;
};

export type ResearchJobSnapshot = {
  id: string;
  state: string;
  error?: { code: string; message: string };
};

export type ResearchClient = {
  submitRun(request: RunRequest): Promise<ResearchJobSummary>;
  cancelJob(jobId: string): Promise<void>;
  getResult(jobId: string): Promise<StoredResult | null>;
  getJob(jobId: string): Promise<ResearchJobSnapshot | null>;
  getResultDownload(jobId: string): Promise<Response>;
};

async function postJson(url: string, body: unknown): Promise<unknown> {
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
  return await response.json();
}

async function getJson(url: string): Promise<unknown | null> {
  const response = await fetch(url, {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
  return await response.json();
}

export function createHttpClient(): ResearchClient {
  return {
    async submitRun(request: RunRequest): Promise<ResearchJobSummary> {
      const body: Record<string, unknown> = {
        kind: "research.backtest",
        correlation_id: "research-ui",
        dataset_csv: request.datasetPath,
        fee_bps: request.feeBps,
        from_ms: request.fromMs,
        to_ms: request.toMs,
      };
      if (request.packPath) {
        body.pack_path = request.packPath;
      }
      if (request.revisionId) {
        body.revision_id = request.revisionId;
      }
      if (typeof request.holdoutFromMs === "number") {
        body.holdout_from_ms = request.holdoutFromMs;
      }
      if (typeof request.holdoutToMs === "number") {
        body.holdout_to_ms = request.holdoutToMs;
      }
      const raw = (await postJson("/api/v1/research/jobs", body)) as {
        id?: string;
        state?: string;
      };
      return {
        id: String(raw.id ?? ""),
        state: String(raw.state ?? ""),
      };
    },
    async cancelJob(jobId: string): Promise<void> {
      await postJson(
        `/api/v1/jobs/${encodeURIComponent(jobId)}/cancel`,
        {},
      );
    },
    async getResult(jobId: string): Promise<StoredResult | null> {
      const raw = await getJson(
        `/api/v1/jobs/${encodeURIComponent(jobId)}/result`,
      );
      if (raw === null) {
        return null;
      }
      if (raw === null || typeof raw !== "object") {
        return null;
      }
      const obj = raw as { legacy_receipt?: unknown; trace?: unknown };
      if (!obj.legacy_receipt || typeof obj.legacy_receipt !== "object") {
        return null;
      }
      const trace = Array.isArray(obj.trace)
        ? (obj.trace as Array<Record<string, unknown>>)
        : [];
      return {
        legacy_receipt: obj.legacy_receipt as Record<string, unknown>,
        trace,
      };
    },
    async getJob(jobId: string): Promise<ResearchJobSnapshot | null> {
      const raw = await getJson(
        `/api/v1/jobs/${encodeURIComponent(jobId)}`,
      );
      if (raw === null || typeof raw !== "object") {
        return null;
      }
      const obj = raw as {
        id?: unknown;
        state?: unknown;
        error?: unknown;
      };
      if (typeof obj.id !== "string" || typeof obj.state !== "string") {
        return null;
      }
      let error: { code: string; message: string } | undefined;
      if (obj.error && typeof obj.error === "object") {
        const e = obj.error as { code?: unknown; message?: unknown };
        if (typeof e.code === "string" && typeof e.message === "string") {
          error = { code: e.code, message: e.message };
        }
      }
      const snap: ResearchJobSnapshot = { id: obj.id, state: obj.state };
      if (error !== undefined) {
        snap.error = error;
      }
      return snap;
    },
    async getResultDownload(jobId: string): Promise<Response> {
      const response = await fetch(
        `/api/v1/jobs/${encodeURIComponent(jobId)}/result/download`,
        {
          method: "GET",
          credentials: "include",
          headers: {
            "X-Krellbot-CSRF": getCsrf(),
          },
        },
      );
      if (!response.ok) {
        throw new Error(`download failed: ${response.status}`);
      }
      return response;
    },
  };
}
