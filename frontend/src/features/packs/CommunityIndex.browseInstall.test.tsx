/**
 * Community index browse + one-click install with typed failures.
 * Contract: KRELL-SIGNAL-20261010.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CommunityIndex,
  communityInstallFailureCopy,
} from "./CommunityIndex";
import { PacksView } from "./PacksView";
import type {
  CommunityIndexDocument,
  CommunityInstallResult,
  PacksClient,
} from "./client";
import { COMMUNITY_BADGE } from "./packSources";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const INDEX: CommunityIndexDocument = {
  schema_version: "1",
  index_url:
    "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/index.json",
  fetched_at: "2026-11-17T19:00:00.000Z",
  packs: [
    {
      id: "trend-follow",
      url: "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/packs/trend-follow.json",
      author: "community-example",
      label: "Trend follow",
    },
  ],
};

function makeClient(overrides: Partial<PacksClient> = {}): PacksClient {
  return {
    listInstalled: vi.fn(async () => []),
    redeemActivation: vi.fn(async () => ({
      schema_version: "1",
      status: "dead" as const,
      message: "license not accepted",
      catalog_downloaded: false,
    })),
    listCatalogue: vi.fn(async () => ({
      schema_version: "1",
      catalogue_version: "0",
      updated: null,
      packs: [],
    })),
    install: vi.fn(async () => ({ ok: false, code: "unused", message: "unused" })),
    startCheckout: vi.fn(async (sku: string) => ({
      schema_version: "1",
      status: "paid" as const,
      message: "checkout paid",
      sku,
      entitlements: [sku],
      session_id: `cs_fake_${sku}`,
    })),
    requestRefund: vi.fn(async (sku: string) => ({
      schema_version: "1",
      status: "refunded" as const,
      message: "refund completed",
      sku,
      entitlements: [],
      refund_id: `re_fake_${sku}`,
    })),
    listCommunityIndex: vi.fn(async () => INDEX),
    installCommunity: vi.fn(async (pack_id: string): Promise<CommunityInstallResult> => ({
      ok: true,
      pack: {
        id: pack_id,
        version: "1.0.0",
        label: "Trend follow",
        author: "community-example",
        origin: "Community pack. Unverified. No guarantee.",
      },
      path: `packs/community/${pack_id}.json`,
    })),
    openCommunityPack: vi.fn(async () => ({
      schema_version: "1",
      source: "community" as const,
      path: "",
      pack: {},
    })),
    getTelemetryConsent: vi.fn(async () => ({
      schema_version: "1",
      enabled: false,
      default_off: true,
      funnel_events: [
        "view",
        "checkout_start",
        "checkout_success",
        "checkout_fail",
        "install",
        "arm",
      ],
      disclosure:
        "Telemetry is opt-in and off by default. Funnel events cover catalogue view, checkout start/success/fail, install, and arm.",
    })),
    setTelemetryConsent: vi.fn(async (enabled: boolean) => ({
      schema_version: "1",
      enabled,
      default_off: true,
      funnel_events: [
        "view",
        "checkout_start",
        "checkout_success",
        "checkout_fail",
        "install",
        "arm",
      ],
      disclosure:
        "Telemetry is opt-in and off by default. Funnel events cover catalogue view, checkout start/success/fail, install, and arm.",
    })),
    ...overrides,
  };
}

describe("communityInstallFailureCopy", () => {
  it("maps foreign_url, payload_refused, and validate-style codes", () => {
    expect(communityInstallFailureCopy("foreign_url")).toMatch(/Foreign URL/);
    expect(communityInstallFailureCopy("payload_refused")).toMatch(/oversized|validate/i);
    expect(communityInstallFailureCopy("pack_not_found")).toMatch(/not found/i);
  });
});

describe("CommunityIndex browse and one-click install", () => {
  it("lists id/author and installs into packs/community with version", async () => {
    const onInstalled = vi.fn();
    render(<CommunityIndex client={makeClient()} onInstalled={onInstalled} />);

    expect(await screen.findByTestId("community-index-list")).toBeDefined();
    expect(screen.getByTestId("community-index-id-trend-follow").textContent).toBe(
      "trend-follow",
    );
    expect(screen.getByTestId("community-index-author-trend-follow").textContent).toMatch(
      /community-example/,
    );
    expect(screen.getByTestId("community-index-source-trend-follow").textContent).toBe(
      COMMUNITY_BADGE,
    );

    fireEvent.click(screen.getByTestId("community-index-install-trend-follow"));

    await waitFor(() => {
      expect(
        screen.getByTestId("community-index-install-status-trend-follow").textContent,
      ).toMatch(/Installed · trend-follow · 1\.0\.0 · author community-example/);
    });
    expect(
      screen.getByTestId("community-index-install-status-trend-follow").textContent,
    ).toMatch(/packs\/community\/trend-follow\.json/);
    expect(onInstalled).toHaveBeenCalledOnce();
  });

  it("surfaces typed foreign_url refusal without inventing success", async () => {
    const installCommunity = vi.fn(async (): Promise<CommunityInstallResult> => ({
      ok: false,
      code: "foreign_url",
      message: "community pack url is not allow-listed",
    }));
    render(<CommunityIndex client={makeClient({ installCommunity })} />);
    await screen.findByTestId("community-index-list");
    fireEvent.click(screen.getByTestId("community-index-install-trend-follow"));
    await waitFor(() => {
      expect(
        screen.getByTestId("community-index-install-status-trend-follow").textContent,
      ).toMatch(/Foreign URL refused/);
    });
  });

  it("surfaces typed payload_refused for oversized or validate fail", async () => {
    const installCommunity = vi.fn(async (): Promise<CommunityInstallResult> => ({
      ok: false,
      code: "payload_refused",
      message: "community pack payload refused",
    }));
    render(<CommunityIndex client={makeClient({ installCommunity })} />);
    await screen.findByTestId("community-index-list");
    fireEvent.click(screen.getByTestId("community-index-install-trend-follow"));
    await waitFor(() => {
      expect(
        screen.getByTestId("community-index-install-status-trend-follow").textContent,
      ).toMatch(/Payload refused/);
    });
  });
});

describe("PacksView community browse + install journey", () => {
  it("installs from the Packs destination and keeps community badge honesty", async () => {
    render(<PacksView client={makeClient()} />);
    expect(await screen.findByTestId("community-index-list")).toBeDefined();
    expect(screen.getByTestId("community-index-source-badge").textContent).toBe(
      COMMUNITY_BADGE,
    );
    fireEvent.click(screen.getByTestId("community-index-install-trend-follow"));
    await waitFor(() => {
      expect(
        screen.getByTestId("community-index-install-status-trend-follow").textContent,
      ).toMatch(/^Installed ·/);
    });
  });
});
