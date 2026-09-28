export type RunRequest = {
  datasetPath: string;
  feeBps: number;
  fromMs: number;
  toMs: number;
  packPath?: string;
};

export type ResearchJobSummary = {
  id: string;
  state: string;
};

export type StoredResult = {
  legacy_receipt: Record<string, unknown>;
  trace: Array<Record<string, unknown>>;
};

export type ResearchClient = {
  submitRun(request: RunRequest): Promise<ResearchJobSummary>;
  cancelJob(jobId: string): Promise<void>;
  getResult(jobId: string): Promise<StoredResult | null>;
};

function readCsrf(): string {
  if (typeof document === "undefined") {
    return "";
  }
  const match = document.cookie.match(/(?:^|;\s*)krellbot_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function postJson(url: string, body: unknown): Promise<unknown> {
  const response = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Krellbot-CSRF": readCsrf(),
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
      "X-Krellbot-CSRF": readCsrf(),
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
      const raw = (await postJson("/api/v1/jobs", body)) as {
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
  };
}
