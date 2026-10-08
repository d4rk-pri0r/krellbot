import { afterEach, describe, expect, it, vi } from "vitest";
import { createAcknowledgedAlertsHttpClient } from "./acknowledgedAlertsClient";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function operationsBody(alerts: unknown[]): Record<string, unknown> {
  return {
    schema_version: "1",
    live: { live_enabled: false, authorized: [], kill_switch: {}, promotion_available: false },
    deployments: [],
    alerts,
  };
}

describe("createAcknowledgedAlertsHttpClient listAcknowledged", () => {
  it("GETs /api/v1/operations with credentials include and CSRF header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(operationsBody([])));
    vi.stubGlobal("fetch", fetchMock);
    await createAcknowledgedAlertsHttpClient().listAcknowledged();
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/operations");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Krellbot-CSRF"]).toBeDefined();
  });

  it("throws on non-2xx responses", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(operationsBody([]), 403));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createAcknowledgedAlertsHttpClient().listAcknowledged()).rejects.toThrow(/403/);
  });

  it("returns acknowledged alert rows in the closed shape, unchanged", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        operationsBody([
          {
            id: "a1",
            kind: "kill_switch",
            severity: "critical",
            code: null,
            venue: null,
            pair: null,
            count: 2,
            first_ts: 1700000000,
            last_ts: 1700000100,
            acknowledged: true,
          },
        ]),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const rows = await createAcknowledgedAlertsHttpClient().listAcknowledged();
    expect(rows).toEqual([
      {
        id: "a1",
        kind: "kill_switch",
        severity: "critical",
        code: null,
        venue: null,
        pair: null,
        count: 2,
        first_ts: 1700000000,
        last_ts: 1700000100,
        acknowledged: true,
      },
    ]);
  });

  it("filters the server response to only acknowledged === true entries", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        operationsBody([
          {
            id: "a1",
            kind: "kill_switch",
            severity: "critical",
            code: null,
            venue: null,
            pair: null,
            count: 2,
            first_ts: 1700000000,
            last_ts: 1700000100,
            acknowledged: true,
          },
          {
            id: "a2",
            kind: "needs_reconcile",
            severity: "critical",
            code: "coid-1",
            venue: "kraken",
            pair: "SUIUSD",
            count: 1,
            first_ts: 1700000200,
            last_ts: 1700000200,
            acknowledged: true,
          },
          {
            id: "a3",
            kind: "warning",
            severity: "warning",
            code: "refusal_code",
            venue: "kraken",
            pair: "BTCUSD",
            count: 3,
            first_ts: 1700000300,
            last_ts: 1700000400,
            acknowledged: false,
          },
        ]),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const rows = await createAcknowledgedAlertsHttpClient().listAcknowledged();
    expect(rows.map((row) => row.id)).toEqual(["a1", "a2"]);
  });
});
