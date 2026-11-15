import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearCsrf,
  getCsrf,
  issueReconnectToken,
  redeemBootstrap,
  redeemReconnectToken,
} from "./session";

afterEach(() => {
  clearCsrf();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("issueReconnectToken", () => {
  beforeEach(async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ csrf_token: "csrf-primary" })));
    await redeemBootstrap("boot");
  });

  it("POSTs with CSRF and returns token plus QR payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      json({
        token: "reconnect-abc",
        expires_at: 1700000300,
        expires_in: 300,
        redeem_path: "/?reconnect=reconnect-abc",
        qr_payload: "http://127.0.0.1:8080/?reconnect=reconnect-abc",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const offer = await issueReconnectToken();
    expect(offer).toEqual({
      token: "reconnect-abc",
      expiresAt: 1700000300,
      expiresIn: 300,
      redeemPath: "/?reconnect=reconnect-abc",
      qrPayload: "http://127.0.0.1:8080/?reconnect=reconnect-abc",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/session/reconnect/issue",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
      }),
    );
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("X-Krellbot-CSRF")).toBe("csrf-primary");
  });
});

describe("redeemReconnectToken", () => {
  it("POSTs the token and stores csrf_token in module memory", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ csrf_token: "csrf-second" }));
    vi.stubGlobal("fetch", fetchMock);

    await redeemReconnectToken("reconnect-abc");
    expect(getCsrf()).toBe("csrf-second");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/session/reconnect/redeem",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({ token: "reconnect-abc" }),
      }),
    );
  });

  it("does not write sessionStorage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ csrf_token: "csrf-x" })));
    await redeemReconnectToken("tok");
    expect(setItem).not.toHaveBeenCalled();
  });
});
