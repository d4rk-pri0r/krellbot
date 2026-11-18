/**
 * Operations first-viewport density — KRELL-SIGNAL-20261010 /
 * docs/ui-density.md (M18.4 / KRE-137).
 *
 * Pins useful rows (or short actionable empties) above the fold at
 * 1440×900: live status, kill switch, deployments, alerts. Advanced stays
 * collapsed. No Learn nav.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OperationsView } from "./OperationsView";
import type {
  AlertRow,
  DeploymentRow,
  OperationsClient,
  OperationsViewModel,
} from "./client";
import { Navigation } from "../../shell/Navigation";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.restoreAllMocks();
});

function view(over: Partial<OperationsViewModel> = {}): OperationsViewModel {
  return {
    schema_version: "1",
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
    ...over,
  };
}

function makeClient(
  overrides: Partial<OperationsClient> = {},
): OperationsClient {
  return {
    getOperations: vi.fn().mockResolvedValue(view()),
    engageKill: vi.fn(),
    releaseKill: vi.fn(),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    promote: vi.fn(),
    acknowledgeAlert: vi.fn(),
    ...overrides,
  } as OperationsClient;
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "");
}

describe("operations first-viewport density at 1440×900", () => {
  it("keeps status, kill, deployments, and alerts in the first-viewport band", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(
        view({
          deployments: [
            {
              venue: "kraken",
              pair: "SUIUSD",
              mode: "paper",
              pack_id: "trend-follow",
              pack_version: "1.0.0",
              entries_paused: false,
              promotion: { available: false, code: "live_disabled" },
            } satisfies DeploymentRow,
          ],
          alerts: [
            {
              id: "a1",
              severity: "warning",
              kind: "paper",
              code: "entries_paused",
              venue: "kraken",
              pair: "SUIUSD",
              count: 1,
              first_ts: 1,
              last_ts: 1,
              acknowledged: false,
            } satisfies AlertRow,
          ],
        }),
      ),
    });
    render(<OperationsView client={client} />);
    const first = await screen.findByTestId("ops-first-viewport");
    expect(first.contains(screen.getByTestId("ops-status-banner"))).toBe(true);
    expect(first.contains(screen.getByTestId("ops-kill"))).toBe(true);
    expect(first.contains(screen.getByTestId("ops-deployments-panel"))).toBe(
      true,
    );
    expect(first.contains(screen.getByTestId("ops-alerts-panel"))).toBe(true);
    await screen.findByTestId("ops-deployment-kraken-SUIUSD");
    expect(screen.getByTestId("ops-alert-a1")).toBeTruthy();
    expect(screen.getByTestId("ops-unresolved-orders-panel").getAttribute("data-open")).toBe(
      "0",
    );
    expect(screen.getByTestId("ops-scheduler-panel").getAttribute("data-open")).toBe(
      "0",
    );
  });

  it("shows short actionable empties for alerts and deployments", async () => {
    render(<OperationsView client={makeClient()} />);
    const deployments = await screen.findByTestId("ops-deployments");
    expect(deployments.textContent).toMatch(/No deployments\./);
    expect(deployments.textContent).toMatch(/Start a paper run/i);
    const alerts = screen.getByTestId("ops-alerts");
    expect(alerts.textContent).toMatch(/No alerts\./);
    expect(alerts.textContent).toMatch(/Refresh after a refusal/i);
  });

  it("ships dense first-viewport CSS with internal alert scroll", () => {
    const css = stripComments(
      readFileSync(join(here, "OperationsView.signal.css"), "utf8"),
    );
    expect(css).toMatch(
      /\.kbot-ops\s+\.kbot-ops__first-viewport\s*\{[^}]*display:\s*grid/,
    );
    expect(css).toMatch(
      /\.kbot-ops\s+\.kbot-ops__alert-groups\s*\{[^}]*max-height:\s*280px/,
    );
  });

  it("keeps Learn out of workstation navigation", () => {
    render(<Navigation active="operations" onChange={() => {}} />);
    const nav = screen.getByTestId("kbot-nav");
    expect(nav.textContent ?? "").not.toMatch(/Learn/i);
    expect(screen.queryByRole("button", { name: /^Learn$/i })).toBeNull();
  });
});
