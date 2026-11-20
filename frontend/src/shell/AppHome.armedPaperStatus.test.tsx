/**
 * AppHome armed paper run continuity, mobile pill/header CSS, and favicon.
 */
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { VersionClient } from "../api/version";
import type { KeysClient, KeysStatus } from "../features/keys/client";
import type { LiveWizardHonesty, TrustClient } from "../features/onboarding/client";
import type { DeploymentRow } from "../features/operations/client";
import { AppHome } from "./AppHome";
import { WorkstationShell } from "./WorkstationShell";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
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

function paperDeployment(
  overrides: Partial<DeploymentRow> = {},
): DeploymentRow {
  return {
    venue: "kraken",
    pair: "XXBTZUSD",
    pack_id: "starter-dual-ma-crossover",
    pack_version: "1.0.0",
    mode: "paper",
    entries_paused: false,
    promotion: {
      available: false,
      code: "live_disabled_paper_only_release",
    },
    ...overrides,
  };
}

describe("AppHome armed paper run status", () => {
  it("shows the running paper strategy and switches the primary CTA to Open paper run", () => {
    const onNavigate = vi.fn();
    const { container } = render(
      <AppHome
        onNavigate={onNavigate}
        armedPaperRuns={[paperDeployment()]}
      />,
    );

    const status = screen.getByTestId("app-home-active-paper");
    expect(status.getAttribute("data-paper-state")).toBe("running");
    expect(status.textContent).toContain("Running: Dual moving average");
    expect(status.textContent).toMatch(/Paper only on this computer/i);

    const cta = screen.getByTestId("app-home-cta-paper");
    expect(cta.textContent).toBe("Open paper run");
    fireEvent.click(cta);
    expect(onNavigate).toHaveBeenCalledWith("workstation");

    fireEvent.click(screen.getByTestId("app-home-cta-try-another"));
    expect(screen.getByTestId("paper-starter-chooser")).toBeDefined();

    for (const forbidden of ["$", "%", "Profit", "live ready", "XXBTZUSD"]) {
      expect(container.textContent?.includes(forbidden)).toBe(false);
    }
  });

  it("shows Waiting when entries are paused on the armed paper run", () => {
    render(
      <AppHome
        onNavigate={() => {}}
        armedPaperRuns={[
          paperDeployment({
            pack_id: "starter-mean-reversion-band",
            entries_paused: true,
          }),
        ]}
      />,
    );

    const status = screen.getByTestId("app-home-active-paper");
    expect(status.getAttribute("data-paper-state")).toBe("waiting");
    expect(status.textContent).toContain("Waiting: Mean reversion");
  });

  it("surfaces real armed paper deployments from StatusStrip's /api/v1/operations poll without extra fetches", async () => {
    const seenUrls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      seenUrls.push(url);
      if (url.endsWith("/api/v1/session/csrf")) {
        return new Response(
          JSON.stringify({ csrf_token: "tok", session_id: "sid" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.endsWith("/api/v1/operations")) {
        return new Response(
          JSON.stringify({
            schema_version: "1",
            live: {
              kill_switch: { engaged: false, reason: null, engaged_at: null },
              authorized: [],
              promotion_available: false,
            },
            deployments: [paperDeployment()],
            alerts: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.endsWith("/api/v1/trust")) {
        return new Response(JSON.stringify(HONEST_TRUST), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/api/v1/keys/")) {
        return new Response(JSON.stringify(ABSENT_KEYS), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("/api/v1/version")) {
        return new Response(
          JSON.stringify({
            schema_version: "1",
            version: "0.9.7",
            channel: "prerelease",
            artifacts_signed: false,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<WorkstationShell />);

    await waitFor(() => {
      expect(screen.getByTestId("app-home-active-paper").textContent).toContain(
        "Running: Dual moving average",
      );
    });
    expect(screen.getByTestId("app-home-cta-paper").textContent).toBe(
      "Open paper run",
    );
    expect(
      seenUrls.some((url) => url.includes("/api/v1/paper/status")),
    ).toBe(false);
  });
});

describe("mobile home pill, header flex-basis, and favicon", () => {
  it("wraps the home availability pill cleanly without breaking phrases", () => {
    const css = readFileSync(join(here, "AppHome.signal.css"), "utf8").replace(
      /\/\*[\s\S]*?\*\//g,
      "",
    );
    expect(css).toMatch(/\.app-home__availability\s*\{[^}]*flex-wrap:\s*wrap/);
    expect(css).toMatch(
      /\.app-home__availability-mode\s*\{[^}]*white-space:\s*nowrap/,
    );
    expect(css).toMatch(
      /\.app-home__availability-live\s*\{[^}]*white-space:\s*nowrap/,
    );
  });

  it("resets mobile header nav flex-basis to avoid a vertical gap", () => {
    const css = readFileSync(
      join(here, "../styles/shell.css"),
      "utf8",
    ).replace(/\/\*[\s\S]*?\*\//g, "");
    expect(css).toMatch(
      /@media\s*\(max-width:\s*640px\)[\s\S]*\.kbot-shell__brandbar\s+\.kbot-shell__nav-root\s*\{[^}]*flex:\s*0\s+0\s+auto/,
    );
  });

  it("links the local Krellbot SVG favicon in index.html", () => {
    const html = readFileSync(join(here, "../../index.html"), "utf8");
    expect(html).toContain(
      '<link rel="icon" type="image/svg+xml" href="/src/assets/brand/krellbot-mark-mint.svg" />',
    );
  });
});
