import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { clearCsrf } from "../session";
import { WorkstationShell } from "./WorkstationShell";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  clearCsrf();
  window.localStorage.clear();
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
      if (url === "/api/v1/trust") {
        return new Response(JSON.stringify({
          schema_version: "1",
          trust: {
            home: "/tmp/home",
            home_mode: "0o700",
            home_mode_ok: true,
            keychain_backend: "FakeKeyring",
            keychain_ok: false,
            posture_ok: false,
            posture_warning: "keychain backend is FakeKeyring (not persistent)",
            bind: "127.0.0.1",
            live_arm_ui_allowed: false,
            trade_only_required: true,
          },
          paper_only_release: true,
          release_policy: "paper_only",
          release_policy_code: "live_disabled_paper_only_release",
          release_policy_message: "paper-only release",
          live_grant_active: false,
          live_grant: { active: false, expires_at: null, grants: [] },
          live_ready: false,
          live_arm_ui_allowed: false,
          trade_only_required: true,
          license_required_for_exchange: false,
          keys_leave_machine: false,
        }), { status: 200 });
      }
      if (url === "/api/v1/keys/kraken" || url === "/api/v1/keys/coinbase") {
        const venue = url.endsWith("coinbase") ? "coinbase" : "kraken";
        return new Response(JSON.stringify({
          schema_version: "1",
          venue,
          present: false,
          corrupt: false,
          message: "no key stored",
          backend_label: null,
          balances: null,
          balances_available: false,
        }), { status: 200 });
      }
      if (url === "/api/v1/version") {
        return new Response(JSON.stringify({
          schema_version: "1",
          version: "0.9.7",
          channel: "prerelease",
          artifacts_signed: false,
        }), { status: 200 });
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
    // Workspace keys + about/version may read in the same commit as
    // session-ready; Operations still must not precede the session settle.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    // Post-wizard home mounts Advanced rails, so keys / trust / version
    // may read in the same commit as the status strip. Operations still
    // must not precede the session settle.
    const afterSession = requests.slice(1);
    expect(afterSession).toContain("/api/v1/operations");
    expect(afterSession).toEqual(
      expect.arrayContaining([
        "/api/v1/operations",
        "/api/v1/trust",
        "/api/v1/keys/kraken",
        "/api/v1/keys/coinbase",
        "/api/v1/version",
      ]),
    );
    for (const url of afterSession) {
      expect([
        "/api/v1/operations",
        "/api/v1/trust",
        "/api/v1/keys/kraken",
        "/api/v1/keys/coinbase",
        "/api/v1/version",
      ]).toContain(url);
    }
    expect(screen.getByTestId("live-orders-status").textContent).toBe("No live venues authorized");
  },
);
