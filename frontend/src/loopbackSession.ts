/**
 * One-time loopback session for the wizard and the shell.
 *
 * The bootstrap meta is single-use. Cold open used to redeem it only
 * inside WorkstationShell, so the wizard's starter and paper calls
 * were refused. Callers share one in-flight redeem.
 */
import { recoverCsrf, redeemBootstrap } from "./session";

const BOOTSTRAP_META = "krellbot-bootstrap";

let inflight: Promise<boolean> | null = null;

function consumeBootstrapToken(): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const meta = document.querySelector(`meta[name="${BOOTSTRAP_META}"]`);
  if (meta === null) {
    return null;
  }
  const token = meta.getAttribute("content") ?? "";
  meta.remove();
  return token;
}

function track(run: Promise<boolean>): Promise<boolean> {
  const shared = run.finally(() => {
    if (inflight === shared) {
      inflight = null;
    }
  });
  inflight = shared;
  return shared;
}

async function redeemToken(token: string): Promise<boolean> {
  try {
    await redeemBootstrap(token);
    return true;
  } catch {
    return false;
  }
}

async function recoverOnly(): Promise<boolean> {
  try {
    return (await recoverCsrf()) === true;
  } catch {
    return false;
  }
}

/**
 * Redeem a present bootstrap meta immediately. Callers that arrive
 * after the meta is gone share that in-flight redeem instead of
 * recovering a session that does not exist yet.
 */
export function ensureLoopbackSession(): Promise<boolean> {
  const token = consumeBootstrapToken();
  if (token) {
    return track(redeemToken(token));
  }
  if (inflight) {
    return inflight;
  }
  return track(recoverOnly());
}
