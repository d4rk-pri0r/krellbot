import { afterEach, describe, expect, it, vi } from "vitest";
import { createHttpClient } from "./client";

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

describe("createHttpClient getOperations", () => {
  it("GETs /api/v1/operations with credentials include", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        live: { live_enabled: false, authorized: [], kill_switch: {}, promotion_available: false },
        deployments: [],
        alerts: [],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const view = await createHttpClient().getOperations();
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/operations");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect(view.live.live_enabled).toBe(false);
  });
});

describe("createHttpClient typed POST bodies", () => {
  it("promote posts live.promote with venue/pair/revision_id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", code: "live_disabled", ok: false }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await createHttpClient().promote("kraken", "SUIUSD", "rev-abc");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/commands");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body.command).toBe("live.promote");
    const payload = body.payload as Record<string, unknown>;
    expect(payload.venue).toBe("kraken");
    expect(payload.pair).toBe("SUIUSD");
    expect(payload.revision_id).toBe("rev-abc");
    expect("args" in body).toBe(false);
    expect("params" in body).toBe(false);
    expect(body.schema_version).toBe("1");
  });

  it("pauseEntries posts paper.pause_entries with venue/pair payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", code: "entries_paused", ok: true }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await createHttpClient().pauseEntries("kraken", "SUIUSD");
    const body = JSON.parse(String((fetchMock.mock.calls[0] as [string, RequestInit])[1].body)) as Record<string, unknown>;
    expect(body.command).toBe("paper.pause_entries");
    expect(body.payload).toEqual({ venue: "kraken", pair: "SUIUSD" });
  });

  it("resumeEntries posts paper.resume_entries with venue/pair payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", code: "entries_resumed", ok: true }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await createHttpClient().resumeEntries("kraken", "SUIUSD");
    const body = JSON.parse(String((fetchMock.mock.calls[0] as [string, RequestInit])[1].body)) as Record<string, unknown>;
    expect(body.command).toBe("paper.resume_entries");
    expect(body.payload).toEqual({ venue: "kraken", pair: "SUIUSD" });
  });

  it("engageKill posts operations.kill with reason payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", code: "kill_switch_engaged", ok: true }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await createHttpClient().engageKill("ops-spec reason");
    const body = JSON.parse(String((fetchMock.mock.calls[0] as [string, RequestInit])[1].body)) as Record<string, unknown>;
    expect(body.command).toBe("operations.kill");
    expect(body.payload).toEqual({ reason: "ops-spec reason" });
  });

  it("releaseKill posts operations.release_kill with empty payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", code: "kill_switch_released", ok: true }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await createHttpClient().releaseKill();
    const body = JSON.parse(String((fetchMock.mock.calls[0] as [string, RequestInit])[1].body)) as Record<string, unknown>;
    expect(body.command).toBe("operations.release_kill");
    expect(body.payload).toEqual({});
  });

  it("ackAlert posts alerts.ack with alert_id payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", code: "acknowledged", ok: true }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await createHttpClient().ackAlert("abc123");
    const body = JSON.parse(String((fetchMock.mock.calls[0] as [string, RequestInit])[1].body)) as Record<string, unknown>;
    expect(body.command).toBe("alerts.ack");
    expect(body.payload).toEqual({ alert_id: "abc123" });
  });

  it("no command uses args or params key", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", ok: true }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = createHttpClient();
    await client.promote("kraken", "SUIUSD", "rev-abc");
    await client.pauseEntries("kraken", "SUIUSD");
    await client.resumeEntries("kraken", "SUIUSD");
    await client.engageKill("x");
    await client.releaseKill();
    await client.ackAlert("abc");
    expect(fetchMock).toHaveBeenCalledTimes(6);
    for (const call of fetchMock.mock.calls) {
      const init = call[1] as RequestInit;
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      expect("args" in body).toBe(false);
      expect("params" in body).toBe(false);
    }
  });

  it("throws on non-2xx response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, 403));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().getOperations()).rejects.toThrow(/403/);
  });
});