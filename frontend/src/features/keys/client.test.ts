import { afterEach, describe, expect, it, vi } from "vitest";
import { createHttpClient, KEYS_VENUE } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("keys HTTP client", () => {
  it("GETs /api/v1/keys/kraken with credentials and CSRF", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        venue: "kraken",
        present: false,
        corrupt: false,
        message: "no key stored",
        backend_label: null,
        balances: null,
        balances_available: false,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const csrf = vi.spyOn(await import("../../session"), "getCsrf").mockReturnValue("csrf-keys");

    const status = await createHttpClient().getStatus();
    expect(status.present).toBe(false);
    expect(status.message).toBe("no key stored");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/api/v1/keys/${KEYS_VENUE}`);
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect((init.headers as Record<string, string>)["X-Krellbot-CSRF"]).toBe("csrf-keys");
    csrf.mockRestore();
  });

  it("GETs /api/v1/keys/coinbase when the Coinbase venue is requested", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        venue: "coinbase",
        present: false,
        corrupt: false,
        message: "no key stored",
        backend_label: null,
        balances: null,
        balances_available: false,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const status = await createHttpClient().getStatus("coinbase");
    expect(status.venue).toBe("coinbase");
    expect(status.present).toBe(false);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/keys/coinbase");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
  });

  it("POSTs probe-and-store without echoing secrets in thrown errors", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        venue: "kraken",
        status: "stored",
        ok: true,
        message: "stored in native OS keychain",
        effect: "changed",
        backend_label: "FakeKeyring",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpClient().probeAndStore("public-test-key", "private-test-secret");
    expect(result.ok).toBe(true);
    expect(result.status).toBe("stored");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/keys/kraken");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      key: "public-test-key",
      secret: "private-test-secret",
    });
    expect((init.headers as Record<string, string>)["X-Krellbot-CSRF"]).toBeDefined();
  });

  it("DELETEs the stored key pair", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        venue: "kraken",
        status: "removed",
        ok: true,
        message: "removed from keychain",
        effect: "changed",
        backend_label: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpClient().remove();
    expect(result.ok).toBe(true);
    expect(result.status).toBe("removed");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/keys/kraken");
    expect(init.method).toBe("DELETE");
  });

  it("surfaces HTTP refusals as honest errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "csrf required" }, 403)),
    );
    await expect(createHttpClient().getStatus()).rejects.toThrow(/csrf required/);
  });
});
