/**
 * LivePreflight — Signal presentation slice (KRELL-SIGNAL-20261010).
 *
 * These tests pin the approved Signal presentation for the mounted
 * LivePreflight panel on the Workstation Deployments surface, next to
 * the already-migrated paper/operations/strategies/studio/shell
 * surfaces:
 *
 *  - a scoped `.kbot-feature__live-preflight-root` wrapper (same
 *    feature-root vocabulary as PaperStatusCsvExport) with no legacy
 *    `kbot-live-preflight` palette or classnames left in the tree;
 *  - the request form keeps its frozen field set with muted uppercase
 *    micro-label captions and restrained technical mono inputs;
 *  - "Run preflight" is the one affirmative primary, so it carries the
 *    sage treatment, with an honest disabled affordance while pending;
 *  - the verdict panel keeps the verbatim backend text (code label, ok
 *    flag, message, account_id, revision_id) on a grouped surface
 *    panel; sage reinforces an ok verdict, coral a refusal, and the
 *    text alone always carries the state;
 *  - a failed request renders as a scoped alert on a muted panel
 *    surface with the coral-derived caution tone, never sage;
 *  - every control keeps a >=44px tap target on narrow (<=640px)
 *    viewports and a 2px seafoam focus-visible ring.
 *
 * jsdom has no layout engine, so the containment/tap-target proofs
 * resolve the *actual shipped* declarations from
 * LivePreflight.signal.css (same approach as
 * LastRunsPanel.signal.test.tsx and GraphCanvas.signal.test.tsx). They
 * fail loudly when the stylesheet or its structural classes are
 * missing, so the suite is RED on the old plain-div presentation and
 * GREEN once the Signal slice ships. Real mounted measurements at
 * 1600x900 and 390x844 are captured by the browser evidence harness
 * outside this repository.
 *
 * Transport note: every client here is an in-memory vi.fn() fake
 * standing in for the loopback command API. No real venue/engine
 * state, keys, orders or fills are exercised or implied by these
 * tests. The existing LivePreflight.test.ts and
 * preflightCodeLabel.test.ts surfaces stay untouched.
 */

import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LivePreflight } from "./LivePreflight";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const ROOT = "kbot-feature__live-preflight-root";

async function renderAndSubmit(
  body: Record<string, unknown>,
): Promise<void> {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body));
  vi.stubGlobal("fetch", fetchMock);
  render(<LivePreflight />);
  fireEvent.change(await screen.findByTestId("live-preflight-account"), {
    target: { value: "acct-1" },
  });
  fireEvent.change(screen.getByTestId("live-preflight-revision"), {
    target: { value: "rev-1" },
  });
  fireEvent.click(screen.getByTestId("live-preflight-submit"));
  await waitFor(() => {
    expect(screen.getByTestId("live-preflight-result")).toBeDefined();
  });
}

/* ------------------------------------------------------------------ */
/* Stylesheet reader (shipped CSS, not an expectation string)          */
/* ------------------------------------------------------------------ */

let cssCache = "";

function readStylesheet(): string {
  if (cssCache === "") {
    cssCache = readFileSync(join(here, "LivePreflight.signal.css"), "utf8");
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

type MediaQueryBlock = { query: string; body: string };

function splitMedia(source: string): { base: string; media: MediaQueryBlock[] } {
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
        matched.push({ ...rule, selector: `${block.query} ${rule.selector}` });
      }
    }
  }
  return matched;
}

function selectorMatches(selectorList: string, selector: string): boolean {
  return selectorList
    .split(",")
    .some((part) => part.trim().endsWith(selector));
}

/* ------------------------------------------------------------------ */
/* 1. Scoped wrapper: no legacy palette left                           */
/* ------------------------------------------------------------------ */

