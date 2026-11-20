import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MORE_VIEWS, Navigation, PRIMARY_VIEWS } from "./Navigation";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function openMore(): void {
  const toggle = screen.getByTestId("kbot-nav-more-toggle");
  if (toggle.getAttribute("aria-expanded") !== "true") {
    fireEvent.click(toggle);
  }
}

describe("Navigation — workstation views", () => {
  it("renders Workspace first among primary tabs and exposes More overflow", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    const primary = screen.getByTestId("kbot-nav-primary");
    const primaryLabels = Array.from(
      primary.querySelectorAll<HTMLButtonElement>(".kbot-nav__item"),
    ).map((button) => button.textContent?.trim());
    expect(primaryLabels).toEqual(PRIMARY_VIEWS.map((view) => view.label));
    expect(primaryLabels[0]).toBe("Workspace");
    expect(screen.getByTestId("kbot-nav-more-toggle")).toBeDefined();
    expect(screen.getByTestId("kbot-nav-more").getAttribute("data-open")).toBe(
      "0",
    );
    for (const label of PRIMARY_VIEWS.map((view) => view.label)) {
      expect(screen.getByRole("button", { name: label })).toBeDefined();
    }
  });

  it("marks Home with aria-current when active and clears the others", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    expect(
      screen.getByRole("button", { name: "Workspace" }).getAttribute("aria-current"),
    ).toBe("page");
    for (const label of ["Run", "Strategies", "Packs", "Settings"]) {
      expect(
        screen.getByRole("button", { name: label }).getAttribute("aria-current"),
      ).toBeNull();
    }
  });

  it("reports the Home selection through onChange", () => {
    const onChange = vi.fn();
    render(<Navigation active="workstation" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Workspace" }));
    expect(onChange).toHaveBeenCalledWith("home");
  });

  it("renders primary nav labels including Run and Settings", () => {
    render(<Navigation active="workstation" onChange={() => {}} />);
    for (const label of ["Run", "Strategies", "Packs", "Settings", "More"]) {
      expect(screen.getByRole("button", { name: label })).toBeDefined();
    }
  });

  it("exposes More destinations when More is expanded", () => {
    render(<Navigation active="workstation" onChange={() => {}} />);
    openMore();
    expect(screen.getByRole("button", { name: "Deploy" })).toBeDefined();
    for (const view of MORE_VIEWS) {
      expect(screen.getByRole("button", { name: view.label })).toBeDefined();
    }
  });

  it("marks only the active tab with aria-current", () => {
    render(<Navigation active="workstation" onChange={() => {}} />);
    const activeButton = screen.getByRole("button", {
      name: "Run",
    });
    expect(activeButton.getAttribute("aria-current")).toBe("page");
    for (const label of ["Strategies", "Packs", "Settings", "Workspace"]) {
      expect(
        screen.getByRole("button", { name: label }).getAttribute("aria-current"),
      ).toBeNull();
    }
  });

  it("keeps More open and marks aria-current when a More view is active", () => {
    render(<Navigation active="studio" onChange={() => {}} />);
    expect(screen.getByTestId("kbot-nav-more").getAttribute("data-open")).toBe(
      "1",
    );
    expect(screen.getByTestId("kbot-nav-more-toggle").getAttribute("aria-expanded")).toBe(
      "true",
    );
    expect(
      screen.getByRole("button", { name: "Strategy studio" }).getAttribute(
        "aria-current",
      ),
    ).toBe("page");
  });
});

/* ------------------------------------------------------------------ */
/* Signal presentation on the mounted Navigation tab strip.           */
/* Contract: KRELL-SIGNAL-20261010.                                   */
/* ------------------------------------------------------------------ */

describe("Navigation — scoped Signal presentation", () => {
  it("renders primary views plus More toggle inside the scoped nav root", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    const nav = screen.getByTestId("kbot-nav");
    expect(nav).toBeInstanceOf(HTMLElement);
    expect(nav.className).toContain("kbot-shell__nav-root");
    const primaryItems = Array.from(
      screen
        .getByTestId("kbot-nav-primary")
        .querySelectorAll<HTMLButtonElement>(".kbot-nav__item"),
    );
    expect(primaryItems.map((button) => button.textContent?.trim())).toEqual(
      PRIMARY_VIEWS.map((view) => view.label),
    );
    for (const item of primaryItems) {
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
    for (const label of ["Workspace", "Run", "Strategies"]) {
      const other = screen.getByRole("button", { name: label });
      expect(other.getAttribute("aria-pressed")).toBe("false");
      expect(other.className).not.toContain("kbot-shell__nav-item--active");
    }
  });

  it("reports view changes through the existing onChange wiring", () => {
    const onChange = vi.fn();
    render(<Navigation active="home" onChange={onChange} />);
    openMore();
    fireEvent.click(screen.getByRole("button", { name: "Deploy" }));
    expect(onChange).toHaveBeenCalledWith("deployments");
    fireEvent.click(screen.getByRole("button", { name: "Strategy studio" }));
    expect(onChange).toHaveBeenCalledWith("studio");
  });

  it("collapses More when a primary tab is clicked or becomes active", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <Navigation active="research" onChange={onChange} />,
    );
    expect(screen.getByTestId("kbot-nav-more").getAttribute("data-open")).toBe(
      "1",
    );
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(onChange).toHaveBeenCalledWith("workstation");
    rerender(<Navigation active="workstation" onChange={onChange} />);
    expect(screen.getByTestId("kbot-nav-more").getAttribute("data-open")).toBe(
      "0",
    );
    expect(
      screen.getByTestId("kbot-nav-more-toggle").getAttribute("aria-expanded"),
    ).toBe("false");
  });

  it("omits duplicate Local preview badges from the nav strip (StatusStrip is the single status pill)", () => {
    render(<Navigation active="home" onChange={() => {}} />);
    expect(screen.queryByTestId("nav-local-preview")).toBeNull();
    expect(screen.queryByTestId("nav-local-preview-note")).toBeNull();
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

  it("scrolls primary tabs horizontally on narrow viewports without wrapping into tall rows", () => {
    const css = stripComments(readStylesheet());
    const { media } = splitMedia(css);
    const narrow = media.find((block) => block.query.includes("max-width"));
    expect(narrow).toBeDefined();
    expect(narrow?.body).toContain("flex-wrap: nowrap");
    expect(narrow?.body).toContain("overflow-x: auto");
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
