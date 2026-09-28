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

export function clearCsrf(): void {
  csrfToken = null;
}