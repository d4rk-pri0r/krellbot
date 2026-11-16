import { getCsrf } from "../../session";

/**
 * Closed-shape body from ``GET /api/v1/portfolio/history``.
 * Series and cards quote journal + paper fills; empty when evidence
 * is missing — never fabricated sample bots or flat zero equity.
 */

export type PortfolioPnlPoint = {
  ts_ms: number;
  value: string;
};

export type PortfolioEquityPoint = {
  ts_ms: number;
  value: string;
};

export type PortfolioDeployment = {
  venue: string;
  pair: string;
  pack_id: string;
  mode: string;
  status: string;
  starting_cash: string | null;
  fills_total: number;
  first_ts_ms: number;
  last_ts_ms: number;
  last_pnl: string | null;
  pnl: PortfolioPnlPoint[];
};

export type PortfolioHistory = {
  schema_version: string;
  equity: PortfolioEquityPoint[];
  deployments: PortfolioDeployment[];
};

export type PortfolioClient = {
  getHistory(): Promise<PortfolioHistory>;
};

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function num(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function adaptPnlPoint(raw: unknown): PortfolioPnlPoint | null {
  if (raw === null || typeof raw !== "object") {
    return null;
  }
  const row = raw as Record<string, unknown>;
  const ts =
    typeof row.ts_ms === "number" && Number.isFinite(row.ts_ms)
      ? row.ts_ms
      : null;
  const value = typeof row.value === "string" ? row.value : null;
  if (ts === null || value === null) {
    return null;
  }
  return { ts_ms: ts, value };
}

function adaptDeployment(raw: unknown): PortfolioDeployment {
  const row = (raw ?? {}) as Record<string, unknown>;
  const pnlRaw = Array.isArray(row.pnl) ? row.pnl : [];
  const pnl: PortfolioPnlPoint[] = [];
  for (const item of pnlRaw) {
    const point = adaptPnlPoint(item);
    if (point !== null) {
      pnl.push(point);
    }
  }
  const starting =
    typeof row.starting_cash === "string"
      ? row.starting_cash
      : row.starting_cash === null
        ? null
        : null;
  const lastPnl =
    typeof row.last_pnl === "string"
      ? row.last_pnl
      : row.last_pnl === null
        ? null
        : null;
  return {
    venue: str(row.venue),
    pair: str(row.pair),
    pack_id: str(row.pack_id),
    mode: str(row.mode, "paper"),
    status: str(row.status, "closed"),
    starting_cash: starting,
    fills_total: num(row.fills_total),
    first_ts_ms: num(row.first_ts_ms),
    last_ts_ms: num(row.last_ts_ms),
    last_pnl: lastPnl,
    pnl,
  };
}

function adaptHistory(raw: Record<string, unknown>): PortfolioHistory {
  if (!Array.isArray(raw.equity) || !Array.isArray(raw.deployments)) {
    throw new Error("portfolio history body missing series arrays");
  }
  const equity: PortfolioEquityPoint[] = [];
  for (const item of raw.equity) {
    const point = adaptPnlPoint(item);
    if (point === null) {
      throw new Error("portfolio equity point malformed");
    }
    equity.push(point);
  }
  return {
    schema_version: str(raw.schema_version, "1"),
    equity,
    deployments: raw.deployments.map(adaptDeployment),
  };
}

/**
 * GET ``/api/v1/portfolio/history``: cross-deployment equity + cards.
 * Same authenticated GET envelope as paper reads; no retry.
 */
export async function getPortfolioHistory(): Promise<PortfolioHistory> {
  const response = await fetch("/api/v1/portfolio/history", {
    method: "GET",
    credentials: "include",
    headers: {
      "X-Krellbot-CSRF": getCsrf(),
    },
  });
  if (!response.ok) {
    throw new Error(`portfolio history failed: ${response.status}`);
  }
  const raw = (await response.json()) as Record<string, unknown>;
  return adaptHistory(raw);
}

export function createPortfolioHttpClient(): PortfolioClient {
  return {
    getHistory(): Promise<PortfolioHistory> {
      return getPortfolioHistory();
    },
  };
}
