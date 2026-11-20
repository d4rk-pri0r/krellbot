/**
 * Dedicated Settings view behavior (KRELL-SIGNAL-20261010).
 *
 * Pins: Exchange keys, Paper & safety, Trust & billing, Privacy & telemetry,
 * This computer (local session / reconnect QR / demo fixture), and About live
 * in Settings (`?view=settings&section=...`) rather than on Workspace Home,
 * and setup tour Step 2 opens Settings → Exchange keys.
 */
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { VersionClient } from "../../api/version";
import type { KeysClient, KeysStatus } from "../keys/client";
import type { LiveWizardHonesty, TrustClient } from "../onboarding/client";
import type { PacksClient } from "../packs/client";
import type { ReferralClient } from "../referral/client";
import { writeWorkspaceSetupTourState } from "../onboarding/workspaceSetupTourPersistence";
import { AppHome } from "../../shell/AppHome";
import { WorkstationShell } from "../../shell/WorkstationShell";
import { clickShellNav } from "../../shell/navTestUtils";
import { SettingsView } from "./SettingsView";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  if (typeof globalThis.ResizeObserver !== "function") {
    globalThis.ResizeObserver =
      ResizeObserverStub as unknown as typeof ResizeObserver;
  }
});

vi.mock("../../session", () => ({
  redeemBootstrap: (): Promise<void> => Promise.resolve(),
  recoverCsrf: (): Promise<boolean> => Promise.resolve(true),
  getCsrf: (): string => "test-csrf",
  issueReconnectToken: (): Promise<never> =>
    Promise.reject(new Error("not stubbed")),
  redeemReconnectToken: (): Promise<void> => Promise.resolve(),
}));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
  vi.restoreAllMocks();
});

const ABSENT_KEYS: KeysStatus = {
  schema_version: "1",
  venue: "kraken",
  present: false,
  corrupt: false,
  message: "no key stored",
  backend_label: null,
  balances: null,
  balances_available: false,
};

