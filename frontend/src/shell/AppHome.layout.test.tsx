/**
 * Application Home first-viewport composition — KRELL-SIGNAL-20261010 /
 * docs/ui-density.md.
 *
 * Pins the 1440×900 composition: brand + honesty + sage CTA in one clean
 * hero, with Settings & keys hosted in the dedicated Settings view rather
 * than a squeezed sidebar or duplicate card wall on Home.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { AppHome } from "./AppHome";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function readStylesheet(): string {
  return readFileSync(join(here, "AppHome.signal.css"), "utf8");
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "");
}

describe("home first-viewport composition at 1440×900", () => {
  it("keeps brand, honesty, and primary CTA in one focused first-viewport hero", () => {
    render(<AppHome onNavigate={() => {}} />);
    const first = screen.getByTestId("app-home-first-viewport");
    expect(first.classList.contains("app-home__hero")).toBe(true);
    expect(first.querySelector(".kbot-brandmark")).not.toBeNull();
    expect(first.contains(screen.getByTestId("app-home-cta-paper"))).toBe(true);
    expect(first.contains(screen.getByTestId("app-home-cta-packs"))).toBe(true);
    expect(screen.queryByTestId("app-home-availability")).toBeNull();
    expect(first.textContent).toMatch(/Live trading stays off/i);
    expect(screen.queryByTestId("app-home-path")).toBeNull();
    expect(screen.queryByTestId("app-home-keys-rail")).toBeNull();
    expect(screen.queryByTestId("app-home-works")).toBeNull();
    expect(screen.queryByTestId("activation-checklist")).toBeNull();
  });

  it("ships clean Signal hero CSS without a home right rail or card wall", () => {
    const css = stripComments(readStylesheet());
    expect(css).toMatch(/\.app-home__hero\s*\{/);
    expect(css).toMatch(/\.app-home__cta\s*\{[^}]*--action-primary-bg/);
    expect(css).not.toMatch(/\.app-home__aside\s*\{/);
    expect(css).not.toMatch(/\.app-home__cards\s*\{/);
  });
});
