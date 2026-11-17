import { getCsrf } from "../../session";

export type HomeRestoreResult = {
  ok: boolean;
  code: string;
  message: string;
  fence_engaged: boolean;
  kill_reason: string | null;
  entries_paused: boolean;
  live_ready: boolean;
  paper_only_release: boolean;
  applied: boolean;
  validated?: boolean;
};

export type HomeRestoreClient = {
  restoreHome(archive: Blob): Promise<HomeRestoreResult>;
};

function asResult(body: Record<string, unknown>, fallbackCode: string): HomeRestoreResult {
  const code =
    typeof body.code === "string" && body.code ? body.code : fallbackCode;
  const message =
    typeof body.message === "string" && body.message
      ? body.message
      : "home restore failed";
  return {
    ok: body.ok === true,
    code,
    message,
    fence_engaged: body.fence_engaged === true,
    kill_reason: typeof body.kill_reason === "string" ? body.kill_reason : null,
    entries_paused: body.entries_paused === true,
    live_ready: body.live_ready === true,
    paper_only_release: body.paper_only_release !== false,
    applied: body.applied === true,
    validated: body.validated === true ? true : undefined,
  };
}

export function createHomeRestoreHttpClient(): HomeRestoreClient {
  return {
    async restoreHome(archive: Blob): Promise<HomeRestoreResult> {
      const response = await fetch("/api/v1/home/restore", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/gzip",
          "X-Krellbot-CSRF": getCsrf(),
        },
        body: archive,
      });
      let body: Record<string, unknown> = {};
      try {
        body = (await response.json()) as Record<string, unknown>;
      } catch {
        body = {};
      }
      const result = asResult(
        body,
        response.ok ? "home_restored" : "restore_failed",
      );
      if (!response.ok && result.ok) {
        return { ...result, ok: false };
      }
      if (response.ok && result.live_ready) {
        // Defense in depth: UI must never treat restore as live-ready.
        return { ...result, live_ready: false };
      }
      return result;
    },
  };
}
