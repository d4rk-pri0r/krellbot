/**
 * Packs source honesty: community vs signed catalogue vs starters.
 * Contract: KRELL-SIGNAL-20261010.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PacksView } from "./PacksView";
import type {
  CatalogueDocument,
  CommunityIndexDocument,
  PacksClient,
} from "./client";
import {
  COMMUNITY_BADGE,
  SIGNED_CATALOGUE_BADGE,
  STARTER_BADGE,
  isCommunitySource,
  isSignedCatalogueSource,
} from "./packSources";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const CATALOGUE: CatalogueDocument = {
  schema_version: "1",
  catalogue_version: "1",
  updated: "2026-11-17T00:00:00Z",
  packs: [
    {
      id: "free-dual-ma",
      tier: "free",
      label: "Free Dual MA",
      description: "Signed free pack",
      version: "1.0.0",
      permissions: [],
    },
    {
      id: "paid-triple-stack",
      tier: "paid",
      label: "Triple Stack",
      description: "Signed paid pack",
      version: "2.0.0",
      permissions: ["catalog"],
    },
  ],
};

const COMMUNITY: CommunityIndexDocument = {
  schema_version: "1",
  index_url:
    "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/index.json",
  fetched_at: "2026-11-17T18:00:00.000Z",
  packs: [
    {
      id: "trend-follow",
      url: "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/packs/trend-follow.json",
      author: "community-example",
      label: "Trend follow",
    },
  ],
};

function makeClient(): PacksClient {
  return {
    listInstalled: vi.fn(async () => []),
    redeemActivation: vi.fn(async () => ({
      schema_version: "1",
      status: "dead" as const,
      message: "license not accepted",
      catalog_downloaded: false,
    })),
    listCatalogue: vi.fn(async () => CATALOGUE),
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
    listCommunityIndex: vi.fn(async () => COMMUNITY),
    installCommunity: vi.fn(async () => ({
      ok: false,
      code: "unused",
      message: "unused",
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
  };
}

describe("PacksView community vs signed-catalogue distinction", () => {
  it("shows distinct source badges and never labels community as ed25519-signed", async () => {
    render(<PacksView client={makeClient()} />);

    expect(screen.getByTestId("packs-paid-disclosures")).toBeDefined();
    expect(screen.getByTestId("paid-disclosures-not-advice").textContent).toMatch(
      /not personalized advice/i,
    );
    expect(screen.getByTestId("paid-disclosures-fee-share").textContent).toMatch(
      /fee share/i,
    );
    expect(screen.getByTestId("paid-disclosures-refund").textContent).toMatch(
      /refund/i,
    );
    expect(screen.getByTestId("paid-disclosures-telemetry").textContent).toMatch(
      /opt-in/i,
    );
    expect(screen.getByTestId("packs-source-legend")).toBeDefined();
    expect(screen.getByTestId("packs-source-legend-signed_catalogue").textContent).toContain(
      SIGNED_CATALOGUE_BADGE,
    );
    expect(screen.getByTestId("packs-source-legend-community").textContent).toContain(
      COMMUNITY_BADGE,
    );
    expect(screen.getByTestId("packs-source-legend-starter").textContent).toContain(
      STARTER_BADGE,
    );

    expect(screen.getByTestId("pack-catalogue-source-badge").textContent).toBe(
      SIGNED_CATALOGUE_BADGE,
    );
    expect(screen.getByTestId("pack-catalogue-panel").getAttribute("data-pack-source")).toBe(
      "signed_catalogue",
    );
    expect(isSignedCatalogueSource("signed_catalogue")).toBe(true);

    await waitFor(() => {
      expect(screen.getByTestId("community-index-list")).toBeDefined();
    });
    expect(screen.getByTestId("community-index-source-badge").textContent).toBe(COMMUNITY_BADGE);
    expect(screen.getByTestId("community-index-panel").getAttribute("data-pack-source")).toBe(
      "community",
    );
    expect(screen.getByTestId("community-index-source-trend-follow").textContent).toBe(
      COMMUNITY_BADGE,
    );
    expect(isCommunitySource("community")).toBe(true);

    const communityHonesty = screen.getByTestId("community-index-honesty").textContent ?? "";
    expect(communityHonesty.toLowerCase()).toMatch(/not ed25519-signed/);
    expect(communityHonesty.toLowerCase()).toMatch(/not a paid sku/);
    expect(communityHonesty).not.toMatch(/Signed catalogue · ed25519/);
    expect(COMMUNITY_BADGE.toLowerCase()).not.toMatch(/ed25519/);
    expect(SIGNED_CATALOGUE_BADGE.toLowerCase()).toMatch(/ed25519/);

    const signedHonesty = screen.getByTestId("pack-catalogue-honesty").textContent ?? "";
    expect(signedHonesty.toLowerCase()).toMatch(/ed25519/);
    expect(signedHonesty.toLowerCase()).toMatch(/not the community index/);

    // Paid catalogue rows keep tier=paid; community rows never get a paid tier badge.
    expect(screen.getByTestId("pack-catalogue-tier-paid-triple-stack").textContent).toBe("paid");
    expect(screen.queryByTestId("community-index-tier-trend-follow")).toBeNull();
    expect(screen.getByTestId("community-index-meta").textContent).toMatch(/index /);
    expect(screen.getByTestId("community-index-meta").textContent).toMatch(/fetched /);
  });
});
