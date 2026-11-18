/**
 * Live-ready wizard honesty client — trust snapshot + paper-only vs grant.
 *
 * Presentation-only GET. Never sends credentials. Defense in depth: even if
 * the API ever claimed live_ready, the client forces it false.
 */

export type TrustSnapshot = {
  home: string;
  home_mode: string | null;
  home_mode_ok: boolean;
  keychain_backend: string | null;
  keychain_ok: boolean;
  posture_ok: boolean;
  posture_warning: string | null;
  bind: string;
  live_arm_ui_allowed: boolean;
  trade_only_required: boolean;
};

export type LiveGrantState = {
  active: boolean;
  expires_at: number | null;
  grants: ReadonlyArray<{ venue: string; pair: string }>;
};

export type LiveWizardHonesty = {
  schema_version: string;
  trust: TrustSnapshot;
  paper_only_release: boolean;
  release_policy: string | null;
  release_policy_code: string | null;
  release_policy_message: string | null;
  live_grant_active: boolean;
  live_grant: LiveGrantState;
  live_ready: boolean;
  live_arm_ui_allowed: boolean;
  trade_only_required: boolean;
  license_required_for_exchange: boolean;
  keys_leave_machine: boolean;
};

export type TrustClient = {
  getTrust(): Promise<LiveWizardHonesty>;
};

function asGrant(raw: unknown): LiveGrantState {
  if (!raw || typeof raw !== "object") {
    return { active: false, expires_at: null, grants: [] };
  }
  const body = raw as Record<string, unknown>;
  const grantsRaw = Array.isArray(body.grants) ? body.grants : [];
  const grants = grantsRaw
    .filter((g): g is Record<string, unknown> => !!g && typeof g === "object")
    .map((g) => ({
      venue: typeof g.venue === "string" ? g.venue : "",
      pair: typeof g.pair === "string" ? g.pair : "",
    }))
    .filter((g) => g.venue && g.pair);
  return {
    active: body.active === true,
    expires_at: typeof body.expires_at === "number" ? body.expires_at : null,
    grants,
  };
}

function asTrust(raw: unknown): TrustSnapshot {
  const body =
    raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  return {
    home: typeof body.home === "string" ? body.home : "",
    home_mode: typeof body.home_mode === "string" ? body.home_mode : null,
    home_mode_ok: body.home_mode_ok === true,
    keychain_backend:
      typeof body.keychain_backend === "string" ? body.keychain_backend : null,
    keychain_ok: body.keychain_ok === true,
    posture_ok: body.posture_ok === true,
    posture_warning:
      typeof body.posture_warning === "string" ? body.posture_warning : null,
    bind: typeof body.bind === "string" ? body.bind : "127.0.0.1",
    live_arm_ui_allowed: body.live_arm_ui_allowed === true,
    trade_only_required: body.trade_only_required !== false,
  };
}

export function parseLiveWizardHonesty(
  body: Record<string, unknown>,
): LiveWizardHonesty {
  const trust = asTrust(body.trust);
  return {
    schema_version:
      typeof body.schema_version === "string" ? body.schema_version : "1",
    trust,
    paper_only_release: body.paper_only_release !== false,
    release_policy:
      typeof body.release_policy === "string" ? body.release_policy : null,
    release_policy_code:
      typeof body.release_policy_code === "string"
        ? body.release_policy_code
        : null,
    release_policy_message:
      typeof body.release_policy_message === "string"
        ? body.release_policy_message
        : null,
    live_grant_active: body.live_grant_active === true,
    live_grant: asGrant(body.live_grant),
    // Defense in depth: this surface never claims live-ready.
    live_ready: false,
    live_arm_ui_allowed: false,
    trade_only_required: body.trade_only_required !== false,
    license_required_for_exchange: body.license_required_for_exchange === true,
    keys_leave_machine: body.keys_leave_machine === true,
  };
}

export function createTrustHttpClient(): TrustClient {
  return {
    async getTrust(): Promise<LiveWizardHonesty> {
      const response = await fetch("/api/v1/trust", {
        method: "GET",
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      let body: Record<string, unknown> = {};
      try {
        body = (await response.json()) as Record<string, unknown>;
      } catch {
        body = {};
      }
      if (!response.ok) {
        const detail =
          typeof body.detail === "string" ? body.detail : "trust read refused";
        throw new Error(detail);
      }
      return parseLiveWizardHonesty(body);
    },
  };
}
