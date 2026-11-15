/**
 * Application Home card layout — KRELL-SIGNAL-20261010.
 *
 * Pins the structure and shipped CSS that keep workspace card
 * descriptions readable at 1440×900. Shell buttons are inline-flex; a
 * flat four-child card laid those children in a row and squeezed
 * descriptions into ~51–77px columns. The stacked card body + higher
 * specificity display rules prevent that regression.
 *
 * jsdom has no layout engine, so width proofs read the real stylesheet.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppHome } from "./AppHome";
import type { KeysClient } from "../features/keys/client";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(cleanup);

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

function readStylesheet(): string {
  return readFileSync(join(here, "AppHome.signal.css"), "utf8");
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "");
}

const CARD_TESTIDS = [
  "app-home-card-workstation",
  "app-home-card-strategies",
  "app-home-card-studio",
  "app-home-card-research",
  "app-home-card-operations",
] as const;

describe("home card layout at 1440×900", () => {
  it("wraps each card's copy in a single stacked body column", () => {
    render(<AppHome onNavigate={() => {}} keysClient={absentKeysClient()} />);
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

  it("beats shell inline-flex so cards stack and keep a readable min track", () => {
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
      /\.app-home__card-body\s*\{[^}]*display:\s*grid/,
    );
    expect(css).toMatch(
      /\.app-home__card-body\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/,
    );
    expect(css).toMatch(
      /\.app-home__card-body\s*\{[^}]*width:\s*100%/,
    );

    expect(css).toMatch(
      /\.app-home__cards\s*\{[^}]*grid-template-columns:\s*repeat\(\s*auto-fit,\s*minmax\(260px,\s*1fr\)\s*\)/,
    );
  });
});
