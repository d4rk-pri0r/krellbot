import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrf, getCsrf, recoverCsrf, redeemBootstrap } from "./session";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

beforeEach(() => {
  clearCsrf();
});

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("redeemBootstrap", () => {
  it("posts {token} to /api/v1/session/bootstrap and stores csrf_token in module memory", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", csrf_token: "csrf-abc" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await redeemBootstrap("the-token");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/session/bootstrap");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(JSON.parse(String(init.body))).toEqual({ token: "the-token" });

    expect(getCsrf()).toBe("csrf-abc");
  });

  it("does not write to localStorage when redeeming", async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ csrf_token: "csrf-abc" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await redeemBootstrap("token-1");

    expect(setItemSpy).not.toHaveBeenCalled();
  });

  it("does not write to sessionStorage when redeeming", async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ csrf_token: "csrf-abc" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await redeemBootstrap("token-1");

    expect(setItemSpy).not.toHaveBeenCalled();
  });

  it("does not read a krellbot_csrf cookie", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ csrf_token: "csrf-abc" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    // Simulate a stale cookie set by a previous build.
    document.cookie = "krellbot_csrf=stale-from-cookie";

    await redeemBootstrap("token-1");

    const [_url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = (init.headers ?? {}) as Record<string, string>;
    const csrfHeader = headers["X-Krellbot-CSRF"] ?? "";
    expect(csrfHeader).not.toBe("stale-from-cookie");
    expect(csrfHeader).toBe("");
  });

  it("throws and leaves csrf empty when the server responds non-2xx", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, 403));
    vi.stubGlobal("fetch", fetchMock);

    await expect(redeemBootstrap("token-1")).rejects.toThrow(/403/);
    expect(getCsrf()).toBe("");
  });

  it("throws when the response body has no csrf_token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ schema_version: "1" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(redeemBootstrap("token-1")).rejects.toThrow(/csrf_token/);
    expect(getCsrf()).toBe("");
  });
});

describe("getCsrf", () => {
  it("returns the empty string before any bootstrap", () => {
    expect(getCsrf()).toBe("");
  });

  it("returns the stored value once bootstrap has succeeded", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ csrf_token: "csrf-xyz" }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await redeemBootstrap("token-2");
    expect(getCsrf()).toBe("csrf-xyz");
  });

  it("returns the empty string after clearCsrf", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ csrf_token: "csrf-xyz" }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await redeemBootstrap("token-3");
    clearCsrf();
    expect(getCsrf()).toBe("");
  });
});

describe("clearCsrf", () => {
  it("does not throw when called before any bootstrap", () => {
    expect(() => clearCsrf()).not.toThrow();
  });
});

describe("recoverCsrf", () => {
  it("GETs /api/v1/session/csrf with credentials and stores the token on 200", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1", csrf_token: "csrf-recovered" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const ok = await recoverCsrf();

    expect(ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/session/csrf");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect(getCsrf()).toBe("csrf-recovered");
  });

  it("returns false on 403 without throwing and leaves getCsrf() empty", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, 403));
    vi.stubGlobal("fetch", fetchMock);

    await expect(recoverCsrf()).resolves.toBe(false);
    expect(getCsrf()).toBe("");
  });

  it("returns false when the body has no csrf_token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ schema_version: "1" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(recoverCsrf()).resolves.toBe(false);
    expect(getCsrf()).toBe("");
  });

  it("resolves false (never rejects) when fetch itself rejects", async () => {
    // G3: jsdom fetch throws "Failed to parse URL" for relative URLs.
    const fetchMock = vi
      .fn()
      .mockRejectedValue(new TypeError("Failed to parse URL"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(recoverCsrf()).resolves.toBe(false);
    expect(getCsrf()).toBe("");
  });

  it("resolves false when a 200 response carries a non-JSON body", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("<html>not json", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(recoverCsrf()).resolves.toBe(false);
    expect(getCsrf()).toBe("");
  });
});