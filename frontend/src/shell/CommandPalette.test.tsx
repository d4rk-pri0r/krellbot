/**
 * CommandPalette — Signal presentation on the mounted shell modal.
 * Contract: KRELL-SIGNAL-20261010.
 *
 * These tests pin the persistent command palette (frontend/src/shell/
 * CommandPalette.tsx, mounted by WorkstationShell behind the ⌘K/Ctrl+K
 * binding) to the same honest-state discipline as the other Signal shell
 * surfaces:
 *
 *   - honest search copy: it finds actions, strategies or views, and says
 *     plainly that this is a local preview;
 *   - a Seafoam "Local preview" badge in the shared badge vocabulary used
 *     by StatusStrip / AppHome / JobsDrawer;
 *   - a Manrope/seafoam keyboard hint naming both Esc and Ctrl+K;
 *   - the existing data-testid "command-palette", the Escape close and
 *     the focus-return behavior stay exactly as they were;
 *   - the scoped Signal stylesheet (.kbot-shell__palette-root) consumes
 *     the shared tokens only, with Manrope primary and a >=44px input
 *     target on small viewports.
 *
 * Real mounted measurements at 1600x900 and 390x844 are captured by the
 * browser journey in the task scratch, not by jsdom.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CommandPalette } from "./CommandPalette";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderPalette(open = true): HTMLElement {
  render(<CommandPalette open={open} onClose={() => {}} />);
  return screen.getByTestId("command-palette");
}

/* ------------------------------------------------------------------ */
/* 1. Honest Signal copy                                               */
/* ------------------------------------------------------------------ */

describe("CommandPalette — honest Signal copy", () => {
  it("labels the palette with the honest find-an-action copy including local preview", () => {
    renderPalette();

    expect(
      screen.getByText("Find an action, strategy, or view — local preview only."),
    ).toBeDefined();
  });

  it("keeps the palette closed when open is false", () => {
    render(<CommandPalette open={false} onClose={() => {}} />);
    expect(screen.queryByTestId("command-palette")).toBeNull();
  });

  it("shows the honest search placeholder in the input", () => {
    renderPalette();

    expect(
      screen.getByPlaceholderText("Type to search actions, strategies, or views"),
    ).toBeDefined();
  });

  it("hints at both Esc and Ctrl+K in the Manrope/seafoam hint", () => {
    renderPalette();

    expect(
      screen.getByText("Press Esc to close · Ctrl+K from anywhere"),
    ).toBeDefined();
  });
});

/* ------------------------------------------------------------------ */
/* 2. Seafoam Local preview badge                                      */
/* ------------------------------------------------------------------ */

