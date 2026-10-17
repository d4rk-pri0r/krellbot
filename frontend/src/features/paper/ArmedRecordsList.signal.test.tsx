/**
 * ArmedRecordsList — Signal presentation slice (KRELL-SIGNAL-20261010).
 *
 * These tests pin the approved Signal presentation for the mounted
 * armed-records surface below the already-migrated StatusPanel and
 * LastRunsPanel on the Workstation paper page:
 *
 *  - a header panel naming "Armed paper runs" carrying the real
 *    armed-run count chip read from the wire;
 *  - a list panel whose rows render the venue/mode/pack in restrained
 *    technical mono, the pair bold, and the entries state as a status
 *    chip (sage for "Entries active", coral-derived for
 *    "Entries paused") — the wire carries no timestamps, so no column
 *    invents one;
 *  - the selected row carries the seafoam selection affordance and a
 *    >=44px tap target; keyboard focus stays visible;
 *  - the explicit empty state ("No packs armed") sits on the
 *    coral-derived caution tone, and the loading/unavailable/error
 *    indicators sit on the muted panel surface;
 *  - the dense table scrolls inside its own region instead of widening
 *    the page, and the 390px composition stays width-contained.
 *
 * jsdom has no layout engine, so the containment/tap-target/focus
 * proofs resolve the *actual shipped* declarations from
 * ArmedRecordsList.signal.css (same approach as
 * LastRunsPanel.signal.test.tsx). They fail loudly when the stylesheet
 * or its structural classes are missing, so the suite is RED on the
 * old plain-table presentation and GREEN once the Signal slice ships.
 * Real mounted measurements at 1600x900 and 390x844 are captured by
 * the browser evidence harness outside this repository.
 *
 * Transport note: every client here is an in-memory vi.fn() fake
 * standing in for the loopback paper API. No real venue/engine state,
 * keys, orders or fills are exercised or implied by these tests.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ArmedRecordsList } from "./ArmedRecordsList";
import type {
  PaperArmedClient,
  PaperArmedRecord,
  PaperArmedView,
} from "./client";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function viewOf(records: PaperArmedRecord[]): PaperArmedView {
  return {
    schema_version: "1",
    armed: records.length > 0,
    records,
  };
}

function record(extra: Partial<PaperArmedRecord> = {}): PaperArmedRecord {
  return {
    venue: "kraken",
    pair: "SUIUSD",
    mode: "paper",
    pack_id: "trend-follow",
    entries_paused: false,
    ...extra,
  };
}

function makeClient(
  listArmed: PaperArmedClient["listArmed"],
): PaperArmedClient {
  return { listArmed };
}

async function renderList(
  client: PaperArmedClient,
): Promise<void> {
  render(<ArmedRecordsList client={client} />);
  await waitFor(() => {
    expect(screen.getAllByTestId("paper-armed-row").length).toBeGreaterThan(0);
  });
}

/* ------------------------------------------------------------------ */
/* Stylesheet reader (shipped CSS, not an expectation string)          */
/* ------------------------------------------------------------------ */

let cssCache = "";

function readStylesheet(): string {
  if (cssCache === "") {
    cssCache = readFileSync(join(here, "ArmedRecordsList.signal.css"), "utf8");
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
/* 1. Header panel: "Armed paper runs" + armed-run count chip          */
/* ------------------------------------------------------------------ */

describe("ArmedRecordsList Signal layout — header panel", () => {
  it("names the header 'Armed paper runs' and renders the count chip with the real armed total", async () => {
    await renderList(
      makeClient(
        vi.fn().mockResolvedValue(
          viewOf([
            record(),
            record({ venue: "coinbase", pair: "BTC-USD", pack_id: "mean-revert" }),
          ]),
        ),
      ),
    );

    const title = screen.getByRole("heading", {
      level: 2,
      name: "Armed paper runs",
    });
    expect(title).toBeDefined();
    expect(title.className).toContain("kbot-paper-armed__title");

    const count = screen.getByTestId("paper-armed-count");
    expect(count.textContent).toBe("2 armed runs");
    expect(count.className).toContain("kbot-paper-armed__count");
  });

  it("uses the singular form for exactly one armed run", async () => {
    await renderList(makeClient(vi.fn().mockResolvedValue(viewOf([record()]))));

    expect(screen.getByTestId("paper-armed-count").textContent).toBe(
      "1 armed run",
    );
  });

  it("keeps the count chip truthful for zero armed runs instead of hiding the fact", async () => {
    render(
      <ArmedRecordsList client={makeClient(vi.fn().mockResolvedValue(viewOf([])))} />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("paper-armed-empty")).toBeDefined();
    });

    expect(screen.getByTestId("paper-armed-count").textContent).toBe(
      "0 armed runs",
    );
  });

  it("does not claim an armed count while the list is still loading", () => {
    render(
      <ArmedRecordsList
        client={makeClient(
          vi.fn(() => new Promise<PaperArmedView>(() => undefined)),
        )}
      />,
    );

    expect(screen.getByTestId("paper-armed-loading")).toBeDefined();
    expect(screen.queryByTestId("paper-armed-count")).toBeNull();
  });

  it("does not claim an armed count when the read fails", async () => {
    render(
      <ArmedRecordsList
        client={makeClient(vi.fn().mockRejectedValue(new Error("paper armed list failed: 403")))}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("paper-armed-unavailable")).toBeDefined();
    });

    expect(screen.queryByTestId("paper-armed-count")).toBeNull();
  });
});