describe("LivePreflight Signal layout — scoped wrapper", () => {
  it("mounts the panel under the .kbot-feature__live-preflight-root scope", () => {
    render(<LivePreflight />);
    const panel = screen.getByTestId("live-preflight-panel");
    expect(panel.className).toContain(ROOT);
    expect(panel.getAttribute("role")).toBe("region");
    expect(panel.getAttribute("aria-label")).toBe("Live preflight");
  });

  it("names the header 'Live preflight' inside the scoped root", () => {
    render(<LivePreflight />);
    const title = screen.getByRole("heading", { level: 2, name: "Live preflight" });
    expect(title.className).toContain(`${ROOT}__title`);
    expect(title.closest(`.${ROOT}`)).not.toBeNull();
  });

  it("imports the Signal stylesheet from LivePreflight.tsx", () => {
    const source = readFileSync(resolve(here, "LivePreflight.tsx"), "utf8");
    expect(source).toMatch(/import\s+"\.\/LivePreflight\.signal\.css"/);
  });

  it("leaves no legacy kbot-live-preflight class or palette in the mounted tree", () => {
    render(<LivePreflight />);
    const panel = screen.getByTestId("live-preflight-panel");
    const classNames = Array.from(
      panel.querySelectorAll("[class]"),
    ).map((node) => node.getAttribute("class") ?? "");
    classNames.push(panel.className);
    for (const name of classNames) {
      expect(name).not.toMatch(/(^|\s)kbot-live-preflight/);
    }
  });

  it("reuses only the approved Signal tokens — no new palette, nothing remote", () => {
    const css = readStylesheet();
    for (const token of [
      "--surface",
      "--panel",
      "--line",
      "--text",
      "--muted",
      "--seafoam",
      "--sage",
      "--coral",
      "--font-ui",
      "--font-mono",
      "--radius-panel",
      "--radius-control",
    ]) {
      expect(css).toContain(`var(${token}`);
    }
    expect(css).not.toMatch(/@import|https?:\/\//);
    for (const retired of ["#5ce1ff", "#c6ff3d", "#07090d", "#72f6b0"]) {
      expect(css.toLowerCase()).not.toContain(retired);
    }
    // Every hex literal is one of the approved palette/semantic values
    // from tokens.css (as fallbacks), not a newly invented color.
    const approved = new Set([
      "#0e1c29",
      "#14222e",
      "#18354a",
      "#22465d",
      "#e9f0f5",
      "#abc4d8",
      "#a8d8d1",
      "#b3dda8",
      "#cc9689",
      "#2b271f",
      "#736044",
      "#e2c193",
      "#e0a296",
      "#7a5348",
      "#172a1d",
      "#ffffff",
    ]);
    const hexes = css.toLowerCase().match(/#[0-9a-f]{6}\b/g) ?? [];
    for (const hex of hexes) {
      expect(approved.has(hex)).toBe(true);
    }
  });
});

/* ------------------------------------------------------------------ */
/* 2. Request form: frozen field set                                   */
/* ------------------------------------------------------------------ */

describe("LivePreflight Signal layout — request form", () => {
  it("styles each frozen field as a scoped caption with a mono input", () => {
    render(<LivePreflight />);
    for (const id of ["live-preflight-account", "live-preflight-revision"]) {
      const input = screen.getByTestId(id);
      expect(input.className).toContain(`${ROOT}__input`);
      const field = input.closest("label");
      expect(field?.className).toContain(`${ROOT}__field`);
    }
    const mode = screen.getByTestId("live-preflight-mode");
    expect(mode.className).toContain(`${ROOT}__input`);
    expect(mode.tagName).toBe("SELECT");
  });

  it("ships the muted uppercase micro-label caption in the stylesheet", () => {
    const css = stripComments(readStylesheet());
    const blocks = blocksFor(css, `${ROOT}__field`);
    expect(blocks.length).toBeGreaterThanOrEqual(1);
    const declarations = blocks.map((b) => b.declarations).join(";");
    expect(declarations).toContain("var(--muted");
    expect(declarations).toMatch(/text-transform:\s*uppercase/);
    expect(declarations).toMatch(/font-weight:\s*700/);
  });

  it("ships the restrained technical mono input on the navy canvas", () => {
    const css = stripComments(readStylesheet());
    const blocks = blocksFor(css, `${ROOT}__input`);
    expect(blocks.length).toBeGreaterThanOrEqual(1);
    const declarations = blocks.map((b) => b.declarations).join(";");
    expect(declarations).toContain("var(--font-mono");
    expect(declarations).toContain("var(--navy");
    expect(declarations).toContain("var(--line");
    expect(declarations).toMatch(/border-radius:\s*var\(--radius-control/);
  });
});

/* ------------------------------------------------------------------ */
/* 3. Run preflight: the one sage affirmative primary                  */
/* ------------------------------------------------------------------ */

describe("LivePreflight Signal layout — affirmative primary action", () => {
  it("styles Run preflight as the scoped primary action", () => {
    render(<LivePreflight />);
    const button = screen.getByTestId("live-preflight-submit");
    expect(button.className).toContain(`${ROOT}__action`);
    expect(button.textContent).toBe("Run preflight");
  });

  it("ships the sage affirmative treatment with an honest disabled state", () => {
    const css = stripComments(readStylesheet());
    const blocks = blocksFor(css, `${ROOT}__action`);
    expect(blocks.length).toBeGreaterThanOrEqual(1);
    const declarations = blocks.map((b) => b.declarations).join(";");
    expect(declarations).toContain("var(--sage");
    expect(declarations).toContain("var(--action-primary-text");

    const disabled = blocksFor(css, `${ROOT}__action:disabled`);
    expect(disabled.length).toBeGreaterThanOrEqual(1);
    const disabledCss = disabled.map((b) => b.declarations).join(";");
    expect(disabledCss).toMatch(/cursor:\s*not-allowed/);
    expect(disabledCss).not.toContain("var(--sage");
  });
});

/* ------------------------------------------------------------------ */
/* 4. Verdict panel: verbatim backend text, reinforced only            */
/* ------------------------------------------------------------------ */

describe("LivePreflight Signal layout — verdict panel", () => {
  it("keeps the verbatim ok verdict on the grouped surface panel with the sage tone", async () => {
    await renderAndSubmit({
      schema_version: "1",
      code: "ok",
      ok: true,
      message: "preflight ok",
      effect: "none",
      account_id: "acct-1",
      revision_id: "rev-1",
    });

    const result = screen.getByTestId("live-preflight-result");
    expect(result.className).toContain(`${ROOT}__result`);
    expect(result.textContent).toMatch(/code: Ok/);
    expect(result.textContent).toMatch(/ok: true/);
    expect(result.textContent).toMatch(/preflight ok/);
    expect(result.textContent).toMatch(/account_id: acct-1/);
    expect(result.textContent).toMatch(/revision_id: rev-1/);

    const lines = result.querySelectorAll(`.${ROOT}__result-line`);
    expect(lines.length).toBe(5);
    expect(lines[0]?.className).toContain(`${ROOT}__result-line--ok`);
    expect(lines[1]?.className).toContain(`${ROOT}__result-line--ok`);
    // Identifiers keep the restrained technical mono treatment.
    expect(lines[3]?.className).toContain(`${ROOT}__result-line--tech`);
    expect(lines[4]?.className).toContain(`${ROOT}__result-line--tech`);
  });

  it("keeps a refusal verdict honest with the coral tone, never sage", async () => {
    await renderAndSubmit({
      schema_version: "1",
      code: "mode_not_sandbox",
      ok: false,
      message: "live mode is refused: sandbox only",
      effect: "refused",
    });

    const result = screen.getByTestId("live-preflight-result");
    expect(result.textContent).toMatch(/code: Mode not sandbox/);
    expect(result.textContent).toMatch(/ok: false/);

    const lines = result.querySelectorAll(`.${ROOT}__result-line`);
    expect(lines[0]?.className).toContain(`${ROOT}__result-line--refused`);
    expect(lines[0]?.className).not.toContain(`${ROOT}__result-line--ok`);
    expect(lines[1]?.className).toContain(`${ROOT}__result-line--refused`);
    for (const line of lines) {
      expect(line.className).not.toContain(`${ROOT}__result-line--ok`);
    }
  });

  it("ships the verdict panel as a grouped surface panel in the stylesheet", () => {
    const css = stripComments(readStylesheet());
    const blocks = blocksFor(css, `${ROOT}__result`);
    expect(blocks.length).toBeGreaterThanOrEqual(1);
    const declarations = blocks.map((b) => b.declarations).join(";");
    expect(declarations).toContain("var(--surface");
    expect(declarations).toMatch(/border[^;]*var\(--line/);
    expect(declarations).toMatch(/radius/);
  });

  it("ships sage for ok and coral-derived danger for a refusal, never the reverse", () => {
    const css = stripComments(readStylesheet());
    const ok = blocksFor(css, `${ROOT}__result-line--ok`);
    expect(ok.length).toBeGreaterThanOrEqual(1);
    const okCss = ok.map((b) => b.declarations).join(";");
    expect(okCss).toContain("var(--sage");
    expect(okCss).not.toContain("var(--coral");

    const refused = blocksFor(css, `${ROOT}__result-line--refused`);
    expect(refused.length).toBeGreaterThanOrEqual(1);
    const refusedCss = refused.map((b) => b.declarations).join(";");
    expect(
      refusedCss.includes("var(--danger-text") ||
        refusedCss.includes("var(--coral"),
    ).toBe(true);
    expect(refusedCss).not.toContain("var(--sage");
  });

  it("ships the restrained technical mono identifier treatment", () => {
    const css = stripComments(readStylesheet());
    const tech = blocksFor(css, `${ROOT}__result-line--tech`);
    expect(tech.length).toBeGreaterThanOrEqual(1);
    const techCss = tech.map((b) => b.declarations).join(";");
    expect(techCss).toContain("var(--font-mono");
    expect(techCss).toContain("var(--muted");
  });
});

/* ------------------------------------------------------------------ */
/* 5. Failed request: honest alert, coral, never sage                  */
/* ------------------------------------------------------------------ */

describe("LivePreflight Signal layout — failed request alert", () => {
  it("renders the read failure as a scoped alert without inventing a verdict", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, 500));
    vi.stubGlobal("fetch", fetchMock);
    render(<LivePreflight />);

    fireEvent.click(screen.getByTestId("live-preflight-submit"));
    const error = await screen.findByTestId("live-preflight-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toBe("Preflight request failed");
    expect(error.className).toContain(`${ROOT}__error`);
    expect(screen.queryByTestId("live-preflight-result")).toBeNull();
  });

  it("ships the muted panel surface with the coral-derived border, never sage", () => {
    const css = stripComments(readStylesheet());
    const blocks = blocksFor(css, `${ROOT}__error`);
    expect(blocks.length).toBeGreaterThanOrEqual(1);
    const declarations = blocks.map((b) => b.declarations).join(";");
    expect(declarations).toContain("var(--surface");
    expect(declarations).toMatch(/border[^;]*var\(--coral/);
    expect(
      declarations.includes("var(--danger-text") ||
        declarations.includes("var(--coral"),
    ).toBe(true);
    expect(declarations).not.toContain("var(--sage");
    expect(declarations).toMatch(/radius/);
  });
});

/* ------------------------------------------------------------------ */
/* 6. Focus, tap targets and width containment                         */
/* ------------------------------------------------------------------ */

describe("LivePreflight Signal layout — focus, targets and containment", () => {
  it("ships the 2px seafoam focus-visible ring for every control", () => {
    const css = stripComments(readStylesheet());
    expect(css).toMatch(
      new RegExp(
        `:is\\(button, input, select\\):focus-visible\\s*\\{[^}]*outline:\\s*2px solid var\\(--seafoam`,
      ),
    );
  });

  it("keeps the root width-contained so long identifiers never widen the page", () => {
    const css = stripComments(readStylesheet());
    const root = blocksFor(css, `.${ROOT}`);
    expect(root.length).toBeGreaterThanOrEqual(1);
    const declarations = root.map((b) => b.declarations).join(";");
    expect(declarationValue(declarations, "min-width")).toBe("0");
    const maxWidth = declarationValue(declarations, "max-width");
    const width = declarationValue(declarations, "width");
    expect(maxWidth === "100%" || width === "100%").toBe(true);
  });

  it("composes intentionally at 390px: stacked fields, 44px controls", () => {
    const css = stripComments(readStylesheet());
    const media = splitMedia(css).media;
    const narrow = media.find((block) =>
      block.query.includes("max-width: 640px"),
    );
    expect(narrow).toBeDefined();

    const narrowCss = narrow ? narrow.body : "";
    // Every ordinary control keeps a >=44px touch target.
    expect(narrowCss).toMatch(/min-height:\s*44px/);
    // The frozen field set stacks instead of overflowing.
    const stacked = selectorBlocks(narrowCss).find(
      (block) => block.selector.endsWith(`${ROOT}__form`),
    );
    expect(stacked).toBeDefined();
    expect(declarationValue(stacked?.declarations ?? "", "grid-template-columns")).toBe(
      "minmax(0, 1fr)",
    );
  });
});