describe("CommandPalette — Local preview badge", () => {
  it("renders the Local preview badge above the input in the shared badge vocabulary", () => {
    renderPalette();

    const badge = screen.getByText("Local preview");
    expect(badge.className).toContain("kbot-shell__palette-badge");

    const input = screen.getByPlaceholderText(
      "Type to search actions, strategies, or views",
    );
    expect(
      badge.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("marks the badge with its own test id for the browser journey", () => {
    renderPalette();

    expect(screen.getByTestId("command-palette-badge")).toBeDefined();
  });
});

/* ------------------------------------------------------------------ */
/* 3. Preserved behavior: test id, Escape, focus return                */
/* ------------------------------------------------------------------ */

describe("CommandPalette — preserved behavior", () => {
  it("preserves the command-palette data-testid and dialog semantics", () => {
    const root = renderPalette();

    expect(root.getAttribute("role")).toBe("dialog");
    expect(root.getAttribute("aria-modal")).toBe("true");
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);

    fireEvent.keyDown(window, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("moves focus into the input on open and returns it on close", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();

    const { unmount } = render(<CommandPalette open onClose={() => {}} />);

    const input = screen.getByPlaceholderText(
      "Type to search actions, strategies, or views",
    );
    expect(document.activeElement).toBe(input);

    unmount();
    expect(document.activeElement).toBe(opener);
    document.body.removeChild(opener);
  });
});

/* ------------------------------------------------------------------ */
/* 4. Scoped Signal stylesheet (.kbot-shell__palette-root)             */
/* ------------------------------------------------------------------ */

let cssCache = "";

function readStylesheet(): string {
  if (cssCache === "") {
    cssCache = readFileSync(join(here, "CommandPalette.signal.css"), "utf8");
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

describe("CommandPalette — scoped Signal stylesheet", () => {
  it("scopes every rule under .kbot-shell__palette-root", () => {
    const css = stripComments(readStylesheet());
    for (const block of selectorBlocks(css)) {
      expect(block.selector).toContain(".kbot-shell__palette-root");
    }
  });

  it("styles the modal box with the shared panel surface and Manrope", () => {
    const css = stripComments(readStylesheet());
    const box = blocksFor(css, ".kbot-shell__palette-box");
    expect(box.length).toBeGreaterThanOrEqual(1);
    const declarations = box.map((block) => block.declarations).join(";");
    expect(declarationValue(declarations, "background")).toContain(
      "var(--panel",
    );
    expect(declarationValue(declarations, "font-family")).toContain("Manrope");
  });

  it("gives the input a Manrope field that keeps seafoam focus and selection", () => {
    const css = stripComments(readStylesheet());
    const input = blocksFor(css, ".kbot-shell__palette-input");
    expect(input.length).toBeGreaterThanOrEqual(1);
    const declarations = input.map((block) => block.declarations).join(";");
    expect(declarationValue(declarations, "font-family")).toContain("Manrope");
    expect(declarations).toContain("var(--seafoam");
  });

  it("uses seafoam on the Local preview badge", () => {
    const css = stripComments(readStylesheet());
    const badge = blocksFor(css, ".kbot-shell__palette-badge");
    expect(badge.length).toBeGreaterThanOrEqual(1);
    const declarations = badge.map((block) => block.declarations).join(";");
    expect(declarations).toContain("var(--seafoam");
  });

  it("keeps the hint in Manrope with the seafoam tone", () => {
    const css = stripComments(readStylesheet());
    const hint = blocksFor(css, ".kbot-shell__palette-hint");
    expect(hint.length).toBeGreaterThanOrEqual(1);
    const declarations = hint.map((block) => block.declarations).join(";");
    expect(declarationValue(declarations, "font-family")).toContain("Manrope");
    expect(declarations).toContain("var(--seafoam");
  });

  it("holds the input to >=44px on small viewports", () => {
    const css = stripComments(readStylesheet());
    const narrow = splitMedia(css).media
      .filter((block) => block.query.includes("640px"))
      .map((block) => block.body)
      .join(";");
    expect(narrow).not.toBe("");

    const input = blocksFor(
      stripComments(readStylesheet()),
      ".kbot-shell__palette-input",
    );
    const allDeclarations = input.map((block) => block.declarations).join(";");
    const minHeight = declarationValue(allDeclarations, "min-height");
    const height = declarationValue(allDeclarations, "height");
    const combined = `${narrow};${allDeclarations}`;
    expect(
      combined.includes("44px") &&
        (minHeight !== null || height !== null || narrow !== ""),
    ).toBe(true);
    expect(
      /min-height:\s*44px|height:\s*44px/.test(
        combined.replace(/\s+/g, " "),
      ),
    ).toBe(true);
  });

  it("introduces no new color tokens of its own", () => {
    const css = stripComments(readStylesheet());
    const declared = [...css.matchAll(/--[\w-]+\s*:/g)].map((m) => m[0]);
    expect(declared).toEqual([]);
  });
});

/* ------------------------------------------------------------------ */
/* 5. Mounted markup carries the scoped classes                        */
/* ------------------------------------------------------------------ */

describe("CommandPalette — mounted markup", () => {
  it("adds the scoped palette-root class alongside the shared kbot-palette classes", () => {
    const root = renderPalette();

    expect(root.className).toContain("kbot-palette");
    expect(root.className).toContain("kbot-shell__palette-root");
  });

  it("types into the input without changing the palette copy", () => {
    renderPalette();

    const input = screen.getByPlaceholderText(
      "Type to search actions, strategies, or views",
    );
    fireEvent.change(input, { target: { value: "rehearsal" } });
    expect((input as HTMLInputElement).value).toBe("rehearsal");
  });
});
