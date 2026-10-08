import { afterEach, describe, expect, it, vi } from "vitest";
import { createHttpClient, createLastRunsHttpClient } from "./client";
import { getCsrf } from "../../session";

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

describe("createHttpClient listArmed", () => {
  it("GETs /api/v1/paper/armed with credentials: include and the CSRF header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        armed: true,
        records: [
          {
            venue: "kraken",
            pair: "SUIUSD",
            mode: "paper",
            pack_id: "trend-follow",
            entries_paused: false,
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const view = await createHttpClient().listArmed();
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/paper/armed");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Krellbot-CSRF"]).toBe(getCsrf());
    expect(view.armed).toBe(true);
    expect(view.records).toHaveLength(1);
    expect(view.records[0]).toEqual({
      venue: "kraken",
      pair: "SUIUSD",
      mode: "paper",
      pack_id: "trend-follow",
      entries_paused: false,
    });
  });

  it("parses the armed=false body to an empty PaperArmedView", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", armed: false, records: [] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const view = await createHttpClient().listArmed();
    expect(view.armed).toBe(false);
    expect(view.records).toEqual([]);
  });

  it("returns multiple rows for multiple armed records", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        armed: true,
        records: [
          {
            venue: "kraken",
            pair: "SUIUSD",
            mode: "paper",
            pack_id: "trend-follow",
            entries_paused: false,
          },
          {
            venue: "coinbase",
            pair: "BTC-USD",
            mode: "paper",
            pack_id: "mean-revert",
            entries_paused: true,
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const view = await createHttpClient().listArmed();
    expect(view.armed).toBe(true);
    expect(view.records).toHaveLength(2);
    expect(view.records[1]?.entries_paused).toBe(true);
  });

  it("never carries cash, quantity, or stop fields on a row", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        armed: true,
        records: [
          {
            venue: "kraken",
            pair: "SUIUSD",
            mode: "paper",
            pack_id: "trend-follow",
            entries_paused: false,
            starting_cash: 1000,
            owned_qty: 2.5,
            stop: 9.75,
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const view = await createHttpClient().listArmed();
    const row = view.records[0] as unknown as Record<string, unknown>;
    expect(view.records).toHaveLength(1);
    expect(row.starting_cash).toBeUndefined();
    expect(row.owned_qty).toBeUndefined();
    expect(row.stop).toBeUndefined();
    expect(row.cap).toBeUndefined();
    expect(row.pack_path).toBeUndefined();
  });

  it("drops rows with unexpected shapes instead of coercing them", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        armed: true,
        records: [
          { venue: "kraken" },
          {
            venue: "coinbase",
            pair: "BTC-USD",
            mode: "paper",
            pack_id: "mean-revert",
            entries_paused: true,
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const view = await createHttpClient().listArmed();
    expect(view.records).toHaveLength(1);
    expect(view.records[0]?.venue).toBe("coinbase");
  });

  it("throws on non-2xx response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, 403));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().listArmed()).rejects.toThrow(/403/);
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

describe("createHttpClient listRuns", () => {
  it("GETs /api/v1/paper/history with credentials: include and the CSRF header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        runs: [
          {
            venue: "kraken",
            pair: "SUIUSD",
            pack_id: "trend-follow",
            first_ts_ms: 1_760_000_100_000,
            last_ts_ms: 1_760_000_200_000,
            ticks_total: 2,
            last_refusal_code: "store_full",
            mode: "paper",
            status: "closed",
            summary: "2 ticks, 2 fills, last refusal store_full, closed",
            recent_fills: [
              { coid: "coid-entry-1", side: "buy", ts_ms: 1_000 },
              { coid: "coid-exit-1", side: "sell", ts_ms: 2_000 },
            ],
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const history = await createHttpClient().listRuns();
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/paper/history");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect(init.headers).toEqual({ "X-Krellbot-CSRF": getCsrf() });
    expect(history.schema_version).toBe("1");
    expect(history.runs).toHaveLength(1);
    const run = history.runs[0];
    expect(run.venue).toBe("kraken");
    expect(run.pair).toBe("SUIUSD");
    expect(run.pack_id).toBe("trend-follow");
    expect(run.pack_version).toBeUndefined();
    expect(run.first_ts_ms).toBe(1_760_000_100_000);
    expect(run.last_ts_ms).toBe(1_760_000_200_000);
    expect(run.ticks_total).toBe(2);
    expect(run.last_refusal_code).toBe("store_full");
    expect(run.mode).toBe("paper");
    expect(run.status).toBe("closed");
    expect(run.summary).toBe("2 ticks, 2 fills, last refusal store_full, closed");
    expect(run.recent_fills).toEqual([
      { coid: "coid-entry-1", side: "buy", ts_ms: 1_000 },
      { coid: "coid-exit-1", side: "sell", ts_ms: 2_000 },
    ]);
  });

  it("parses an ok body with pack_version, null refusal, and no runs", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        runs: [
          {
            venue: "kraken",
            pair: "SUIUSD",
            pack_id: "trend-follow",
            pack_version: "3",
            first_ts_ms: 5,
            last_ts_ms: 6,
            ticks_total: 1,
            last_refusal_code: null,
            mode: "paper",
            status: "active",
            summary: "1 tick, 0 fills, no refusal, active",
            recent_fills: [],
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const history = await createHttpClient().listRuns();
    const run = history.runs[0];
    expect(run.pack_version).toBe("3");
    expect(run.last_refusal_code).toBeNull();
    expect(run.recent_fills).toEqual([]);
  });

  it("returns an empty runs list for the no-history body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", runs: [] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const history = await createHttpClient().listRuns();
    expect(history.runs).toEqual([]);
  });

  it("throws a PaperCommandResult-flavoured refusal error on a non-2xx body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        { schema_version: "1", code: "session_required", ok: false, message: "session required" },
        403,
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().listRuns()).rejects.toThrow(
      "paper history refused: session_required",
    );
  });

  it("falls back to the refusal message when no code is present", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ detail: "session required" }, 403),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().listRuns()).rejects.toThrow(/403/);
  });

  it("falls back to the bare status when the error body is not JSON", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("not json");
      },
    } as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().listRuns()).rejects.toThrow(
      "paper history refused: 500",
    );
  });

  it("throws when the network request fails", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("fetch failed"));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().listRuns()).rejects.toThrow("fetch failed");
  });

  it("createLastRunsHttpClient exposes listRuns", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", runs: [] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = createLastRunsHttpClient();
    expect(typeof client.listRuns).toBe("function");
    const history = await client.listRuns();
    expect(history.runs).toEqual([]);
  });
});