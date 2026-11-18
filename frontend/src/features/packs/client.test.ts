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

describe("packs client redeemActivation", () => {
  it("POSTs /api/v1/activation/redeem with credentials, CSRF, and key body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        status: "paid",
        message: "license verified",
        catalog_downloaded: true,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const csrfMock = vi
      .spyOn(await import("../../session"), "getCsrf")
      .mockReturnValue("csrf-redeem-1");
    try {
      const result = await createHttpClient().redeemActivation("FAKE-KEY");
      expect(result).toEqual({
        schema_version: "1",
        status: "paid",
        message: "license verified",
        catalog_downloaded: true,
      });
      expect(fetchMock).toHaveBeenCalledOnce();
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/v1/activation/redeem");
      expect(init.method).toBe("POST");
      expect(init.credentials).toBe("include");
      expect((init.headers as Record<string, string>)["X-Krellbot-CSRF"]).toBe(
        "csrf-redeem-1",
      );
      expect((init.headers as Record<string, string>)["Content-Type"]).toBe(
        "application/json",
      );
      expect(JSON.parse(String(init.body))).toEqual({ key: "FAKE-KEY" });
    } finally {
      csrfMock.mockRestore();
    }
  });

  it("adapts grace and dead outcomes without inventing success", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          schema_version: "1",
          status: "grace",
          message: "license in grace period",
          catalog_downloaded: true,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          schema_version: "1",
          status: "dead",
          message: "license not accepted",
          catalog_downloaded: false,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const client = createHttpClient();
    expect(await client.redeemActivation("a")).toEqual({
      schema_version: "1",
      status: "grace",
      message: "license in grace period",
      catalog_downloaded: true,
    });
    expect(await client.redeemActivation("b")).toEqual({
      schema_version: "1",
      status: "dead",
      message: "license not accepted",
      catalog_downloaded: false,
    });
  });

  it.each([403, 500])(
    "throws PackLibraryHttpError carrying status %s on non-2xx",
    async (status) => {
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, status));
      vi.stubGlobal("fetch", fetchMock);
      const promise = createHttpClient().redeemActivation("k");
      await expect(promise).rejects.toBeInstanceOf(PackLibraryHttpError);
      await promise.catch((err: unknown) => {
        expect((err as PackLibraryHttpError).status).toBe(status);
        expect((err as Error).message).toContain(String(status));
        expect((err as Error).message).not.toContain("k");
      });
    },
  );
});

describe("packs client startCheckout", () => {
  it("POSTs /api/v1/checkout/start with credentials, CSRF, and sku body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        status: "paid",
        message: "checkout paid",
        sku: "paid-launch-dca",
        entitlements: ["paid-launch-dca"],
        session_id: "cs_fake_paid-launch-dca",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const csrfMock = vi
      .spyOn(await import("../../session"), "getCsrf")
      .mockReturnValue("csrf-checkout-1");
    try {
      const result = await createHttpClient().startCheckout("paid-launch-dca");
      expect(result).toEqual({
        schema_version: "1",
        status: "paid",
        message: "checkout paid",
        sku: "paid-launch-dca",
        entitlements: ["paid-launch-dca"],
        session_id: "cs_fake_paid-launch-dca",
      });
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/v1/checkout/start");
      expect(init.method).toBe("POST");
      expect(init.credentials).toBe("include");
      expect((init.headers as Record<string, string>)["X-Krellbot-CSRF"]).toBe(
        "csrf-checkout-1",
      );
      expect(JSON.parse(String(init.body))).toEqual({ sku: "paid-launch-dca" });
    } finally {
      csrfMock.mockRestore();
    }
  });

  it("adapts failed checkout without inventing entitlements", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        status: "failed",
        message: "checkout refused",
        sku: "paid-launch-dca",
        entitlements: [],
        session_id: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    expect(await createHttpClient().startCheckout("paid-launch-dca")).toEqual({
      schema_version: "1",
      status: "failed",
      message: "checkout refused",
      sku: "paid-launch-dca",
      entitlements: [],
      session_id: null,
    });
  });
});

