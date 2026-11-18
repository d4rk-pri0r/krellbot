import { describe, expect, it, vi, afterEach } from "vitest";
import { createTrustHttpClient, parseLiveWizardHonesty } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("parseLiveWizardHonesty", () => {
  it("forces live_ready false and keeps paper-only vs grant distinct", () => {
    const parsed = parseLiveWizardHonesty({
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
        live_arm_ui_allowed: true,
        trade_only_required: true,
      },
      paper_only_release: true,
      release_policy: "paper_only",
      release_policy_code: "live_disabled_paper_only_release",
      release_policy_message: "paper-only release",
      live_grant_active: true,
      live_grant: {
        active: true,
        expires_at: 1_700_000_000,
        grants: [{ venue: "kraken", pair: "XXBTZUSD" }],
      },
      live_ready: true,
      live_arm_ui_allowed: true,
      trade_only_required: true,
      license_required_for_exchange: true,
      keys_leave_machine: true,
    });

    expect(parsed.live_ready).toBe(false);
    expect(parsed.live_arm_ui_allowed).toBe(false);
    expect(parsed.paper_only_release).toBe(true);
    expect(parsed.live_grant_active).toBe(true);
    expect(parsed.live_grant.grants[0]?.pair).toBe("XXBTZUSD");
    expect(parsed.license_required_for_exchange).toBe(true);
    expect(parsed.keys_leave_machine).toBe(true);
    expect(parsed.trust.live_arm_ui_allowed).toBe(true);
  });
});

describe("createTrustHttpClient", () => {
  it("GETs /api/v1/trust and never claims live-ready", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        schema_version: "1",
        trust: {
          home: "/tmp/h",
          home_mode: "0o755",
          home_mode_ok: false,
          keychain_backend: null,
          keychain_ok: false,
          posture_ok: false,
          posture_warning: "home mode is 0o755",
          bind: "127.0.0.1",
          live_arm_ui_allowed: false,
          trade_only_required: true,
        },
        paper_only_release: true,
        release_policy: "paper_only",
        release_policy_code: "live_disabled_paper_only_release",
        release_policy_message: "paper-only",
        live_grant_active: false,
        live_grant: { active: false, expires_at: null, grants: [] },
        live_ready: true,
        live_arm_ui_allowed: false,
        trade_only_required: true,
        license_required_for_exchange: false,
        keys_leave_machine: false,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = createTrustHttpClient();
    const result = await client.getTrust();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/trust",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );
    expect(result.live_ready).toBe(false);
    expect(result.paper_only_release).toBe(true);
    expect(result.trust.home_mode).toBe("0o755");
  });
});
