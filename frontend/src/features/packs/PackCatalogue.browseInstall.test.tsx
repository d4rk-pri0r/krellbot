/**
 * Catalogue browse + one-click install / paid checkout behaviour (M5.2 + M21.1).
 * Contract: KRELL-SIGNAL-20261010.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PackCatalogue } from "./PackCatalogue";
import type {
  CatalogueDocument,
  CheckoutResult,
  PackInstallResult,
  PackRow,
  PacksClient,
} from "./client";
import { PackLibraryHttpError } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const FREE: CatalogueDocument = {
  schema_version: "1",
  catalogue_version: "1",
  updated: "2026-11-16T00:00:00Z",
  packs: [
    {
      id: "free-dual-ma",
      tier: "free",
      label: "Free Dual MA",
      description: "Educational free pack",
      version: "1.0.0",
      permissions: [],
    },
    {
      id: "paid-triple-stack",
      tier: "paid",
      label: "Triple Stack",
      description: "Paid catalog pack",
      version: "2.1.0",
      permissions: ["catalog"],
    },
  ],
};

function installedRow(pack_id: string, version: string): PackRow {
  return {
    bucket: "download_pending",
    pack_id,
    version,
    permissions: [],
    rollback_ref: null,
  };
}

function makeClient(overrides: Partial<PacksClient> = {}): PacksClient {
  return {
    listInstalled: vi.fn(async () => []),
    redeemActivation: vi.fn(async () => ({
      schema_version: "1",
      status: "dead" as const,
      message: "license not accepted",
      catalog_downloaded: false,
    })),
    listCatalogue: vi.fn(async () => FREE),
    install: vi.fn(async (pack_id: string): Promise<PackInstallResult> => ({
      ok: true,
      pack: installedRow(pack_id, "1.0.0"),
    })),
    startCheckout: vi.fn(async (sku: string): Promise<CheckoutResult> => ({
      schema_version: "1",
      status: "paid",
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
    listCommunityIndex: vi.fn(async () => ({
      schema_version: "1",
      index_url: "",
      packs: [],
      fetched_at: null,
    })),
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
    ...overrides,
  };
}

describe("PackCatalogue browse and one-click install", () => {
  it("loads free and paid catalogue rows with version and tier", async () => {
    render(<PackCatalogue client={makeClient()} />);
    expect(await screen.findByTestId("pack-catalogue-list")).toBeDefined();
    expect(screen.getByTestId("pack-catalogue-version").textContent).toContain(
      "catalogue 1",
    );
    expect(screen.getByTestId("pack-catalogue-id-free-dual-ma").textContent).toBe(
      "free-dual-ma",
    );
    expect(screen.getByTestId("pack-catalogue-tier-free-dual-ma").textContent).toBe(
      "free",
    );
    expect(
      screen.getByTestId("pack-catalogue-version-free-dual-ma").textContent,
    ).toBe("1.0.0");
    expect(screen.getByTestId("pack-catalogue-tier-paid-triple-stack").textContent).toBe(
      "paid",
    );
  });

  it("one-click installs a free pack and reports bucket/version", async () => {
    const onInstalled = vi.fn();
    const install = vi.fn(async (): Promise<PackInstallResult> => ({
      ok: true,
      pack: installedRow("free-dual-ma", "1.0.0"),
    }));
    render(
      <PackCatalogue
        client={makeClient({ install })}
        onInstalled={onInstalled}
      />,
    );
    await screen.findByTestId("pack-catalogue-list");
    fireEvent.click(screen.getByTestId("pack-catalogue-install-free-dual-ma"));
    await waitFor(() => {
      expect(
        screen.getByTestId("pack-catalogue-install-status-free-dual-ma").textContent,
      ).toMatch(/Installed · download_pending · 1\.0\.0/);
    });
    expect(install).toHaveBeenCalledWith("free-dual-ma");
    expect(onInstalled).toHaveBeenCalledOnce();
  });

  it("paid checkout refreshes entitlements on success", async () => {
    const onCheckoutPaid = vi.fn();
    const startCheckout = vi.fn(async (): Promise<CheckoutResult> => ({
      schema_version: "1",
      status: "paid",
      message: "checkout paid",
      sku: "paid-triple-stack",
      entitlements: ["paid-triple-stack"],
      session_id: "cs_fake_paid-triple-stack",
    }));
    render(
      <PackCatalogue
        client={makeClient({ startCheckout })}
        onCheckoutPaid={onCheckoutPaid}
      />,
    );
    await screen.findByTestId("pack-catalogue-list");
    expect(screen.queryByTestId("pack-catalogue-install-paid-triple-stack")).toBeNull();
    fireEvent.click(screen.getByTestId("pack-catalogue-checkout-paid-triple-stack"));
    await waitFor(() => {
      expect(
        screen.getByTestId("pack-catalogue-checkout-status-paid-triple-stack").textContent,
      ).toMatch(/Entitled · entitlements refreshed/);
    });
    expect(startCheckout).toHaveBeenCalledWith("paid-triple-stack");
    expect(onCheckoutPaid).toHaveBeenCalledOnce();
  });

  it("failed checkout leaves a closed message without refreshing entitlements", async () => {
    const onCheckoutPaid = vi.fn();
    const startCheckout = vi.fn(async (): Promise<CheckoutResult> => ({
      schema_version: "1",
      status: "failed",
      message: "checkout refused",
      sku: "paid-triple-stack",
      entitlements: [],
      session_id: null,
    }));
    render(
      <PackCatalogue
        client={makeClient({ startCheckout })}
        onCheckoutPaid={onCheckoutPaid}
      />,
    );
    await screen.findByTestId("pack-catalogue-list");
    fireEvent.click(screen.getByTestId("pack-catalogue-checkout-paid-triple-stack"));
    await waitFor(() => {
      expect(
        screen.getByTestId("pack-catalogue-checkout-status-paid-triple-stack").textContent,
      ).toMatch(/Checkout refused.*Trading and export stay available/);
    });
    expect(onCheckoutPaid).not.toHaveBeenCalled();
  });

  it("shows a truthful catalogue failure instead of inventing rows", async () => {
    const listCatalogue = vi.fn(async () => {
      throw new PackLibraryHttpError(502, "catalogue failed: 502");
    });
    render(<PackCatalogue client={makeClient({ listCatalogue })} />);
    expect(await screen.findByTestId("pack-catalogue-error")).toBeDefined();
    expect(screen.getByTestId("pack-catalogue-error").textContent).toMatch(
      /Catalogue failed \(HTTP 502\)/,
    );
    expect(screen.queryByTestId("pack-catalogue-list")).toBeNull();
  });

  it("shows launch pack family honesty for the DCA SKU without returns promises", async () => {
    const launchDoc: CatalogueDocument = {
      schema_version: "1",
      catalogue_version: "1",
      updated: "2026-11-18T00:00:00Z",
      packs: [
        {
          id: "paid-launch-dca",
          tier: "paid",
          label: "Launch DCA",
          description:
            "Launch DCA pack family. Tools only — not personalized advice. Research/fixture results are backtest or pinned fixture — not live market performance. No returns promises.",
          version: "1.0.0",
          permissions: ["catalog"],
        },
      ],
    };
    render(
      <PackCatalogue
        client={makeClient({ listCatalogue: vi.fn(async () => launchDoc) })}
      />,
    );
    expect(
      await screen.findByTestId("pack-catalogue-launch-family-honesty"),
    ).toBeDefined();
    const familyHonesty =
      screen.getByTestId("pack-catalogue-launch-family-honesty").textContent ?? "";
    expect(familyHonesty.toLowerCase()).toContain("not personalized advice");
    expect(familyHonesty.toLowerCase()).toMatch(/fixture/);
    expect(familyHonesty.toLowerCase()).toMatch(/backtest/);
    expect(familyHonesty.toLowerCase()).not.toMatch(/guaranteed\s+returns?/);
    expect(
      screen.getByTestId("pack-catalogue-launch-honesty-paid-launch-dca").textContent,
    ).toMatch(/not personalized advice/i);
    expect(screen.queryByTestId("pack-catalogue-install-paid-launch-dca")).toBeNull();
    expect(screen.getByTestId("pack-catalogue-checkout-paid-launch-dca")).toBeDefined();
  });
});
