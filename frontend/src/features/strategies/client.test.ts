import { afterEach, describe, expect, it, vi } from "vitest";
import { createHttpClient } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

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