const HONEST_TRUST: LiveWizardHonesty = {
  schema_version: "1",
  trust: {
    home: "/tmp/krellbot-home",
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
};

function fakeKeysClient(): KeysClient {
  return {
    getStatus: vi.fn().mockResolvedValue(ABSENT_KEYS),
    probeAndStore: vi.fn(),
    remove: vi.fn(),
  };
}

function fakeTrustClient(): TrustClient {
  return { getTrust: vi.fn().mockResolvedValue(HONEST_TRUST) };
}

function fakeReferralClient(): ReferralClient {
  return {
    getStatus: vi.fn().mockResolvedValue({
      schema_version: "1",
      headline: "Exchange fee share / referral",
      body: "Exchange referral disclosure.",
      packs_body: "Packs referral disclosure.",
      earn_rule: "Disclosed attribution.",
      source: "local",
      receipt_count: 0,
      receipts: [],
    }),
    attribute: vi.fn(),
  };
}

function fakeVersionClient(): VersionClient {
  return {
    getVersion: vi.fn().mockResolvedValue({
      schema_version: "1",
      version: "0.9.7",
      channel: "prerelease",
      artifacts_signed: false,
    }),
  };
}

function fakeTelemetryClient(): Pick<
  PacksClient,
  "getTelemetryConsent" | "setTelemetryConsent"
> {
  return {
    getTelemetryConsent: vi.fn().mockResolvedValue({
      schema_version: "1",
      enabled: false,
      default_off: true,
      funnel_events: [],
      disclosure: "Telemetry is opt-in and off by default.",
    }),
    setTelemetryConsent: vi.fn().mockImplementation(async (enabled: boolean) => ({
      schema_version: "1",
      enabled,
      default_off: true,
      funnel_events: [],
      disclosure: "Telemetry is opt-in and off by default.",
    })),
  };
}

describe("SettingsView — sections and honesty", () => {
  it("mounts Exchange keys (Kraken + Coinbase) in Settings and never on Workspace Home", async () => {
    const home = render(<AppHome onNavigate={() => {}} />);
    expect(screen.queryByTestId("keys-onboarding-kraken")).toBeNull();
    expect(screen.queryByTestId("keys-onboarding-coinbase")).toBeNull();
    expect(screen.queryByTestId("app-home-settings-trust")).toBeNull();
    expect(home.container.textContent).not.toMatch(/No separate Settings view/i);
    home.unmount();

    const keys = fakeKeysClient();
    render(
      <SettingsView
        section="keys"
        onSectionChange={() => {}}
        onNavigate={() => {}}
        keysClient={keys}
        trustClient={fakeTrustClient()}
        referralClient={fakeReferralClient()}
        versionClient={fakeVersionClient()}
        packsClient={fakeTelemetryClient()}
      />,
    );
    expect(await screen.findByTestId("keys-onboarding-kraken")).toBeTruthy();
    expect(await screen.findByTestId("keys-onboarding-coinbase")).toBeTruthy();
    expect(await screen.findByTestId("keys-form-kraken")).toBeTruthy();
    expect(await screen.findByTestId("keys-form-coinbase")).toBeTruthy();
  });

  it("renders Paper & safety with the live-ready wizard and Run/Deploy handoffs", async () => {
    const onNavigate = vi.fn();
    render(
      <SettingsView
        section="safety"
        onSectionChange={() => {}}
        onNavigate={onNavigate}
        keysClient={fakeKeysClient()}
        trustClient={fakeTrustClient()}
        referralClient={fakeReferralClient()}
        versionClient={fakeVersionClient()}
        packsClient={fakeTelemetryClient()}
      />,
    );
    expect(await screen.findByTestId("live-wizard")).toBeTruthy();
    expect(screen.getByTestId("live-wizard-no-license").textContent).toMatch(
      /No license token/i,
    );
    fireEvent.click(screen.getByTestId("settings-link-run"));
    expect(onNavigate).toHaveBeenCalledWith("workstation");
    fireEvent.click(screen.getByTestId("settings-link-deploy"));
    expect(onNavigate).toHaveBeenCalledWith("deployments");
  });

  it("renders Trust & billing with Paid disclosures and Exchange referral", async () => {
    render(
      <SettingsView
        section="trust"
        onSectionChange={() => {}}
        onNavigate={() => {}}
        keysClient={fakeKeysClient()}
        trustClient={fakeTrustClient()}
        referralClient={fakeReferralClient()}
        versionClient={fakeVersionClient()}
        packsClient={fakeTelemetryClient()}
      />,
    );
    expect(screen.getByTestId("paid-disclosures-panel")).toBeTruthy();
    expect(await screen.findByTestId("referral-disclosure-panel")).toBeTruthy();
  });

  it("wires Privacy & telemetry toggle off by default and persists opt-in via client", async () => {
    const telemetry = fakeTelemetryClient();
    render(
      <SettingsView
        section="privacy"
        onSectionChange={() => {}}
        onNavigate={() => {}}
        keysClient={fakeKeysClient()}
        trustClient={fakeTrustClient()}
        referralClient={fakeReferralClient()}
        versionClient={fakeVersionClient()}
        packsClient={telemetry}
      />,
    );
    const checkbox = (await screen.findByTestId(
      "settings-telemetry-opt-in",
    )) as HTMLInputElement;
    await waitFor(() => {
      expect(telemetry.getTelemetryConsent).toHaveBeenCalledTimes(1);
    });
    expect(checkbox.checked).toBe(false);
    expect(screen.getByTestId("settings-telemetry-status").textContent).toMatch(
      /Off \(default\)/i,
    );

    fireEvent.click(checkbox);
    await waitFor(() => {
      expect(telemetry.setTelemetryConsent).toHaveBeenCalledWith(true);
    });
    expect(checkbox.checked).toBe(true);
    expect(screen.getByTestId("settings-telemetry-status").textContent).toMatch(
      /Opted in/i,
    );
  });

  it("hosts reconnect QR invite and collapsed Fixture demo seed under This computer", async () => {
    const onIssue = vi.fn().mockResolvedValue({
      token: "tok-settings-1",
      expiresAt: 1700000300,
      expiresIn: 300,
      redeemPath: "/?reconnect=tok-settings-1",
      qrPayload: "http://127.0.0.1:8080/?reconnect=tok-settings-1",
    });
    render(
      <SettingsView
        section="computer"
        onSectionChange={() => {}}
        onNavigate={() => {}}
        onIssueReconnect={onIssue}
        keysClient={fakeKeysClient()}
        trustClient={fakeTrustClient()}
        referralClient={fakeReferralClient()}
        versionClient={fakeVersionClient()}
        packsClient={fakeTelemetryClient()}
      />,
    );
    expect(
      screen.getByTestId("settings-demo-fixture").getAttribute("data-open"),
    ).toBe("0");
    fireEvent.click(screen.getByTestId("settings-reconnect-issue"));
    await waitFor(() => {
      expect(screen.getByTestId("settings-reconnect-offer")).toBeTruthy();
    });
    expect(screen.getByTestId("settings-reconnect-token").textContent).toBe(
      "tok-settings-1",
    );
    expect(screen.getByTestId("app-home-reconnect-qr").tagName).toBe("svg");
  });

  it("shows version and unsigned posture under About", async () => {
    render(
      <SettingsView
        section="about"
        onSectionChange={() => {}}
        onNavigate={() => {}}
        keysClient={fakeKeysClient()}
        trustClient={fakeTrustClient()}
        referralClient={fakeReferralClient()}
        versionClient={fakeVersionClient()}
        packsClient={fakeTelemetryClient()}
      />,
    );
    expect((await screen.findByTestId("app-home-about-version")).textContent).toBe(
      "v0.9.7",
    );
    expect(screen.getByTestId("app-home-about-channel").textContent).toBe(
      "Prerelease",
    );
    expect(screen.getByTestId("app-home-about-signing").textContent).toBe(
      "Unsigned artifacts",
    );
  });
});

describe("WorkstationShell — Settings routing and setup tour Step 2", () => {
  it("syncs ?view=settings&section=... and clears section when leaving Settings", () => {
    render(<WorkstationShell />);
    clickShellNav("Settings");
    expect(window.location.search).toBe("?view=settings");
    expect(screen.getByTestId("settings-view")).toBeTruthy();
    expect(
      screen.getByTestId("settings-content").getAttribute("data-settings-section"),
    ).toBe("keys");

    fireEvent.click(screen.getByTestId("settings-nav-privacy"));
    expect(window.location.search).toBe("?view=settings&section=privacy");
    expect(
      screen.getByTestId("settings-content").getAttribute("data-settings-section"),
    ).toBe("privacy");

    clickShellNav("Workspace");
    expect(window.location.search).toBe("?view=home");
    expect(screen.queryByTestId("settings-view")).toBeNull();
  });

  it("navigates to Settings → Exchange keys from Command Palette and Setup Tour Step 2", () => {
    writeWorkspaceSetupTourState({ status: "active", stepId: "workspace" });
    render(<WorkstationShell />);
    expect(screen.getByTestId("app-home")).toBeTruthy();

    fireEvent.click(screen.getByTestId("workspace-setup-tour-next"));
    expect(
      screen.getByTestId("workspace-setup-tour").getAttribute("data-setup-step"),
    ).toBe("keys");
    expect(screen.getByTestId("settings-view")).toBeTruthy();
    expect(
      screen.getByTestId("settings-content").getAttribute("data-settings-section"),
    ).toBe("keys");
    expect(window.location.search).toBe("?view=settings&section=keys");

    fireEvent.click(screen.getByTestId("workspace-setup-tour-back"));
    expect(screen.getByTestId("app-home")).toBeTruthy();

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    fireEvent.click(screen.getByTestId("command-palette-action-settings-keys"));
    expect(screen.getByTestId("settings-view")).toBeTruthy();
    expect(window.location.search).toBe("?view=settings&section=keys");
  });
});