/* ------------------------------------------------------------------ */
/* 2. List panel rows: mono identifiers, bold pair, status chip        */
/* ------------------------------------------------------------------ */

describe("ArmedRecordsList Signal layout — list panel rows", () => {
  it("renders the armed rows inside a grouped list panel below the header", async () => {
    await renderList(makeClient(vi.fn().mockResolvedValue(viewOf([record()]))));

    const panel = screen.getByTestId("paper-armed-list-panel");
    const rows = within(panel).getAllByTestId("paper-armed-row");
    expect(rows).toHaveLength(1);
    expect(panel.className).toContain("kbot-paper-armed__panel");
  });

  it("keeps venue, mode and pack in restrained technical mono and the pair bold", async () => {
    await renderList(
      makeClient(
        vi.fn().mockResolvedValue(
          viewOf([
            record({ venue: "kraken", pair: "SUIUSD", pack_id: "trend-follow" }),
          ]),
        ),
      ),
    );

    const row = screen.getByTestId("paper-armed-row");
    expect(row.textContent).toContain("kraken");
    expect(row.textContent).toContain("SUIUSD");
    expect(row.textContent).toContain("trend-follow");

    const venue = within(row).getByText("kraken");
    expect(venue.className).toContain("kbot-paper-armed__mono");
    const pair = within(row).getByText("SUIUSD");
    expect(pair.className).toContain("kbot-paper-armed__pair");
    const pack = within(row).getByText("trend-follow");
    expect(pack.className).toContain("kbot-paper-armed__mono");
  });

  it("renders the entries state as a status chip: sage for active, coral for paused", async () => {
    await renderList(
      makeClient(
        vi.fn().mockResolvedValue(
          viewOf([
            record({ pair: "SUIUSD", entries_paused: false }),
            record({ pair: "DOTUSD", entries_paused: true }),
          ]),
        ),
      ),
    );

    const active = screen.getByTestId("paper-armed-status-kraken-SUIUSD");
    expect(active.textContent).toBe("Entries active");
    expect(active.className).toContain("kbot-paper-armed__chip--sage");

    const paused = screen.getByTestId("paper-armed-status-kraken-DOTUSD");
    expect(paused.textContent).toBe("Entries paused");
    expect(paused.className).toContain("kbot-paper-armed__chip--coral");
  });

  it("marks the selected row with the seafoam selection affordance", async () => {
    await renderList(makeClient(vi.fn().mockResolvedValue(viewOf([record()]))));

    const row = screen.getAllByTestId("paper-armed-row")[0];
    expect(row.className).not.toContain("kbot-paper-armed__row--selected");
    fireEvent.click(row);

    const selectedRow = screen.getAllByTestId("paper-armed-row")[0];
    expect(selectedRow.className).toContain("kbot-paper-armed__row--selected");
    expect(screen.getByTestId("paper-armed-detail")).toBeDefined();
  });

  it("makes every armed row a keyboard-focusable affordance", async () => {
    await renderList(makeClient(vi.fn().mockResolvedValue(viewOf([record()]))));

    const row = screen.getAllByTestId("paper-armed-row")[0];
    expect(row.getAttribute("tabindex")).toBe("0");
  });
});

/* ------------------------------------------------------------------ */
/* 3. Shipped stylesheet: rows, chips, focus, state surfaces           */
/* ------------------------------------------------------------------ */

