/**
 * Wizard and shell share one bootstrap redeem so paper setup is not
 * refused and the one-time token is not spent twice.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { ensureLoopbackSession } from "./loopbackSession";

afterEach(() => {
  document.head.innerHTML = "";
  vi.unstubAllGlobals();
});

describe("ensureLoopbackSession redeems one bootstrap token", () => {
  it("shares one redeem across overlapping wizard and shell callers", async () => {
    document.head.innerHTML =
      '<meta name="krellbot-bootstrap" content="tok-wizard">';
    let release: (value: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const fetchMock = vi.fn(() => pending);
    vi.stubGlobal("fetch", fetchMock);

    const first = ensureLoopbackSession();
    const second = ensureLoopbackSession();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(document.querySelector('meta[name="krellbot-bootstrap"]')).toBeNull();

    release(
      new Response(JSON.stringify({ csrf_token: "csrf-wizard" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await expect(first).resolves.toBe(true);
    await expect(second).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/session/bootstrap");
    expect(JSON.parse(String(init.body))).toEqual({ token: "tok-wizard" });
  });

  it("recovers CSRF after the bootstrap meta is already spent", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ csrf_token: "csrf-again" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(ensureLoopbackSession()).resolves.toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/session/csrf");
    expect(init.method).toBe("GET");
  });
});
