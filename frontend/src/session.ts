/**
 * Session bootstrap for the loopback API.
 *
 * The app server embeds a one-time bootstrap token into the served
 * shell as `<meta name="krellbot-bootstrap" content="...">`. The
 * shell reads that meta tag, calls `redeemBootstrap(token)`, and the
 * API returns a CSRF token that subsequent state-change requests
 * must echo in the `X-Krellbot-CSRF` header.
 *
 * The CSRF token lives in module memory for the lifetime of this
 * JavaScript realm. It is never written to `localStorage`, never
 * stored in a cookie, and never sent to a non-loopback origin. The
 * session cookie itself is HttpOnly and is sent automatically by the
 * browser; only the CSRF value crosses the JS / HTTP boundary here.
 */

let csrfToken: string | null = null;

export async function redeemBootstrap(token: string): Promise<void> {
  const response = await fetch("/api/v1/session/bootstrap", {
    method: "POST",
    credentials: "include",
    redirect: "error",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  if (!response.ok) {
    throw new Error(`bootstrap failed: ${response.status}`);
  }
  const body = (await response.json()) as { csrf_token?: unknown };
  if (typeof body.csrf_token !== "string" || body.csrf_token.length === 0) {
    throw new Error("bootstrap response missing csrf_token");
  }
  csrfToken = body.csrf_token;
}

export function getCsrf(): string {
  return csrfToken ?? "";
}

/**
 * Fixed total deadline bounding one existing-session CSRF recovery
 * read. The deadline spans the whole read — response headers AND the
 * JSON body — so a stalled local server can never wedge shell startup
 * forever, and a late answer can never install a token afterwards.
 */
const CSRF_RECOVERY_READ_DEADLINE_MS = 10000;

/**
 * Recover the CSRF token for an existing session after a reload.
 *
 * A page reload drops the module-memory token while the HttpOnly
 * session cookie survives. `GET /api/v1/session/csrf` re-reads the
 * token for that cookie. The read is bounded by a fixed 10000ms total
 * deadline: at the deadline this resolves `false` (never throws),
 * aborts its owned read, and never commits a token from a response
 * that arrives late — even if the transport ignores the AbortSignal.
 * Resolves `false` when the session is gone, the body carries no
 * token, or the request itself fails; any previously held token keeps
 * its current failure treatment (it is neither cleared nor replaced).
 */
export async function recoverCsrf(): Promise<boolean> {
  const controller = new AbortController();
  let expired = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let settleDeadline: (ok: boolean) => void = () => {};
  const deadline = new Promise<boolean>((resolve) => {
    settleDeadline = resolve;
  });
  timer = setTimeout(() => {
    timer = null;
    expired = true;
    controller.abort();
    settleDeadline(false);
  }, CSRF_RECOVERY_READ_DEADLINE_MS);
  const read = (async (): Promise<boolean> => {
    try {
      const response = await fetch("/api/v1/session/csrf", {
        method: "GET",
        credentials: "include",
        signal: controller.signal,
      });
      if (!response.ok) {
        return false;
      }
      const body = (await response.json()) as { csrf_token?: unknown };
      if (expired) {
        // The deadline already fired: never commit a late token, even
        // if this transport ignored the abort signal.
        return false;
      }
      if (typeof body.csrf_token !== "string" || body.csrf_token.length === 0) {
        return false;
      }
      csrfToken = body.csrf_token;
      return true;
    } catch {
      return false;
    }
  })();
  try {
    return await Promise.race([read, deadline]);
  } finally {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    settleDeadline(false);
  }
}

let paperStatusRecovery: Promise<boolean> | null = null;

/**
 * Only for a forbidden Paper status GET, never a command replay. Concurrent
 * reads share the one-time redemption. A restart invalidates memory-only
 * backend sessions; the fresh shell may still offer its unused bootstrap.
 */
export function recoverPaperStatusSession(): Promise<boolean> {
  paperStatusRecovery ??= recoverPaperStatusSessionOnce().finally(() => {
    paperStatusRecovery = null;
  });
  return paperStatusRecovery;
}

async function recoverPaperStatusSessionOnce(): Promise<boolean> {
  clearCsrf();
  try {
    // Match the existing backend's supported loopback origins, not arbitrary
    // local-looking hosts. Do not contact any recovery endpoint off loopback.
    const origin = new URL(location.origin);
    if (
      origin.protocol !== "http:" ||
      !["127.0.0.1", "localhost"].includes(origin.hostname)
    ) {
      return false;
    }

    const existing = await fetch("/api/v1/session/csrf", {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      redirect: "error",
    });
    if (existing.ok) {
      const body = (await existing.json()) as { csrf_token?: unknown };
      if (typeof body.csrf_token !== "string" || !body.csrf_token.trim()) {
        return false;
      }
      csrfToken = body.csrf_token;
      return true;
    }
    // A network/server/malformed response is not evidence of a lost cookie.
    if (existing.status !== 403) return false;

    const shell = await fetch("/", {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      redirect: "error",
    });
    if (
      shell.status !== 200 ||
      shell.redirected ||
      new URL(shell.url).origin !== origin.origin ||
      shell.headers.get("Content-Type")?.split(";", 1)[0].trim().toLowerCase() !== "text/html"
    ) {
      return false;
    }
    // DOMParser creates an inert document: do not mount it, execute scripts,
    // navigate, or consult the original document's already-consumed token.
    const parsed = new DOMParser().parseFromString(await shell.text(), "text/html");
    const metas = parsed.querySelectorAll('meta[name="krellbot-bootstrap"]');
    if (metas.length !== 1) return false;
    const token = metas[0].getAttribute("content");
    if (!token?.trim()) return false;
    await redeemBootstrap(token);
    return true;
  } catch {
    clearCsrf();
    return false;
  }
}

export function clearCsrf(): void {
  csrfToken = null;
}