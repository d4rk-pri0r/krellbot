/**
 * Navigation — scoped Signal presentation vocabulary evidence.
 * Contract: KRELL-SIGNAL-20261010.
 *
 * Pins the owner-approved scoped class vocabulary the persistent
 * top-of-shell tab strip renders (frontend/src/shell/Navigation.signal.css)
 * without touching the legacy unscoped Navigation.test.tsx: every
 * expectation here is driven through the existing `active`/`onChange`
 * prop path over the seven-tab VIEWS array, and every test references an
 * existing data-testid marker verbatim (kbot-nav / nav-local-preview /
 * nav-local-preview-note), which this slice must not alter.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Navigation } from "./Navigation";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const cssSource = readFileSync(
  resolve(__dirname, "Navigation.signal.css"),
  "utf8",
);

const SEVEN_VIEWS = [
  { id: "home", label: "Home" },
  { id: "workstation", label: "Workstation" },
  { id: "strategies", label: "Strategies" },
  { id: "research", label: "Research" },
  { id: "studio", label: "Studio" },
  { id: "operations", label: "Operations" },
  { id: "deployments", label: "Deploy" },
] as const;

describe("Navigation Signal presentation (KRELL-SIGNAL-20261010)", () => {
  it("mounts the scoped Signal root with the shared navigation semantics", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    const nav = screen.getByTestId("kbot-nav");
    expect(nav).toBeInstanceOf(HTMLElement);
    // Exact tokens, not substrings: a renamed or suffixed class must fail.
    expect(nav.classList.contains("kbot-shell__nav-root")).toBe(true);
    expect(nav.getAttribute("role")).toBe("navigation");
    expect(nav.getAttribute("aria-label")).toBe("Workstation navigation");
  });

  it("renders the seven VIEWS tabs in order with the scoped item vocabulary", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    const nav = screen.getByTestId("kbot-nav");
    const items = Array.from(nav.querySelectorAll("button"));
    expect(items.map((button) => button.textContent?.trim())).toEqual(
      SEVEN_VIEWS.map((view) => view.label),
    );
    for (const item of items) {
      expect(item.classList.contains("kbot-shell__nav-item")).toBe(true);
    }
    expect(nav.querySelectorAll(".kbot-shell__nav-item")).toHaveLength(
      SEVEN_VIEWS.length,
    );
  });

  it("marks only the active tab with the scoped active class and ARIA state", () => {
    render(<Navigation active="research" onChange={() => {}} />);
    const nav = screen.getByTestId("kbot-nav");
    const active = screen.getByRole("button", { name: "Research" });
    expect(active.classList.contains("kbot-shell__nav-item--active")).toBe(
      true,
    );
    expect(active.getAttribute("aria-pressed")).toBe("true");
    expect(active.getAttribute("aria-current")).toBe("page");
    expect(
      nav.querySelectorAll(".kbot-shell__nav-item--active"),
    ).toHaveLength(1);
    for (const view of SEVEN_VIEWS) {
      if (view.id === "research") {
        continue;
      }
      const other = screen.getByRole("button", { name: view.label });
      expect(other.classList.contains("kbot-shell__nav-item--active")).toBe(
        false,
      );
      expect(other.getAttribute("aria-pressed")).toBe("false");
      expect(other.getAttribute("aria-current")).toBeNull();
    }
  });

  it("reports every view selection through the existing onChange wiring", () => {
    const onChange = vi.fn();
    render(<Navigation active="home" onChange={onChange} />);
    expect(screen.getByTestId("kbot-nav")).toBeInstanceOf(HTMLElement);
    for (const view of SEVEN_VIEWS) {
      fireEvent.click(screen.getByRole("button", { name: view.label }));
    }
    expect(onChange.mock.calls).toEqual(
      SEVEN_VIEWS.map((view) => [view.id]),
    );
  });

  it("renders the honest Local preview badge under the scoped note classes", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    const badge = screen.getByTestId("nav-local-preview");
    expect(badge.textContent?.trim()).toBe("Local preview");
    expect(badge.classList.contains("kbot-shell__nav-preview")).toBe(true);
    const caption = screen.getByTestId("nav-local-preview-note");
    expect(caption.textContent).toBe("Live trading unavailable");
    expect(caption.classList.contains("kbot-shell__nav-note-text")).toBe(true);
    const note = caption.closest(".kbot-shell__nav-note");
    expect(note).not.toBeNull();
    expect(note?.contains(badge)).toBe(true);
    const nav = screen.getByTestId("kbot-nav");
    expect(note).toBe(nav.lastElementChild);
  });

  it("scopes every stylesheet rule under the approved nav root selector", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    expect(screen.getByTestId("kbot-nav")).toBeInstanceOf(HTMLElement);
    const stripped = cssSource.replace(/\/\*[\s\S]*?\*\//g, "");
    const blocks = Array.from(stripped.matchAll(/([^{}]+)\{([^{}]*)\}/g));
    expect(blocks.length).toBeGreaterThan(0);
    for (const block of blocks) {
      expect(block[1]).toContain(".kbot-shell__nav-root");
    }
    for (const scoped of [
      ".kbot-shell__nav-item",
      ".kbot-shell__nav-item--active",
      ".kbot-shell__nav-note",
      ".kbot-shell__nav-preview",
      ".kbot-shell__nav-note-text",
    ]) {
      expect(cssSource).toContain(`${".kbot-shell__nav-root"} ${scoped}`);
    }
  });

  it("keeps the approved Signal token fallbacks and the narrow-viewport layer", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    const badge = screen.getByTestId("nav-local-preview");
    expect(badge.classList.contains("kbot-shell__nav-preview")).toBe(true);
    expect(cssSource).toContain('var(--font-ui, "Manrope"');
    expect(cssSource).toContain("var(--seafoam, #a8d8d1)");
    expect(cssSource).toContain("var(--sage, #b3dda8)");
    expect(cssSource).toContain("var(--surface, #14222e)");
    expect(cssSource).toContain("var(--line, #22465d)");
    expect(cssSource).toContain("@media (max-width: 640px)");
    expect(cssSource).toMatch(/min-height:\s*44px/);
    expect(cssSource).toMatch(/overflow-wrap:\s*anywhere/);
    expect(cssSource).not.toContain("#a3ff12");
    expect(cssSource).not.toContain("lime");
    expect(cssSource).not.toContain("cyan");
  });
});
