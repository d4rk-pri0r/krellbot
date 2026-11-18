/**
 * Live-ready wizard honesty — Signal (KRELL-SIGNAL-20261010).
 *
 * Pins welcome truths, trust snapshot, no license ask, and distinct
 * paper-only release vs live grant states. Fake clients only.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { KeysClient, KeysStatus } from "../keys/client";
import { LiveWizardPanel } from "./LiveWizardPanel";
import type { LiveWizardHonesty, TrustClient } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function honesty(over: Partial<LiveWizardHonesty> = {}): LiveWizardHonesty {
  return {
    schema_version: "1",
    trust: {
      home: "/tmp/krellbot-home",
      home_mode: "0o755",
      home_mode_ok: false,
      keychain_backend: "FakeKeyring",
      keychain_ok: false,
      posture_ok: false,
      posture_warning:
        "keychain backend is FakeKeyring (not persistent); home mode is 0o755, expected 0o700 — another local user may read this directory",
      bind: "127.0.0.1",
      live_arm_ui_allowed: false,
      trade_only_required: true,
    },
    paper_only_release: true,
    release_policy: "paper_only",
    release_policy_code: "live_disabled_paper_only_release",
    release_policy_message:
      "v0.9.7 is a paper-only release: live order send is disabled regardless of environment, stored keys, or authorization.",
    live_grant_active: false,
    live_grant: { active: false, expires_at: null, grants: [] },
    live_ready: false,
    live_arm_ui_allowed: false,
    trade_only_required: true,
    license_required_for_exchange: false,
    keys_leave_machine: false,
    ...over,
  };
}

function absentKeys(): KeysStatus {
  return {
    schema_version: "1",
    venue: "kraken",
    present: false,
    corrupt: false,
    message: "no key stored",
    backend_label: null,
    balances: null,
    balances_available: false,
  };
}

function makeKeysClient(): KeysClient {
  return {
    getStatus: vi.fn().mockResolvedValue(absentKeys()),
    probeAndStore: vi.fn(),
    remove: vi.fn(),
  };
}

function makeTrustClient(view: LiveWizardHonesty = honesty()): TrustClient {
  return {
    getTrust: vi.fn().mockResolvedValue(view),
  };
}

describe("LiveWizardPanel", () => {
  it("shows welcome truths and never asks for a license", async () => {
    render(
      <LiveWizardPanel
        trustClient={makeTrustClient()}
        keysClient={makeKeysClient()}
      />,
    );
    const welcome = await screen.findByTestId("live-wizard-welcome");
    expect(welcome.textContent).toMatch(/free and open-source/i);
    expect(welcome.textContent).toMatch(/not sent to krellbot\.dev/i);
    expect(screen.getByTestId("live-wizard-no-license").textContent).toMatch(
      /No license token/i,
    );
    expect(screen.queryByLabelText(/license/i)).toBeNull();
    expect(document.querySelector('input[name*="license" i]')).toBeNull();
  });

  it("renders fail-closed trust snapshot with requirement, not validated connection", async () => {
    render(
      <LiveWizardPanel
        trustClient={makeTrustClient()}
        keysClient={makeKeysClient()}
      />,
    );
    fireEvent.click(screen.getByTestId("live-wizard-step-security"));
    await waitFor(() => {
      expect(screen.getByTestId("live-wizard-posture").textContent).toMatch(
        /krellbot doctor/i,
      );
    });
    expect(screen.getByTestId("live-wizard-home-mode").textContent).toMatch(/0o755/);
    expect(screen.getByTestId("live-wizard-bind").textContent).toBe("127.0.0.1");
    expect(screen.getByTestId("live-wizard-arm-ui").textContent).toMatch(/not allowed/i);
    expect(screen.getByTestId("live-wizard-key-requirement").textContent).toMatch(
      /Trade-only permission required/i,
    );
    expect(screen.getByTestId("live-wizard-key-requirement").textContent).toMatch(
      /No exchange key is probed/i,
    );
  });

  it("embeds exchange probe without a license field", async () => {
    render(
      <LiveWizardPanel
        trustClient={makeTrustClient()}
        keysClient={makeKeysClient()}
      />,
    );
    fireEvent.click(screen.getByTestId("live-wizard-step-exchange"));
    expect(await screen.findByTestId("live-wizard-exchange")).toBeTruthy();
    expect(await screen.findByTestId("keys-form-kraken")).toBeTruthy();
    expect(screen.queryByLabelText(/license/i)).toBeNull();
  });

  it("distinguishes paper-only release from live grant and never claims live-ready", async () => {
    const trust = makeTrustClient(
      honesty({
        live_grant_active: true,
        live_grant: {
          active: true,
          expires_at: 1_900_000_000,
          grants: [{ venue: "kraken", pair: "XXBTZUSD" }],
        },
        live_ready: true,
      }),
    );
    render(<LiveWizardPanel trustClient={trust} keysClient={makeKeysClient()} />);
    fireEvent.click(screen.getByTestId("live-wizard-step-live"));
    await waitFor(() => {
      expect(screen.getByTestId("live-wizard-paper-only").textContent).toMatch(
        /paper-only release/i,
      );
    });
    expect(screen.getByTestId("live-wizard-grant").textContent).toMatch(
      /Grant on file: kraken XXBTZUSD/i,
    );
    expect(screen.getByTestId("live-wizard-grant").textContent).toMatch(
      /not live order send/i,
    );
    expect(screen.getByTestId("live-wizard-live-ready").textContent).toBe(
      "Live-ready claim: no",
    );
    expect(screen.getByTestId("live-wizard-keys-local").textContent).toMatch(
      /Keys leave this machine: no/,
    );
  });
});
