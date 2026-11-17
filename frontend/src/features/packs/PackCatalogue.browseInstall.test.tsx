/**
 * Catalogue browse + one-click install behaviour (M5.2).
 * Contract: KRELL-SIGNAL-20261010.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PackCatalogue } from "./PackCatalogue";
import type {
  CatalogueDocument,
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
    listCommunityIndex: vi.fn(async () => ({
      schema_version: "1",
      index_url: "",
      packs: [],
      fetched_at: null,
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

  it("surfaces activation_required for paid packs without entitlements", async () => {
    const install = vi.fn(async (): Promise<PackInstallResult> => ({
      ok: false,
      code: "activation_required",
      message: "paid pack requires activation",
    }));
    render(<PackCatalogue client={makeClient({ install })} />);
    await screen.findByTestId("pack-catalogue-list");
    fireEvent.click(screen.getByTestId("pack-catalogue-install-paid-triple-stack"));
    await waitFor(() => {
      expect(
        screen.getByTestId("pack-catalogue-install-status-paid-triple-stack").textContent,
      ).toMatch(/Activation required/);
    });
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
});
