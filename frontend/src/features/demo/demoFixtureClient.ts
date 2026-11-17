import { getCsrf } from "../../session";

export type DemoFixtureDeployment = {
  id: string;
  label: string;
  venue: string;
  pair: string;
  mode: string;
  pack_id: string;
  status: string;
  is_fixture: boolean;
  live_performance: boolean;
  soak_proof: boolean;
};

export type DemoFixtureStatus = {
  schema_version: string;
  enabled: boolean;
  label: string | null;
  badge: string | null;
  honesty_note: string;
  is_fixture: boolean;
  live_performance: boolean;
  soak_proof: boolean;
  deployments: ReadonlyArray<DemoFixtureDeployment>;
  message: string;
  ok?: boolean;
  code?: string;
};

export type DemoFixtureClient = {
  getStatus(): Promise<DemoFixtureStatus>;
  seed(confirm: boolean): Promise<DemoFixtureStatus>;
  clear(): Promise<DemoFixtureStatus>;
};

function adaptDeployment(raw: unknown): DemoFixtureDeployment {
  const row = (raw ?? {}) as Record<string, unknown>;
  return {
    id: String(row.id ?? ""),
    label: String(row.label ?? ""),
    venue: String(row.venue ?? ""),
    pair: String(row.pair ?? ""),
    mode: String(row.mode ?? "paper"),
    pack_id: String(row.pack_id ?? ""),
    status: String(row.status ?? ""),
    is_fixture: row.is_fixture === true,
    live_performance: row.live_performance === true,
    soak_proof: row.soak_proof === true,
  };
}

export function adaptDemoFixtureStatus(raw: unknown): DemoFixtureStatus {
  const body = (raw ?? {}) as Record<string, unknown>;
  const deployments = Array.isArray(body.deployments)
    ? body.deployments.map(adaptDeployment)
    : [];
  return {
    schema_version: String(body.schema_version ?? "1"),
    enabled: body.enabled === true,
    label: body.label == null ? null : String(body.label),
    badge: body.badge == null ? null : String(body.badge),
    honesty_note: String(body.honesty_note ?? ""),
    is_fixture: body.is_fixture === true,
    // Honesty: never trust wire bits that claim live/soak for fixtures.
    live_performance: false,
    soak_proof: false,
    deployments: deployments.map((row) => ({
      ...row,
      live_performance: false,
      soak_proof: false,
      is_fixture: true,
    })),
    message: String(body.message ?? ""),
    ok: typeof body.ok === "boolean" ? body.ok : undefined,
    code: body.code == null ? undefined : String(body.code),
  };
}

export function createDemoFixtureHttpClient(
  fetchImpl: typeof fetch = fetch,
): DemoFixtureClient {
  return {
    async getStatus(): Promise<DemoFixtureStatus> {
      const response = await fetchImpl("/api/v1/demo-fixture", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`demo fixture status failed: ${response.status}`);
      }
      return adaptDemoFixtureStatus(await response.json());
    },
    async seed(confirm: boolean): Promise<DemoFixtureStatus> {
      const csrf = getCsrf();
      const response = await fetchImpl("/api/v1/demo-fixture/seed", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          ...(csrf ? { "X-Krellbot-CSRF": csrf } : {}),
        },
        body: JSON.stringify({ confirm }),
      });
      const body = adaptDemoFixtureStatus(await response.json());
      if (!response.ok) {
        throw new Error(body.message || `demo fixture seed failed: ${response.status}`);
      }
      return body;
    },
    async clear(): Promise<DemoFixtureStatus> {
      const csrf = getCsrf();
      const response = await fetchImpl("/api/v1/demo-fixture/clear", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          ...(csrf ? { "X-Krellbot-CSRF": csrf } : {}),
        },
        body: "{}",
      });
      const body = adaptDemoFixtureStatus(await response.json());
      if (!response.ok) {
        throw new Error(body.message || `demo fixture clear failed: ${response.status}`);
      }
      return body;
    },
  };
}
