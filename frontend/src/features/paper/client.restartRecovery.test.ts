import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrf, redeemBootstrap } from "../../session";
import { createHttpClient } from "./client";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function shell(): Response {
  const response = new Response('<meta name="krellbot-bootstrap" content="fresh-token">', { headers: { "Content-Type": "text/html" } });
  Object.defineProperty(response, "url", { value: "http://127.0.0.1:8765/" });
  return response;
}

beforeEach(() => {
  clearCsrf();
  vi.stubGlobal("location", new URL("http://127.0.0.1:8765/"));
});
afterEach(() => {
  clearCsrf();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("only Paper status GET retries after a real 403", () => {
  it("returns original success with unchanged adaptation and no recovery traffic", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ armed: true, pair: "BTC/USD", entries_paused: false, mode: "paper", venue: "kraken", pack_id: "owned", extra: "not adapted" }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().getStatus()).resolves.toEqual({ schema_version: "1", armed: true, pair: "BTC/USD", entries_paused: false, mode: "paper", venue: "kraken", pack_id: "owned" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("recovers after restart and retries the original status GET exactly once with current CSRF", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ csrf_token: "old-csrf" })));
    await redeemBootstrap("old-token");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({}, 403))
      .mockResolvedValueOnce(json({}, 403))
      .mockResolvedValueOnce(shell())
      .mockResolvedValueOnce(json({ csrf_token: "new-csrf" }))
      .mockResolvedValueOnce(json({ schema_version: "1", armed: true, entries_paused: false }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().getStatus()).resolves.toEqual({ schema_version: "1", armed: true, entries_paused: false });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/paper/status", "/api/v1/session/csrf", "/", "/api/v1/session/bootstrap", "/api/v1/paper/status",
    ]);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "GET", headers: { "X-Krellbot-CSRF": "old-csrf" } });
    expect(fetchMock.mock.calls[4][1]).toMatchObject({ method: "GET", credentials: "include", headers: { "X-Krellbot-CSRF": "new-csrf" } });
  });

  it("can recover a valid existing cookie without redeeming any bootstrap", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({}, 403))
      .mockResolvedValueOnce(json({ csrf_token: "recovered-csrf" }))
      .mockResolvedValueOnce(json({ armed: false }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().getStatus()).resolves.toEqual({ schema_version: "1", armed: false });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it.each([401, 404, 500])("does not recover or retry original HTTP %s", async (status) => {
    const fetchMock = vi.fn().mockResolvedValue(json({}, status));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().getStatus()).rejects.toThrow(`paper status failed: ${status}`);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not retry an offline original request", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("backend unavailable"));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().getStatus()).rejects.toThrow("backend unavailable");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([403, 500])("preserves final denial/error %s without a second recovery or retry", async (status) => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({}, 403))
      .mockResolvedValueOnce(json({ csrf_token: "recovered-csrf" }))
      .mockResolvedValueOnce(json({}, status));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().getStatus()).rejects.toThrow(`paper status failed: ${status}`);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("preserves honest status error if recovery fails, with no status replay", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({}, 403))
      .mockRejectedValueOnce(new TypeError("backend disappeared"));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().getStatus()).rejects.toThrow("paper status failed: 403");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("concurrent forbidden reads share bootstrap recovery but each retries its own GET once", async () => {
    let release!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => { release = resolve; });
    let statusReads = 0;
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/v1/paper/status") return Promise.resolve(json({ armed: true }, ++statusReads <= 2 ? 403 : 200));
      if (url === "/api/v1/session/csrf") return pending;
      if (url === "/") return Promise.resolve(shell());
      if (url === "/api/v1/session/bootstrap") return Promise.resolve(json({ csrf_token: "shared-csrf" }));
      throw new Error("unexpected fetch");
    });
    vi.stubGlobal("fetch", fetchMock);
    const a = createHttpClient().getStatus();
    const b = createHttpClient().getStatus();
    release(json({}, 403));
    expect(await Promise.all([a, b])).toEqual([{ schema_version: "1", armed: true }, { schema_version: "1", armed: true }]);
    expect(statusReads).toBe(4);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/v1/session/csrf")).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/v1/session/bootstrap")).toHaveLength(1);
  });

  it.each(["pauseEntries", "resumeEntries", "disarm", "raiseStop", "exportPaperPack", "arm"] as const)("never recovers or replays command %s on 403", async (command) => {
    const fetchMock = vi.fn().mockResolvedValue(json({}, 403));
    vi.stubGlobal("fetch", fetchMock);
    const client = createHttpClient();
    const result = command === "arm"
      ? client.arm!({ revision_id: "owned", venue: "kraken", mode: "paper", paper_balance: "1000" })
      : command === "raiseStop" ? client.raiseStop("kraken", "BTC/USD", "1")
      : client[command]!("kraken", "BTC/USD");
    await expect(result).rejects.toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/commands");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST" });
  });

  it.each(["getPosition", "listRuns", "listArmed", "listOwnedDrafts"] as const)("leaves other read %s explicitly out of scope", async (read) => {
    const fetchMock = vi.fn().mockResolvedValue(json({}, 403));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient()[read]!()).rejects.toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