describe("packs client requestRefund", () => {
  it("POSTs /api/v1/checkout/refund with credentials, CSRF, and sku body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        status: "refunded",
        message: "refund completed",
        sku: "paid-launch-dca",
        entitlements: [],
        refund_id: "re_fake_paid-launch-dca",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const csrfMock = vi
      .spyOn(await import("../../session"), "getCsrf")
      .mockReturnValue("csrf-refund-1");
    try {
      const result = await createHttpClient().requestRefund("paid-launch-dca");
      expect(result).toEqual({
        schema_version: "1",
        status: "refunded",
        message: "refund completed",
        sku: "paid-launch-dca",
        entitlements: [],
        refund_id: "re_fake_paid-launch-dca",
      });
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/v1/checkout/refund");
      expect(init.method).toBe("POST");
      expect(init.credentials).toBe("include");
      expect((init.headers as Record<string, string>)["X-Krellbot-CSRF"]).toBe(
        "csrf-refund-1",
      );
      expect(JSON.parse(String(init.body))).toEqual({ sku: "paid-launch-dca" });
    } finally {
      csrfMock.mockRestore();
    }
  });

  it("adapts failed refund without inventing a revoke", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        status: "failed",
        message: "refund refused",
        sku: "paid-launch-dca",
        entitlements: ["paid-launch-dca"],
        refund_id: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    expect(await createHttpClient().requestRefund("paid-launch-dca")).toEqual({
      schema_version: "1",
      status: "failed",
      message: "refund refused",
      sku: "paid-launch-dca",
      entitlements: ["paid-launch-dca"],
      refund_id: null,
    });
  });
});

describe("packs client telemetry consent", () => {
  it("GETs /api/v1/telemetry and adapts default-off consent", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        enabled: false,
        default_off: true,
        funnel_events: ["view", "checkout_start"],
        disclosure: "Telemetry is opt-in and off by default.",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const csrfMock = vi
      .spyOn(await import("../../session"), "getCsrf")
      .mockReturnValue("csrf-telemetry-1");
    try {
      const result = await createHttpClient().getTelemetryConsent();
      expect(result.enabled).toBe(false);
      expect(result.default_off).toBe(true);
      expect(result.funnel_events).toEqual(["view", "checkout_start"]);
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/v1/telemetry");
      expect(init.method).toBe("GET");
      expect(init.credentials).toBe("include");
    } finally {
      csrfMock.mockRestore();
    }
  });

  it("PUTs /api/v1/telemetry enabled=true for explicit opt-in", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        enabled: true,
        default_off: true,
        funnel_events: ["view"],
        disclosure: "Telemetry is opt-in and off by default.",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const csrfMock = vi
      .spyOn(await import("../../session"), "getCsrf")
      .mockReturnValue("csrf-telemetry-2");
    try {
      const result = await createHttpClient().setTelemetryConsent(true);
      expect(result.enabled).toBe(true);
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/v1/telemetry");
      expect(init.method).toBe("PUT");
      expect(JSON.parse(String(init.body))).toEqual({ enabled: true });
    } finally {
      csrfMock.mockRestore();
    }
  });
});

describe("createPacksHttpClient", () => {
  it("exposes the same read surface the shell mounts without dead rollback", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    const client = createPacksHttpClient();
    expect(typeof client.listInstalled).toBe("function");
    expect("rollback" in client).toBe(false);
    expect(typeof client.redeemActivation).toBe("function");
    expect(typeof client.listCatalogue).toBe("function");
    expect(typeof client.install).toBe("function");
    expect(typeof client.startCheckout).toBe("function");
    expect(typeof client.requestRefund).toBe("function");
    expect(typeof client.listCommunityIndex).toBe("function");
    expect(typeof client.installCommunity).toBe("function");
    expect(typeof client.getTelemetryConsent).toBe("function");
    expect(typeof client.setTelemetryConsent).toBe("function");
    expect(typeof client.openCommunityPack).toBe("function");
    expect(await client.listInstalled()).toEqual([]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/packs",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );
    expect(fetchMock.mock.calls.every(([url]) => url !== "/api/v1/packs/rollback")).toBe(
      true,
    );
  });
});

describe("packs client listCommunityIndex", () => {
  it("GETs /api/v1/community/index and adapts closed rows with fetch time", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        index_url:
          "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/index.json",
        packs: [
          {
            id: "trend-follow",
            url: "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/packs/trend-follow.json",
            author: "community-example",
            label: "Trend follow",
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const doc = await createHttpClient().listCommunityIndex();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/community/index",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );
    expect(doc.index_url).toContain("krellbot-community-packs");
    expect(doc.packs).toEqual([
      {
        id: "trend-follow",
        url: "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/packs/trend-follow.json",
        author: "community-example",
        label: "Trend follow",
      },
    ]);
    expect(typeof doc.fetched_at).toBe("string");
    expect(doc.fetched_at).not.toBeNull();
  });

  it("throws PackLibraryHttpError on community index refusal", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, 502));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().listCommunityIndex()).rejects.toBeInstanceOf(
      PackLibraryHttpError,
    );
  });
});

