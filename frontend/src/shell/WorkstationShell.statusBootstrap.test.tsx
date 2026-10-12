import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { clearCsrf } from "../session";
import { WorkstationShell } from "./WorkstationShell";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  clearCsrf();
  document.querySelector('meta[name="krellbot-bootstrap"]')?.remove();
});

it.each(["bootstrap", "csrf"])(
  "does not read Operations before the real session %s request settles",
  async (sessionRoute) => {
    vi.useFakeTimers();
    clearCsrf();
    if (sessionRoute === "bootstrap") {
      const meta = document.createElement("meta");
      meta.name = "krellbot-bootstrap";
      meta.content = "fixture-bootstrap";
      document.head.append(meta);
    }
    const deferred: { resolve?: () => void } = {};
    const sessionReady = new Promise<void>((resolve) => {
      deferred.resolve = resolve;
    });
    const requests: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url);
      if (url === `/api/v1/session/${sessionRoute}`) {
        await sessionReady;
        return new Response(JSON.stringify({ csrf_token: "fixture-csrf" }), { status: 200 });
      }
      if (url === "/api/v1/operations") {
        return new Response(JSON.stringify({
          live: {
            schema_version: "1",
            live_enabled: false,
            authorized: [],
            kill_switch: { engaged: false, reason: null, engaged_at: null },
            promotion_available: false,
            promotion_code: "live_promotion_owner_deferred",
          },
          deployments: [],
          alerts: [],
        }), { status: 200 });
      }
      throw new Error(`unexpected request: ${url}`);
    }));

    render(<WorkstationShell />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(requests).toEqual([`/api/v1/session/${sessionRoute}`]);
    expect(screen.getByTestId("live-orders-status").textContent).toBe("Live orders unavailable");

    await act(async () => {
      deferred.resolve?.();
    });
    // React commits the settled session before the strip schedules its
    // existing deferred read; advance that timer in the next act boundary.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(requests).toEqual([
      `/api/v1/session/${sessionRoute}`,
      "/api/v1/operations",
    ]);
    expect(screen.getByTestId("live-orders-status").textContent).toBe("No live venues authorized");
  },
);
