import { afterEach, describe, expect, it, vi } from "vitest";
import { createLibraryClient } from "./libraryClient";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

describe("libraryClient — listOwned", () => {
  it("GETs /api/v1/strategies/drafts and returns the owned summaries", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, {
        schema_version: "1",
        drafts: [
          {
            revision_id: "rev-child",
            strategy_id: "trend-follow",
            parent_revision_id: "rev-parent",
            state: "draft",
            runnable: false,
            created_at: "2026-10-07T10:00:00Z",
            id: "trend-follow",
            label: "Edited",
            pair: "SUIUSD",
            timeframe: "1h",
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = createLibraryClient();
    const rows = await client.listOwned();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toBe("/api/v1/strategies/drafts");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect(rows).toEqual([
      {
        revision_id: "rev-child",
        strategy_id: "trend-follow",
        parent_revision_id: "rev-parent",
        state: "draft",
        runnable: false,
        created_at: "2026-10-07T10:00:00Z",
        id: "trend-follow",
        label: "Edited",
        pair: "SUIUSD",
        timeframe: "1h",
      },
    ]);
  });

  it("adapts missing optional fields instead of fabricating data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(200, {
          schema_version: "1",
          drafts: [
            {
              revision_id: "rev-1",
              strategy_id: "legacy",
              state: "draft",
            },
          ],
        }),
      ),
    );
    const client = createLibraryClient();
    const rows = await client.listOwned();
    expect(rows).toEqual([
      {
        revision_id: "rev-1",
        strategy_id: "legacy",
        parent_revision_id: null,
        state: "draft",
        runnable: false,
        created_at: "",
        id: "",
        label: "",
        pair: "",
        timeframe: "",
      },
    ]);
  });

  it("returns [] when the drafts array is absent", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(200, { schema_version: "1" })),
    );
    const client = createLibraryClient();
    expect(await client.listOwned()).toEqual([]);
  });

  it("throws the HTTP status when the request fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(403, { detail: "session required" })),
    );
    const client = createLibraryClient();
    await expect(client.listOwned()).rejects.toThrow(
      "library list failed: 403",
    );
  });
});

describe("libraryClient — getJson", () => {
  it("GETs the canonical revision and returns summary + canonical bytes", async () => {
    const pack = { id: "trend-follow", label: "Trend follow" };
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, {
        schema_version: "1",
        revision_id: "rev-1",
        state: "validated",
        runnable: true,
        pack,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = createLibraryClient();
    const loaded = await client.getJson("rev-1");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toBe("/api/v1/strategies/drafts/rev-1");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect(loaded.revision_id).toBe("rev-1");
    expect(loaded.state).toBe("validated");
    expect(loaded.bytes).toBe(JSON.stringify(pack));
  });

  it("maps an unknown draft to a clear error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(404, { code: "draft_not_found" }),
      ),
    );
    const client = createLibraryClient();
    await expect(client.getJson("missing")).rejects.toThrow(
      "library open failed: 404",
    );
  });
});
