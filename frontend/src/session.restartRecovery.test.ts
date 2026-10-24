import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCsrf, getCsrf, recoverPaperStatusSession, redeemBootstrap } from "./session";

const origin = "http://127.0.0.1:8765";
const tokenMeta = '<meta name="krellbot-bootstrap" content="fresh-one-time">';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function shell(html = tokenMeta, options: { status?: number; type?: string; url?: string; redirected?: boolean } = {}): Response {
  const response = new Response(html, {
    status: options.status ?? 200,
    headers: { "Content-Type": options.type ?? "text/html; charset=utf-8" },
  });
  Object.defineProperties(response, {
    url: { value: options.url ?? `${origin}/` },
    redirected: { value: options.redirected ?? false },
  });
  return response;
}

beforeEach(() => {
  clearCsrf();
  vi.stubGlobal("location", new URL(`${origin}/`));
});

afterEach(() => {
  clearCsrf();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function seedStaleCsrf(): Promise<void> {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ csrf_token: "invalid-old-csrf" })));
  await redeemBootstrap("initial-token");
}

describe("Paper status session recovery after backend restart", () => {
  it("first recovers a still-valid cookie without fetching shell or redeeming bootstrap", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ csrf_token: "existing-session-csrf" }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(recoverPaperStatusSession()).resolves.toBe(true);
    expect(getCsrf()).toBe("existing-session-csrf");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/session/csrf", expect.objectContaining({ method: "GET", credentials: "include" }));
  });

  it("reads fresh inert HTML and redeems its sole token without storage or document replacement", async () => {
    await seedStaleCsrf();
    const html = `${tokenMeta}<script>window.recoveryScriptRan=true</script>`;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({}, 403))
      .mockResolvedValueOnce(shell(html))
      .mockImplementationOnce(async () => {
        expect(getCsrf()).toBe("");
        return json({ csrf_token: "fresh-csrf" });
      });
    vi.stubGlobal("fetch", fetchMock);
    const storage = vi.spyOn(Storage.prototype, "setItem");
    const documentBefore = document.documentElement;
    const parse = vi.spyOn(DOMParser.prototype, "parseFromString");
    await expect(recoverPaperStatusSession()).resolves.toBe(true);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/session/csrf", "/", "/api/v1/session/bootstrap",
    ]);
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: "GET", credentials: "include", cache: "no-store", redirect: "error" });
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: "POST", credentials: "include", body: JSON.stringify({ token: "fresh-one-time" }) });
    expect(parse).toHaveBeenCalledWith(html, "text/html");
    expect(getCsrf()).toBe("fresh-csrf");
    expect(storage).not.toHaveBeenCalled();
    expect(document.documentElement).toBe(documentBefore);
    expect(document.querySelector('meta[name="krellbot-bootstrap"]')).toBeNull();
    expect((window as unknown as Record<string, unknown>).recoveryScriptRan).toBeUndefined();
  });

  it("shares one pending recovery including a single one-time redemption, then releases the flight", async () => {
    let resolveShell!: (value: Response) => void;
    const pendingShell = new Promise<Response>((resolve) => { resolveShell = resolve; });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({}, 403))
      .mockReturnValueOnce(pendingShell)
      .mockResolvedValueOnce(json({ csrf_token: "fresh-csrf" }))
      .mockResolvedValueOnce(json({ csrf_token: "fresh-csrf" }));
    vi.stubGlobal("fetch", fetchMock);
    const a = recoverPaperStatusSession();
    const b = recoverPaperStatusSession();
    resolveShell(shell());
    expect(await Promise.all([a, b])).toEqual([true, true]);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/v1/session/bootstrap")).toHaveLength(1);
    await expect(recoverPaperStatusSession()).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it.each([
    ["absent token", "<html><head></head></html>", {}],
    ["empty token", '<meta name="krellbot-bootstrap" content="">', {}],
    ["whitespace token", '<meta name="krellbot-bootstrap" content="  ">', {}],
    ["missing content", '<meta name="krellbot-bootstrap">', {}],
    ["duplicate token", tokenMeta + tokenMeta, {}],
    ["non-HTML", tokenMeta, { type: "application/json" }],
    ["lookalike MIME", tokenMeta, { type: "text/html-malicious" }],
    ["server failure", tokenMeta, { status: 500 }],
    ["redirect status", tokenMeta, { status: 302 }],
    ["followed redirect", tokenMeta, { redirected: true }],
    ["external origin", tokenMeta, { url: "http://example.invalid/" }],
    ["different loopback host", tokenMeta, { url: "http://localhost:8765/" }],
    ["different port", tokenMeta, { url: "http://127.0.0.1:8766/" }],
    ["missing response URL", tokenMeta, { url: "" }],
  ])("fails closed for %s without redeeming or retaining stale CSRF", async (_name, html, options) => {
    await seedStaleCsrf();
    const fetchMock = vi.fn().mockResolvedValueOnce(json({}, 403)).mockResolvedValueOnce(shell(html, options));
    vi.stubGlobal("fetch", fetchMock);
    await expect(recoverPaperStatusSession()).resolves.toBe(false);
    expect(getCsrf()).toBe("");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each(["http://example.invalid:8765/", "http://127.0.0.1.example.invalid:8765/", "https://127.0.0.1:8765/", "file:///tmp/shell.html", "http://[::1]:8765/"])("refuses unsupported origin %s before network access", async (url) => {
    await seedStaleCsrf();
    vi.stubGlobal("location", new URL(url));
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(recoverPaperStatusSession()).resolves.toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(getCsrf()).toBe("");
  });

  it.each([401, 404, 500])("does not bootstrap after CSRF endpoint returns %s", async (status) => {
    await seedStaleCsrf();
    const fetchMock = vi.fn().mockResolvedValue(json({}, status));
    vi.stubGlobal("fetch", fetchMock);
    await expect(recoverPaperStatusSession()).resolves.toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(getCsrf()).toBe("");
  });

  it.each([{}, { csrf_token: "" }, { csrf_token: 123 }])("rejects malformed recovered CSRF %j without bootstrap", async (body) => {
    const fetchMock = vi.fn().mockResolvedValue(json(body));
    vi.stubGlobal("fetch", fetchMock);
    await expect(recoverPaperStatusSession()).resolves.toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(getCsrf()).toBe("");
  });

  it.each(["wrong token", "token already redeemed"])("does not replay bootstrap when backend refuses %s", async (detail) => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({}, 403))
      .mockResolvedValueOnce(shell())
      .mockResolvedValueOnce(json({ detail }, 403));
    vi.stubGlobal("fetch", fetchMock);
    await expect(recoverPaperStatusSession()).resolves.toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(getCsrf()).toBe("");
  });

  it.each([0, 1, 2])("fails honestly on network error at recovery step %s, with no automatic repeat", async (step) => {
    await seedStaleCsrf();
    const fetchMock = vi.fn();
    if (step > 0) fetchMock.mockResolvedValueOnce(json({}, 403));
    if (step > 1) fetchMock.mockResolvedValueOnce(shell());
    fetchMock.mockRejectedValueOnce(new TypeError("backend unavailable"));
    vi.stubGlobal("fetch", fetchMock);
    await expect(recoverPaperStatusSession()).resolves.toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(step + 1);
    expect(getCsrf()).toBe("");
  });

  it("rejects invalid bootstrap JSON and releases a failed recovery for a later explicit attempt", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({}, 403))
      .mockResolvedValueOnce(shell())
      .mockResolvedValueOnce(json({}))
      .mockResolvedValueOnce(json({ csrf_token: "later-csrf" }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(recoverPaperStatusSession()).resolves.toBe(false);
    expect(getCsrf()).toBe("");
    await expect(recoverPaperStatusSession()).resolves.toBe(true);
    expect(getCsrf()).toBe("later-csrf");
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });
});
