import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Navigation } from "./Navigation";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Navigation — workstation views", () => {
  it("renders the Home tab first alongside the five core nav tabs", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    const nav = screen.getByTestId("kbot-nav");
    const labels = Array.from(
      nav.querySelectorAll<HTMLButtonElement>(".kbot-nav__item"),
    ).map((button) => button.textContent?.trim());
    expect(labels[0]).toBe("Home");
    for (const label of [
      "Home",
      "Workstation",
      "Strategies",
      "Research",
      "Studio",
      "Operations",
      "Deploy",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeDefined();
    }
  });

  it("marks Home with aria-current when active and clears the others", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    expect(
      screen.getByRole("button", { name: "Home" }).getAttribute("aria-current"),
    ).toBe("page");
    for (const label of [
      "Workstation",
      "Strategies",
      "Research",
      "Studio",
      "Operations",
      "Deploy",
    ]) {
      expect(
        screen.getByRole("button", { name: label }).getAttribute("aria-current"),
      ).toBeNull();
    }
  });

  it("reports the Home selection through onChange", () => {
    const onChange = vi.fn();
    render(<Navigation active="workstation" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Home" }));
    expect(onChange).toHaveBeenCalledWith("home");
  });

  it("renders the five core nav tabs with their labels", () => {
    render(<Navigation active="workstation" onChange={() => {}} />);
    for (const label of [
      "Workstation",
      "Strategies",
      "Research",
      "Studio",
      "Operations",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeDefined();
    }
  });

  it("renders the Deploy nav tab so users can reach the live preflight dry-run", () => {
    render(<Navigation active="workstation" onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "Deploy" })).toBeDefined();
  });

  it("marks only the active tab with aria-current", () => {
    render(<Navigation active="workstation" onChange={() => {}} />);
    const activeButton = screen.getByRole("button", {
      name: "Workstation",
    });
    expect(activeButton.getAttribute("aria-current")).toBe("page");
    const otherLabels = [
      "Strategies",
      "Research",
      "Studio",
      "Operations",
      "Deploy",
    ];
    for (const label of otherLabels) {
      expect(
        screen.getByRole("button", { name: label }).getAttribute("aria-current"),
      ).toBeNull();
    }
  });
});

/* ------------------------------------------------------------------ */
/* Signal presentation on the mounted Navigation tab strip.           */
/* Contract: KRELL-SIGNAL-20261010.                                   */
/* ------------------------------------------------------------------ */

const SEVEN_VIEWS = [
  { id: "home", label: "Home" },
  { id: "workstation", label: "Workstation" },
  { id: "strategies", label: "Strategies" },
  { id: "research", label: "Research" },
  { id: "studio", label: "Studio" },
  { id: "operations", label: "Operations" },
  { id: "deployments", label: "Deploy" },
] as const;

describe("Navigation — scoped Signal presentation", () => {
  it("renders the seven existing views in order inside the scoped nav root", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    const nav = screen.getByTestId("kbot-nav");
    expect(nav).toBeInstanceOf(HTMLElement);
    expect(nav.className).toContain("kbot-shell__nav-root");
    const items = Array.from(
      nav.querySelectorAll<HTMLButtonElement>(".kbot-nav__item"),
    );
    expect(items.map((button) => button.textContent?.trim())).toEqual(
      SEVEN_VIEWS.map((view) => view.label),
    );
    for (const item of items) {
      expect(item.className).toContain("kbot-shell__nav-item");
    }
  });

  it("keeps the shared strip classes, data-testid and ARIA on the active item", () => {
    render(<Navigation active="research" onChange={() => {}} />);
    const nav = screen.getByTestId("kbot-nav");
    expect(nav.className).toContain("kbot-nav");
    const active = screen.getByRole("button", { name: "Research" });
    expect(active.getAttribute("aria-pressed")).toBe("true");
    expect(active.getAttribute("aria-current")).toBe("page");
    expect(active.className).toContain("kbot-nav__item--active");
    expect(active.className).toContain("kbot-shell__nav-item--active");
    for (const label of ["Home", "Workstation", "Strategies"]) {
      const other = screen.getByRole("button", { name: label });
      expect(other.getAttribute("aria-pressed")).toBe("false");
      expect(other.className).not.toContain("kbot-shell__nav-item--active");
    }
  });

  it("reports view changes through the existing onChange wiring", () => {
    const onChange = vi.fn();
    render(<Navigation active="home" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Deploy" }));
    expect(onChange).toHaveBeenCalledWith("deployments");
    fireEvent.click(screen.getByRole("button", { name: "Studio" }));
    expect(onChange).toHaveBeenCalledWith("studio");
  });

  it("renders the seafoam Local preview badge below the tab row", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    const badge = screen.getByTestId("nav-local-preview");
    expect(badge.textContent?.trim()).toBe("Local preview");
    expect(badge.className).toContain("kbot-shell__nav-preview");
    const caption = screen.getByTestId("nav-local-preview-note");
    expect(caption.textContent).toContain("Live trading unavailable");
    // The badge sits inside the scoped root, below the tab row.
    const root = screen.getByTestId("kbot-nav");
    expect(root.contains(badge)).toBe(true);
    const tabs = root.querySelectorAll(".kbot-nav__item");
    expect(tabs.length).toBe(SEVEN_VIEWS.length);
    const note = caption.closest(".kbot-shell__nav-note");
    expect(note).toBe(root.lastElementChild);
    expect(badge.compareDocumentPosition(tabs[tabs.length - 1])).toBe(
      Node.DOCUMENT_POSITION_PRECEDING,
    );
  });
});

/* ------------------------------------------------------------------ */
/* Scoped Signal stylesheet (.kbot-shell__nav-root)                   */
/* ------------------------------------------------------------------ */

