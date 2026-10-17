import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createHttpClient,
  createPacksHttpClient,
  PackLibraryHttpError,
} from "./client";

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

describe("packs client listInstalled", () => {
  it("GETs /api/v1/packs with credentials: include and the CSRF header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    await createHttpClient().listInstalled();
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/packs");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect((init.headers as Record<string, string>)["X-Krellbot-CSRF"]).toBe("");
  });

  it("parses an ok body into PackRow[] with the closed fields", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse([
        {
          bucket: "deployed",
          pack_id: "alpha",
          version: "2.0.0",
          permissions: ["trade"],
          rollback_ref: {
            pack_id: "alpha",
            prior_revision_id: "0".repeat(64),
          },
        },
        {
          bucket: "installed",
          pack_id: "bravo",
          version: null,
          permissions: [],
          rollback_ref: null,
        },
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);
    const rows = await createHttpClient().listInstalled();
    expect(rows).toEqual([
      {
        bucket: "deployed",
        pack_id: "alpha",
        version: "2.0.0",
        permissions: ["trade"],
        rollback_ref: {
          pack_id: "alpha",
          prior_revision_id: "0".repeat(64),
        },
      },
      {
        bucket: "installed",
        pack_id: "bravo",
        version: null,
        permissions: [],
        rollback_ref: null,
      },
    ]);
  });

  it("returns [] on an empty array body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    const rows = await createHttpClient().listInstalled();
    expect(rows).toEqual([]);
  });

  it("drops malformed entries instead of inventing rows", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse([
        { bucket: "installed", pack_id: "alpha", version: "1.0.0", permissions: [], rollback_ref: null },
        "not-an-object",
        null,
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);
    const rows = await createHttpClient().listInstalled();
    expect(rows.map((r) => r.pack_id)).toEqual(["alpha"]);
  });

  it.each([403, 404, 500])(
    "throws a PackLibraryHttpError carrying status %s on non-2xx",
    async (status) => {
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, status));
      vi.stubGlobal("fetch", fetchMock);
      const promise = createHttpClient().listInstalled();
      await expect(promise).rejects.toBeInstanceOf(PackLibraryHttpError);
      await promise.catch((err: unknown) => {
        expect((err as PackLibraryHttpError).status).toBe(status);
        expect((err as Error).message).toContain(String(status));
      });
    },
  );

  it("sends the recovered CSRF token when the session module holds one", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    const session = await import("../../session");
    const redeemed = session as unknown as {
      redeemBootstrap: (token: string) => Promise<void>;
    };
    const csrfMock = vi
      .spyOn(await import("../../session"), "getCsrf")
      .mockReturnValue("csrf-token-1");
    try {
      void redeemed;
      await createHttpClient().listInstalled();
      const [_url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect((init.headers as Record<string, string>)["X-Krellbot-CSRF"]).toBe(
        "csrf-token-1",
      );
    } finally {
      csrfMock.mockRestore();
    }
  });
});

describe("createPacksHttpClient", () => {
  it("exposes the same read surface the shell mounts", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    const client = createPacksHttpClient();
    expect(typeof client.listInstalled).toBe("function");
    expect(typeof client.rollback).toBe("function");
    expect(await client.listInstalled()).toEqual([]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/packs",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );
  });
});
