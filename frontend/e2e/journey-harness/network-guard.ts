/** Deny browser egress before the first navigation; retain every refusal. */
import type { Page } from "@playwright/test";

export type OffLoopbackRecord = { via: "request" | "websocket"; method: string; url: string };
export type NetworkGuard = { offLoopback: OffLoopbackRecord[]; consoleErrors: string[]; pageErrors: string[] };

export function loopbackUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (["about:", "data:", "blob:"].includes(parsed.protocol)) return true;
    if (!["http:", "https:", "ws:", "wss:"].includes(parsed.protocol)) return false;
    return ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname.toLowerCase());
  } catch { return false; }
}

export async function attachNetworkGuard(page: Page): Promise<NetworkGuard> {
  const guard: NetworkGuard = {offLoopback: [], consoleErrors: [], pageErrors: []};
  await page.context().route("**/*", async (route) => {
    const request = route.request();
    if (!loopbackUrl(request.url())) {
      guard.offLoopback.push({via: "request", method: request.method(), url: request.url()});
      await route.abort("blockedbyclient");
    } else await route.fallback();
  });
  await page.context().routeWebSocket("**/*", (socket) => {
    if (!loopbackUrl(socket.url())) {
      guard.offLoopback.push({via: "websocket", method: "GET", url: socket.url()});
      socket.close({code: 1008, reason: "journey guard: non-loopback"});
    } else socket.connectToServer();
  });
  page.on("console", (msg) => { if (msg.type() === "error") guard.consoleErrors.push(msg.text()); });
  page.on("pageerror", (error) => guard.pageErrors.push(error.message));
  return guard;
}

export function assertNoOffLoopback(guard: NetworkGuard): void {
  if (guard.offLoopback.length) throw new Error(`network-guard: non-loopback attempts refused: ${JSON.stringify(guard.offLoopback)}`);
}
