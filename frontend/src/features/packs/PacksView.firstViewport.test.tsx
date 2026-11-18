/**
 * Packs first-viewport density — KRELL-SIGNAL-20261010 /
 * docs/ui-density.md (M18.4 / KRE-137).
 *
 * Pins catalogue browse density at 1440×900: useful rows or short
 * actionable empties above the fold. No Learn nav.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PacksClient } from "./client";
import { PacksView } from "./PacksView";
import { Navigation } from "../../shell/Navigation";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function makeClient(overrides: Partial<PacksClient> = {}): PacksClient {
  return {
    listCatalogue: vi.fn().mockResolvedValue({
      schema_version: "1",
      catalogue_version: "1",
      updated: null,
      packs: [],
    }),
    listCommunityIndex: vi.fn().mockResolvedValue({
      schema_version: "1",
      packs: [],
    }),
    install: vi.fn(),
    listInstalled: vi.fn().mockResolvedValue([]),
    redeemActivation: vi.fn().mockResolvedValue({
      schema_version: "1",
      status: "dead",
      message: "license not accepted",
      catalog_downloaded: false,
    }),
    startCheckout: vi.fn().mockResolvedValue({
      schema_version: "1",
      status: "paid",
      message: "checkout paid",
      sku: "",
      entitlements: [],
      session_id: null,
    }),
    installCommunity: vi.fn(),
    openCommunityPack: vi.fn(),
    ...overrides,
  } as PacksClient;
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "");
}

describe("packs first-viewport density at 1440×900", () => {
  it("keeps title and catalogue in the first-viewport band with actionable empty", async () => {
    render(<PacksView client={makeClient()} />);
    const first = screen.getByTestId("packs-first-viewport");
    expect(first.contains(screen.getByTestId("pack-catalogue-panel"))).toBe(
      true,
    );
    const empty = await screen.findByTestId("pack-catalogue-empty");
    expect(first.contains(empty)).toBe(true);
    expect(empty.textContent).toMatch(/No catalogue packs/i);
    expect(empty.textContent).toMatch(/Refresh the catalogue/i);
    const libraryEmpty = await screen.findByTestId("pack-library-empty");
    expect(libraryEmpty.textContent).toMatch(/Install from the catalogue/i);
  });

  it("shows catalogue rows above the fold when the feed has packs", async () => {
    const client = makeClient({
      listCatalogue: vi.fn().mockResolvedValue({
        schema_version: "1",
        catalogue_version: "2",
        updated: "2026-01-01",
        packs: [
          {
            id: "free-dual-ma",
            label: "Dual MA",
            tier: "free",
            version: "1.0.0",
            description: null,
            permissions: [],
          },
          {
            id: "paid-triple-stack",
            label: "Triple",
            tier: "paid",
            version: "1.2.0",
            description: null,
            permissions: [],
          },
        ],
      }),
    });
    render(<PacksView client={client} />);
    const first = screen.getByTestId("packs-first-viewport");
    await screen.findByTestId("pack-catalogue-list");
    expect(
      first.contains(screen.getByTestId("pack-catalogue-row-free-dual-ma")),
    ).toBe(true);
    expect(
      first.contains(screen.getByTestId("pack-catalogue-row-paid-triple-stack")),
    ).toBe(true);
  });

  it("ships dense single-column catalogue CSS", () => {
    const css = stripComments(
      readFileSync(join(here, "PackCatalogue.signal.css"), "utf8"),
    );
    expect(css).toMatch(
      /\.kbot-pack-catalogue__list\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/,
    );
    expect(css).toMatch(
      /\.kbot-pack-catalogue__list\s*\{[^}]*max-height:\s*320px/,
    );
    const viewCss = stripComments(
      readFileSync(join(here, "PacksView.signal.css"), "utf8"),
    );
    expect(viewCss).toMatch(/\.kbot-packs-view__first-viewport/);
  });

  it("keeps Learn out of workstation navigation", () => {
    render(<Navigation active="packs" onChange={() => {}} />);
    expect(screen.getByTestId("kbot-nav").textContent ?? "").not.toMatch(
      /Learn/i,
    );
  });
});
