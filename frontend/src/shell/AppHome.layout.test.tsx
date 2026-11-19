/**
 * Application Home first-viewport density — KRELL-SIGNAL-20261010 /
 * docs/ui-density.md (M18.2).
 *
 * Pins the 1440×900 composition: brand + honesty + sage CTA in one hero,
 * compact single-column destination path (not a sparse card wall), and
 * Advanced rails collapsed by default. jsdom has no layout engine, so
 * width/density proofs read the shipped stylesheet.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { VersionClient } from "../api/version";
import type { KeysClient } from "../features/keys/client";
import { AppHome } from "./AppHome";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function absentKeysClient(): KeysClient {
  return {
    getStatus: vi.fn().mockResolvedValue({
      schema_version: "1",
      venue: "kraken",
      present: false,
      corrupt: false,
      message: "no key stored",
      backend_label: null,
      balances: null,
      balances_available: false,
    }),
    probeAndStore: vi.fn(),
    remove: vi.fn(),
  };
}

function previewVersionClient(): VersionClient {
  return {
    getVersion: vi.fn().mockResolvedValue({
      schema_version: "1",
      version: "0.9.7",
      channel: "prerelease",
      artifacts_signed: false,
    }),
  };
}

function readStylesheet(): string {
  return readFileSync(join(here, "AppHome.signal.css"), "utf8");
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "");
}

const CARD_TESTIDS = [
  "app-home-card-workstation",
  "app-home-card-strategies",
  "app-home-card-packs",
  "app-home-card-studio",
  "app-home-card-research",
  "app-home-card-operations",
] as const;

describe("home first-viewport composition at 1440×900", () => {
  it("keeps brand, honesty, CTA, and compact path in one first-viewport composition", () => {
    render(
      <AppHome
        onNavigate={() => {}}
        keysClient={absentKeysClient()}
        versionClient={previewVersionClient()}
      />,
    );
    const first = screen.getByTestId("app-home-first-viewport");
    expect(first.classList.contains("app-home__hero")).toBe(true);
    expect(first.querySelector(".kbot-brandmark")).not.toBeNull();
    expect(first.contains(screen.getByTestId("app-home-availability"))).toBe(
      true,
    );
    expect(first.contains(screen.getByTestId("app-home-cta-paper"))).toBe(true);
    expect(first.contains(screen.getByTestId("app-home-cta-packs"))).toBe(true);
    expect(
      screen.getByTestId("app-home-availability").textContent,
    ).toMatch(/Local preview/i);
    // Peer destinations live under Advanced All areas — collapsed by default.
    expect(screen.getByTestId("app-home-path").getAttribute("data-open")).toBe(
      "0",
    );
    expect(screen.queryByTestId("app-home-works")).toBeNull();
    expect(screen.queryByTestId("activation-checklist")).toBeNull();
    expect(screen.getByTestId("app-home-keys-rail").getAttribute("data-open")).toBe(
      "0",
    );
  });

  it("wraps each path row's copy in a single stacked body column", () => {
    render(
      <AppHome
        onNavigate={() => {}}
        keysClient={absentKeysClient()}
        versionClient={previewVersionClient()}
      />,
    );
    for (const testid of CARD_TESTIDS) {
      const card = screen.getByTestId(testid);
      expect(card.tagName).toBe("BUTTON");
      const body = card.querySelector(".app-home__card-body");
      expect(body).not.toBeNull();
      expect(card.children.length).toBe(1);
      expect(card.children[0]).toBe(body);
      expect(body!.querySelector(".app-home__card-detail")).not.toBeNull();
      expect(body!.querySelector(".app-home__card-action")).not.toBeNull();
    }
  });

  it("ships dense single-column path CSS instead of a sparse card wall", () => {
    const css = stripComments(readStylesheet());

    expect(css).toMatch(
      /\.app-home\s+button\.app-home__card\s*\{[^}]*display:\s*flex/,
    );
    expect(css).toMatch(
      /\.app-home\s+button\.app-home__card\s*\{[^}]*flex-direction:\s*column/,
    );
    expect(css).toMatch(
      /\.app-home\s+button\.app-home__card\s*\{[^}]*align-items:\s*stretch/,
    );
    expect(css).toMatch(
      /\.app-home\s+button\.app-home__card\s*\{[^}]*min-height:\s*0/,
    );

    expect(css).toMatch(
      /\.app-home__card-body\s*\{[^}]*display:\s*grid/,
    );
    expect(css).toMatch(
      /\.app-home__card-body\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/,
    );
    expect(css).toMatch(
      /\.app-home__card-body\s*\{[^}]*width:\s*100%/,
    );

    expect(css).toMatch(
      /\.app-home__cards\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/,
    );
    expect(css).not.toMatch(
      /\.app-home__cards\s*\{[^}]*minmax\(260px,\s*1fr\)/,
    );
  });
});