describe("ArmedRecordsList Signal layout — shipped stylesheet", () => {
  it("gives every armed row a >=44px tap target", () => {
    const css = stripComments(readStylesheet());
    const rows = blocksFor(css, ".kbot-paper-armed__row");
    expect(rows.length).toBeGreaterThanOrEqual(1);
    const declarations = rows.map((block) => block.declarations).join(";");
    const height = declarationValue(declarations, "height");
    const minHeight = declarationValue(declarations, "min-height");
    expect(
      height === "44px" ||
        minHeight === "44px" ||
        (height !== null && /^\d+px$/.test(height) && parseInt(height, 10) >= 44) ||
        (minHeight !== null && parseInt(minHeight, 10) >= 44),
    ).toBe(true);
    expect(declarations).toMatch(/cursor:\s*pointer/);
  });

  it("shows the seafoam focus ring on rows and controls, not just a color change", () => {
    const css = stripComments(readStylesheet());
    const focusBlocks = blocksFor(css, ".kbot-paper-armed__row:focus-visible");
    expect(focusBlocks.length).toBeGreaterThanOrEqual(1);
    const focusCss = focusBlocks.map((block) => block.declarations).join(";");
    expect(focusCss).toMatch(/outline:\s*2px solid var\(--seafoam/);

    // Controls (refresh) keep their own seafoam focus ring; the
    // `:is(button, a)` pseudo-list is split on commas by the block
    // reader, so assert it directly against the shipped source.
    expect(css).toMatch(
      /:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--seafoam/,
    );
  });

  it("styles the sage and coral status chips from the shared tokens", () => {
    const css = stripComments(readStylesheet());

    const sage = blocksFor(css, ".kbot-paper-armed__chip--sage");
    expect(sage.length).toBeGreaterThanOrEqual(1);
    const sageCss = sage.map((block) => block.declarations).join(";");
    expect(sageCss).toContain("var(--sage");

    const coral = blocksFor(css, ".kbot-paper-armed__chip--coral");
    expect(coral.length).toBeGreaterThanOrEqual(1);
    const coralCss = coral.map((block) => block.declarations).join(";");
    expect(
      coralCss.includes("var(--coral") || coralCss.includes("var(--danger-text"),
    ).toBe(true);
  });

  it("keeps the selected row on the seafoam selection tone", () => {
    const css = stripComments(readStylesheet());
    const selected = blocksFor(css, ".kbot-paper-armed__row--selected");
    expect(selected.length).toBeGreaterThanOrEqual(1);
    const selectedCss = selected.map((block) => block.declarations).join(";");
    expect(selectedCss).toContain("var(--seafoam");
  });

  it("sits the loading and unavailable indicators on the muted panel surface", () => {
    const css = stripComments(readStylesheet());
    const blocks = blocksFor(css, ".kbot-paper-armed__empty");
    expect(blocks.length).toBeGreaterThanOrEqual(1);
    const declarations = blocks.map((block) => block.declarations).join(";");
    expect(declarations).toContain("var(--surface");
    expect(declarations).toMatch(/border[^;]*var\(--line/);
    expect(declarations).toMatch(/radius/);
    expect(declarations).toContain("var(--muted");
  });

  it("keeps the read-failure error in the coral-derived danger tone", () => {
    const css = stripComments(readStylesheet());
    const error = blocksFor(css, ".kbot-paper-armed__error");
    expect(error.length).toBeGreaterThanOrEqual(1);
    const errorCss = error.map((block) => block.declarations).join(";");
    expect(
      errorCss.includes("var(--danger-text") || errorCss.includes("var(--coral"),
    ).toBe(true);
    expect(errorCss).not.toContain("var(--sage");
  });
});

/* ------------------------------------------------------------------ */
/* 4. Explicit empty state on the coral-derived caution tone           */
/* ------------------------------------------------------------------ */

describe("ArmedRecordsList Signal layout — empty state", () => {
  it("renders the confirmed empty state inside the list panel with the coral-derived affordance", async () => {
    render(
      <ArmedRecordsList client={makeClient(vi.fn().mockResolvedValue(viewOf([])))} />,
    );
    const empty = await screen.findByTestId("paper-armed-empty");
    expect(empty.textContent).toMatch(/No packs armed/);

    const panel = screen.getByTestId("paper-armed-list-panel");
    expect(panel.contains(empty)).toBe(true);

    const css = stripComments(readStylesheet());
    const emptyBlocks = blocksFor(css, ".kbot-paper-armed__empty--none");
    expect(emptyBlocks.length).toBeGreaterThanOrEqual(1);
    const emptyCss = emptyBlocks.map((block) => block.declarations).join(";");
    expect(
      emptyCss.includes("var(--coral") || emptyCss.includes("var(--danger-text"),
    ).toBe(true);
    expect(emptyCss).not.toContain("var(--sage");
  });
});

/* ------------------------------------------------------------------ */
/* 5. Width containment at 390px (shipped declarations)                */
/* ------------------------------------------------------------------ */

describe("ArmedRecordsList Signal layout — width containment", () => {
  it("keeps the root width-contained so long pairs, venues or packs never widen the page", () => {
    const css = stripComments(readStylesheet());
    const root = blocksFor(css, ".kbot-paper-armed");
    expect(root.length).toBeGreaterThanOrEqual(1);
    const declarations = root.map((block) => block.declarations).join(";");
    expect(declarationValue(declarations, "min-width")).toBe("0");
    const maxWidth = declarationValue(declarations, "max-width");
    const width = declarationValue(declarations, "width");
    expect(maxWidth === "100%" || width === "100%").toBe(true);
  });

  it("wraps the dense table in its own internal scroll region", async () => {
    await renderList(makeClient(vi.fn().mockResolvedValue(viewOf([record()]))));

    const table = screen.getByTestId("paper-armed-table");
    const scroll = screen.getByTestId("paper-armed-scroll");
    expect(scroll.contains(table)).toBe(true);

    const css = stripComments(readStylesheet());
    const scrollBlocks = blocksFor(css, ".kbot-paper-armed__scroll");
    expect(scrollBlocks.length).toBeGreaterThanOrEqual(1);
    const scrollCss = scrollBlocks.map((block) => block.declarations).join(";");
    expect(scrollCss).toMatch(/overflow-x:\s*auto/);
    expect(scrollCss).toMatch(/max-width:\s*100%/);

    const tableBlocks = blocksFor(css, ".kbot-paper-armed__table");
    expect(tableBlocks.length).toBeGreaterThanOrEqual(1);
    expect(
      declarationValue(
        tableBlocks.map((block) => block.declarations).join(";"),
        "min-width",
      ),
    ).toMatch(/^\d+px$/);
  });

  it("composes intentionally at 390px: stacked header, 44px controls, contained table", () => {
    const css = stripComments(readStylesheet());
    const media = splitMedia(css).media;
    const narrow = media.find((block) =>
      block.query.includes("max-width: 640px"),
    );
    expect(narrow).toBeDefined();

    const narrowCss = narrow ? narrow.body : "";
    // Ordinary controls keep >=44px touch targets on narrow screens.
    expect(narrowCss).toMatch(/min-height:\s*44px/);
    // The dense armed table keeps an explicit internal-scroll min-width.
    const narrowTables = selectorBlocks(narrowCss).filter((block) =>
      block.selector.includes("kbot-paper-armed__table"),
    );
    expect(narrowTables.length).toBeGreaterThanOrEqual(1);
    for (const block of narrowTables) {
      expect(declarationValue(block.declarations, "min-width")).toMatch(/^\d+px$/);
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
/* 6. Refresh affordance keeps the truthful last-good-list behaviour   */
/* ------------------------------------------------------------------ */

describe("ArmedRecordsList Signal layout — refresh affordance", () => {
  it("keeps the refresh control in the header panel next to the count chip", async () => {
    await renderList(makeClient(vi.fn().mockResolvedValue(viewOf([record()]))));

    const head = screen.getByTestId("paper-armed-head");
    const refresh = within(head).getByRole("button", { name: /refresh/i });
    expect(refresh.className).toContain("kbot-paper-armed__action");
    expect(head.contains(screen.getByTestId("paper-armed-count"))).toBe(true);
  });

  it("keeps the last good rows visible when a refresh fails, with the refusal named", async () => {
    const listArmed = vi
      .fn<PaperArmedClient["listArmed"]>()
      .mockResolvedValueOnce(viewOf([record()]))
      .mockRejectedValueOnce(new Error("paper armed list failed: 503"));
    render(<ArmedRecordsList client={makeClient(listArmed)} />);
    await waitFor(() => {
      expect(screen.getAllByTestId("paper-armed-row")).toHaveLength(1);
    });

    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => {
      expect(listArmed).toHaveBeenCalledTimes(2);
    });

    expect(screen.getAllByTestId("paper-armed-row")).toHaveLength(1);
    expect(screen.getByTestId("paper-armed-refresh-error").textContent).toMatch(
      /503/,
    );
    // The count chip keeps reporting the last known list, not a failure.
    expect(screen.getByTestId("paper-armed-count").textContent).toBe(
      "1 armed run",
    );
  });
});
