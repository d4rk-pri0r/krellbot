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

describe("createHttpClient getStatus", () => {
  it("GETs /api/v1/paper/status with credentials: include", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        armed: true,
        venue: "kraken",
        pair: "SUIUSD",
        entries_paused: false,
        mode: "paper",
        pack_id: "trend-follow",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const status = await createHttpClient().getStatus();
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/paper/status");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect(status.armed).toBe(true);
    expect(status.venue).toBe("kraken");
    expect(status.pair).toBe("SUIUSD");
    expect(status.entries_paused).toBe(false);
    expect(status.mode).toBe("paper");
    expect(status.pack_id).toBe("trend-follow");
  });

  it("returns armed=false without the projection fields when no pack is armed", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", armed: false }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const status = await createHttpClient().getStatus();
    expect(status.armed).toBe(false);
    expect(status.venue).toBeUndefined();
    expect(status.pair).toBeUndefined();
    expect(status.entries_paused).toBeUndefined();
  });

  it("throws on non-2xx response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, 403));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().getStatus()).rejects.toThrow(/403/);
  });
});

describe("createHttpClient paper commands", () => {
  it("pauseEntries posts paper.pause_entries with venue/pair payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", code: "entries_paused", ok: true }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await createHttpClient().pauseEntries("kraken", "SUIUSD");
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/commands");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(JSON.parse(String(init.body))).toEqual({
      schema_version: "1",
      command: "paper.pause_entries",
      payload: { venue: "kraken", pair: "SUIUSD" },
    });
  });

  it("resumeEntries posts paper.resume_entries with venue/pair payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", code: "entries_resumed", ok: true }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await createHttpClient().resumeEntries("kraken", "SUIUSD");
    expect(fetchMock).toHaveBeenCalledOnce();
    const [_url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      schema_version: "1",
      command: "paper.resume_entries",
      payload: { venue: "kraken", pair: "SUIUSD" },
    });
  });

  it("disarm posts paper.disarm with venue/pair payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", code: "disarmed", ok: true }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await createHttpClient().disarm("kraken", "SUIUSD");
    expect(fetchMock).toHaveBeenCalledOnce();
    const [_url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      schema_version: "1",
      command: "paper.disarm",
      payload: { venue: "kraken", pair: "SUIUSD" },
    });
  });

  it("does not send mode: live in any command body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", ok: true }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = createHttpClient();
    await client.pauseEntries("kraken", "SUIUSD");
    await client.resumeEntries("kraken", "SUIUSD");
    await client.disarm("kraken", "SUIUSD");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    for (const call of fetchMock.mock.calls) {
      const init = call[1] as RequestInit;
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      const payload = (body.payload ?? {}) as Record<string, unknown>;
      expect(payload.mode).toBeUndefined();
      expect(body.command).not.toMatch(/^live\./);
    }
  });
});