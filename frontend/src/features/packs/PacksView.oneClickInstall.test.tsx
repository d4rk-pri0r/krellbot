/**
 * Packs first-class destination: browse, install, show library bucket/version.
 * Contract: KRELL-SIGNAL-20261010.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PacksView } from "./PacksView";
import type {
  CatalogueDocument,
  PackInstallResult,
  PackRow,
  PacksClient,
} from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const CATALOGUE: CatalogueDocument = {
  schema_version: "1",
  catalogue_version: "1",
  updated: null,
  packs: [
    {
      id: "free-dual-ma",
      tier: "free",
      label: "Free Dual MA",
      description: null,
      version: "1.0.0",
      permissions: [],
    },
  ],
};

function makeClient(): PacksClient {
  let library: PackRow[] = [];
  return {
    listInstalled: vi.fn(async () => library),
    rollback: vi.fn(async () => ({ ok: false })),
    redeemActivation: vi.fn(async () => ({
      schema_version: "1",
      status: "dead",
      message: "license not accepted",
      catalog_downloaded: false,
    })),
    listCatalogue: vi.fn(async () => CATALOGUE),
    install: vi.fn(async (pack_id: string): Promise<PackInstallResult> => {
      const pack: PackRow = {
        bucket: "download_pending",
        pack_id,
        version: "1.0.0",
        permissions: [],
        rollback_ref: null,
      };
      library = [pack];
      return { ok: true, pack };
    }),
  };
}

describe("PacksView one-click install shows library bucket and version", () => {
  it("mounts catalogue and library on the Packs destination", async () => {
    render(<PacksView client={makeClient()} />);
    expect(screen.getByTestId("packs-view")).toBeDefined();
    expect(await screen.findByTestId("pack-catalogue-list")).toBeDefined();
    expect(screen.getByTestId("pack-library-panel")).toBeDefined();
  });

  it("after install remounts the library with bucket and version", async () => {
    render(<PacksView client={makeClient()} />);
    await screen.findByTestId("pack-catalogue-list");
    expect(await screen.findByTestId("pack-library-empty")).toBeDefined();

    fireEvent.click(screen.getByTestId("pack-catalogue-install-free-dual-ma"));

    await waitFor(() => {
      expect(screen.getByTestId("pack-library-row-free-dual-ma")).toBeDefined();
    });
    expect(screen.getByTestId("pack-library-bucket-free-dual-ma").textContent).toMatch(
      /download_pending/,
    );
    expect(screen.getByTestId("pack-library-version-free-dual-ma").textContent).toBe(
      "1.0.0",
    );
  });
});
