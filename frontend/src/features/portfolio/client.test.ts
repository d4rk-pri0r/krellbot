import { afterEach, describe, expect, it, vi } from "vitest";
import { createPortfolioHttpClient } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("createPortfolioHttpClient getHistory", () => {
  it("GETs /api/v1/portfolio/history with credentials and CSRF", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        schema_version: "1",
        equity: [{ ts_ms: 1000, value: "1000" }],
        deployments: [
          {
            venue: "kraken",
            pair: "SUIUSD",
            pack_id: "trend",
            mode: "paper",
            status: "active",
            starting_cash: "1000",
            fills_total: 0,
            first_ts_ms: 0,
            last_ts_ms: 0,
            last_pnl: null,
            pnl: [],
          },
        ],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const history = await createPortfolioHttpClient().getHistory();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/portfolio/history");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Krellbot-CSRF"]).toBeDefined();
    expect(history.equity).toEqual([{ ts_ms: 1000, value: "1000" }]);
    expect(history.deployments).toHaveLength(1);
    expect(history.deployments[0]?.pair).toBe("SUIUSD");
  });

  it("refuses a body missing equity or deployments arrays", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ schema_version: "1" }),
      }),
    );
    await expect(createPortfolioHttpClient().getHistory()).rejects.toThrow(
      /missing series arrays/,
    );
  });

  it("throws on non-OK responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        json: async () => ({}),
      }),
    );
    await expect(createPortfolioHttpClient().getHistory()).rejects.toThrow(
      /403/,
    );
  });
});
