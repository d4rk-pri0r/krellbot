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
  } as unknown as Response;
}

describe("createHttpClient arm", () => {
  it("posts paper.arm with the command payload, not args", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await createHttpClient().arm("rev-1", "kraken", "1000");

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/commands");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      schema_version: "1",
      command: "paper.arm",
      payload: {
        revision_id: "rev-1",
        venue: "kraken",
        paper_balance: "1000",
      },
    });
  });
});

describe("createHttpClient edit — outcome pass-through", () => {
  it("adapt keeps the three contract outcome literals and drops others", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        revision_id: "rev-out-1",
        parent_revision_id: "rev-parent",
        state: "draft",
        pack: { id: "x" },
        errors: [],
        outcome: "created",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const summary = await createHttpClient().edit("rev-parent", { id: "x" });
    expect((summary as { outcome?: string }).outcome).toBe("created");

    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        revision_id: "rev-out-1",
        parent_revision_id: "rev-parent",
        state: "validated",
        pack: { id: "x" },
        errors: [],
        outcome: "unchanged",
      }),
    );
    const unchanged = await createHttpClient().edit("rev-parent", { id: "x" });
    expect((unchanged as { outcome?: string }).outcome).toBe("unchanged");

    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        revision_id: "rev-other",
        parent_revision_id: null,
        state: "validated",
        pack: { id: "x" },
        errors: [],
        outcome: "existing",
      }),
    );
    const existing = await createHttpClient().edit("rev-parent", { id: "x" });
    expect((existing as { outcome?: string }).outcome).toBe("existing");

    // The adapt() contract drops an outcome literal it does not know.
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        revision_id: "rev-strange",
        state: "draft",
        pack: { id: "x" },
        errors: [],
        outcome: "weird",
      }),
    );
    const stray = await createHttpClient().edit("rev-parent", { id: "x" });
    expect((stray as { outcome?: unknown }).outcome).toBeUndefined();
  });

  it("a 409 from edit throws an Error whose message contains strategy_id_mismatch", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          schema_version: "1",
          code: "strategy_id_mismatch",
          message: "pack id does not match parent strategy",
        },
        409,
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      createHttpClient().edit("rev-parent", { id: "x" }),
    ).rejects.toThrow(/strategy_id_mismatch/);
  });
});