describe("packs client installCommunity", () => {
  it("POSTs /api/v1/community/install and returns id/version/author/path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        ok: true,
        pack: {
          id: "trend-follow",
          version: "1.0.0",
          label: "Trend follow",
          author: "community-example",
          origin: "Community pack. Unverified. No guarantee.",
        },
        path: "packs/community/trend-follow.json",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const csrfMock = vi
      .spyOn(await import("../../session"), "getCsrf")
      .mockReturnValue("csrf-community");
    try {
      const result = await createHttpClient().installCommunity("trend-follow");
      expect(result.ok).toBe(true);
      expect(result.pack?.id).toBe("trend-follow");
      expect(result.pack?.author).toBe("community-example");
      expect(result.path).toBe("packs/community/trend-follow.json");
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/v1/community/install");
      expect(init.method).toBe("POST");
      expect(JSON.parse(String(init.body))).toEqual({ pack_id: "trend-follow" });
      expect((init.headers as Record<string, string>)["X-Krellbot-CSRF"]).toBe(
        "csrf-community",
      );
    } finally {
      csrfMock.mockRestore();
    }
  });

  it("returns foreign_url without throwing", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          schema_version: "1",
          ok: false,
          code: "foreign_url",
          message: "community pack url is not allow-listed",
        },
        403,
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await createHttpClient().installCommunity("trend-follow");
    expect(result).toEqual({
      ok: false,
      code: "foreign_url",
      message: "community pack url is not allow-listed",
    });
  });
});

describe("packs client omits rollback until a real route exists", () => {
  it("never POSTs /api/v1/packs/rollback from the HTTP client", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        ok: true,
        pack: {
          bucket: "download_pending",
          pack_id: "free-dual-ma",
          version: "1.0.0",
          permissions: [],
          rollback_ref: null,
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = createHttpClient();
    await client.install("free-dual-ma");
    await client.listInstalled();
    expect("rollback" in client).toBe(false);
    expect(
      fetchMock.mock.calls.map(([url]) => url as string),
    ).not.toContain("/api/v1/packs/rollback");
  });
});

describe("packs client listCatalogue", () => {
  it("GETs /api/v1/catalogue with credentials and CSRF", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        catalogue_version: "1",
        packs: [
          { id: "free-dual-ma", tier: "free", version: "1.0.0", permissions: [] },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const doc = await createHttpClient().listCatalogue();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/catalogue",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );
    expect(doc.catalogue_version).toBe("1");
    expect(doc.packs).toEqual([
      {
        id: "free-dual-ma",
        tier: "free",
        label: null,
        description: null,
        version: "1.0.0",
        permissions: [],
      },
    ]);
  });

  it("throws PackLibraryHttpError on catalogue refusal", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, 502));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createHttpClient().listCatalogue()).rejects.toBeInstanceOf(
      PackLibraryHttpError,
    );
  });
});

describe("packs client install", () => {
  it("POSTs /api/v1/packs/install with CSRF and returns the pack row", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        ok: true,
        pack: {
          bucket: "download_pending",
          pack_id: "free-dual-ma",
          version: "1.0.0",
          permissions: [],
          rollback_ref: null,
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const csrfMock = vi
      .spyOn(await import("../../session"), "getCsrf")
      .mockReturnValue("csrf-install");
    try {
      const result = await createHttpClient().install("free-dual-ma");
      expect(result.ok).toBe(true);
      expect(result.pack?.bucket).toBe("download_pending");
      expect(result.pack?.version).toBe("1.0.0");
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/v1/packs/install");
      expect(init.method).toBe("POST");
      expect(init.credentials).toBe("include");
      expect((init.headers as Record<string, string>)["X-Krellbot-CSRF"]).toBe(
        "csrf-install",
      );
      expect(JSON.parse(String(init.body))).toEqual({
        schema_version: "1",
        command: "packs.install",
        pack_id: "free-dual-ma",
      });
    } finally {
      csrfMock.mockRestore();
    }
  });

  it("returns activation_required without throwing on paid refusal", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          schema_version: "1",
          ok: false,
          code: "activation_required",
          message: "paid pack requires activation",
        },
        403,
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await createHttpClient().install("paid-triple-stack");
    expect(result).toEqual({
      ok: false,
      code: "activation_required",
      message: "paid pack requires activation",
    });
  });
});