let cssCache = "";

function readStylesheet(): string {
  if (cssCache === "") {
    cssCache = readFileSync(join(here, "Navigation.signal.css"), "utf8");
  }
  return cssCache;
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "");
}

type CssBlock = { selector: string; declarations: string };

function selectorBlocks(source: string): CssBlock[] {
  const blocks: CssBlock[] = [];
  const pattern = /([^{}]+)\{([^{}]*)\}/g;
  let match = pattern.exec(source);
  while (match) {
    blocks.push({ selector: match[1].trim(), declarations: match[2] });
    match = pattern.exec(source);
  }
  return blocks;
}

function selectorMatches(selector: string, wanted: string): boolean {
  return selector
    .split(",")
    .some((part) => part.trim().split(/\s+/).includes(wanted));
}

type MediaQueryBlock = { query: string; body: string };

function splitMedia(source: string): {
  base: string;
  media: MediaQueryBlock[];
} {
  const media: MediaQueryBlock[] = [];
  let base = "";
  let i = 0;
  while (i < source.length) {
    const at = source.indexOf("@media", i);
    if (at === -1) {
      base += source.slice(i);
      break;
    }
    base += source.slice(i, at);
    const open = source.indexOf("{", at);
    const query = source.slice(at, open);
    let depth = 1;
    let j = open + 1;
    while (j < source.length && depth > 0) {
      if (source[j] === "{") {
        depth += 1;
      } else if (source[j] === "}") {
        depth -= 1;
      }
      j += 1;
    }
    media.push({ query, body: source.slice(open + 1, j - 1) });
    i = j;
  }
  return { base, media };
}

function blocksFor(css: string, selector: string): CssBlock[] {
  const { base, media } = splitMedia(css);
  const matched: CssBlock[] = [];
  for (const block of selectorBlocks(base)) {
    if (selectorMatches(block.selector, selector)) {
      matched.push(block);
    }
  }
  for (const block of media) {
    for (const rule of selectorBlocks(block.body)) {
      if (selectorMatches(rule.selector, selector)) {
        matched.push({
          ...rule,
          selector: `${block.query} ${rule.selector}`,
        });
      }
    }
  }
  return matched;
}

function declarationValue(
  declarations: string,
  property: string,
): string | null {
  const pattern = new RegExp(
    `(?:^|;)\\s*${property}\\s*:\\s*([^;]+)\\s*(?:;|$)`,
  );
  const match = declarations.match(pattern);
  return match ? match[1].trim() : null;
}

describe("Navigation — scoped Signal stylesheet", () => {
  it("scopes every rule under .kbot-shell__nav-root", () => {
    const css = stripComments(readStylesheet());
    const blocks = selectorBlocks(css);
    expect(blocks.length).toBeGreaterThan(0);
    for (const block of blocks) {
      expect(block.selector).toContain(".kbot-shell__nav-root");
    }
  });

  it("frames the strip as a panel surface in Manrope with restrained borders", () => {
    const css = stripComments(readStylesheet());
    const root = blocksFor(css, ".kbot-shell__nav-root");
    const declarations = root.map((block) => block.declarations).join(";");
    expect(declarationValue(declarations, "font-family")).toContain("Manrope");
    expect(declarations).toContain("var(--line");
    expect(declarations).toContain("var(--surface");
  });

  it("marks the active tab with the seafoam indicator and sage text", () => {
    const css = stripComments(readStylesheet());
    const active = blocksFor(css, ".kbot-shell__nav-item--active");
    expect(active.length).toBeGreaterThanOrEqual(1);
    const declarations = active.map((block) => block.declarations).join(";");
    expect(declarations).toContain("var(--seafoam");
    expect(declarations).toContain("var(--sage");
  });

  it("styles hover through the supplied text token without new colors", () => {
    const css = stripComments(readStylesheet());
    const hover = blocksFor(css, ".kbot-shell__nav-root");
    const hoverRule = hover.find((block) =>
      block.selector.includes(":hover"),
    );
    expect(hoverRule).toBeDefined();
    expect(hoverRule?.declarations).toContain("var(--text");
  });

  it("colors the Local preview badge seafoam", () => {
    const css = stripComments(readStylesheet());
    const badge = blocksFor(css, ".kbot-shell__nav-preview");
    expect(badge.length).toBeGreaterThanOrEqual(1);
    const declarations = badge.map((block) => block.declarations).join(";");
    expect(declarations).toContain("var(--seafoam");
  });

  it("keeps a >=44px tap target on small viewports", () => {
    const css = stripComments(readStylesheet());
    const { media } = splitMedia(css);
    const narrow = media.find((block) =>
      block.query.includes("max-width"),
    );
    expect(narrow).toBeDefined();
    const items = blocksFor(narrow?.body ?? "", ".kbot-shell__nav-item");
    const declarations = items.map((block) => block.declarations).join(";");
    const height = declarationValue(declarations, "min-height");
    expect(height).not.toBeNull();
    expect(parseInt(height ?? "0", 10)).toBeGreaterThanOrEqual(44);
  });

  it("introduces no new color literals beyond the shared tokens", () => {
    const css = stripComments(readStylesheet());
    for (const block of selectorBlocks(css)) {
      const hexes = block.declarations.match(/#[0-9a-fA-F]{3,8}\b/g) ?? [];
      for (const hex of hexes) {
        // Only token fallback literals inherited from tokens.css are allowed.
        expect([
          "#0e1c29",
          "#14222e",
          "#18354a",
          "#22465d",
          "#e9f0f5",
          "#abc4d8",
          "#a8d8d1",
          "#b3dda8",
          "#cc9689",
        ]).toContain(hex.toLowerCase());
      }
    }
  });
});
