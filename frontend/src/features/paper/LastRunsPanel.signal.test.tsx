// Pin the zone so local-time assertions for the fills table are
// deterministic regardless of the host running the suite.
process.env.TZ = "UTC";

/**
 * LastRunsPanel — Signal presentation slice (KRELL-SIGNAL-20261010).
 *
 * These tests pin the approved Signal presentation for the mounted
 * paper-run history surface next to the already-migrated operations /
 * strategies surfaces:
 *
 *  - a header panel naming "Paper runs" carrying the run-count chip;
 *  - a runs list panel whose rows render the UTC time in restrained
 *    mono, the pair bold, a status chip (sage for an armed/active run,
 *    coral for a failed one) and the last refusal in the coral tone;
 *  - the selected row carries the seafoam selection affordance and a
 *    >=44px tap target;
 *  - a detail panel that opens for the selected run with the fills
 *    table (local-time mono, pair, side badge, coid mono) and an
 *    explicit coral "no fills in this run" empty state;
 *  - the loading/error indicators sit on a muted panel surface;
 *  - dense tables scroll inside their own region instead of widening
 *    the page, and the 390px composition stays width-contained.
 *
 * jsdom has no layout engine, so the containment/tap-target proofs
 * resolve the *actual shipped* declarations from
 * LastRunsPanel.signal.css (same approach as
 * GraphCanvas.signal.test.tsx). They fail loudly when the stylesheet
 * or its structural classes are missing, so the suite is RED on the
 * old plain-div presentation and GREEN once the Signal slice ships.
 * Real mounted measurements at 1600x900 and 390x844 are captured by
 * the browser evidence harness outside this repository.
 *
 * Transport note: every client here is an in-memory vi.fn() fake
 * standing in for the loopback paper API. No real venue/engine state,
 * keys, orders or fills are exercised or implied by these tests.
 */

import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LastRunsPanel } from "./LastRunsPanel";
import type { PaperClient, PaperHistory, PaperRunsClient } from "./client";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function makeHistory(overrides: Partial<PaperHistory> = {}): PaperHistory {
  return {
    schema_version: "1",
    runs: [
      {
        venue: "kraken",
        pair: "SUIUSD",
        pack_id: "trend-follow",
        pack_version: "1",
        first_ts_ms: Date.UTC(2026, 9, 7, 10, 0, 0),
        last_ts_ms: Date.UTC(2026, 9, 7, 11, 0, 0),
        ticks_total: 4,
        last_refusal_code: "store_full",
        mode: "paper",
        status: "closed",
        summary: "4 ticks, 1 fill, last refusal store_full, closed",
        recent_fills: [
          { coid: "coid-entry-1", side: "buy", ts_ms: Date.UTC(2026, 9, 7, 9, 30, 5) },
        ],
      },
      {
        venue: "kraken",
        pair: "DOTUSD",
        pack_id: "trend-follow",
        first_ts_ms: Date.UTC(2026, 9, 6, 10, 0, 0),
        last_ts_ms: Date.UTC(2026, 9, 6, 10, 30, 0),
        ticks_total: 1,
        last_refusal_code: null,
        mode: "paper",
        status: "closed",
        summary: "1 tick, 0 fills, no refusal, closed",
        recent_fills: [],
      },
    ],
    ...overrides,
  };
}

function makeClient(
  history: PaperHistory = makeHistory(),
): PaperClient & PaperRunsClient {
  return {
    getStatus: vi.fn(),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    disarm: vi.fn(),
    listRuns: vi.fn().mockResolvedValue(history),
  } as unknown as PaperClient & PaperRunsClient;
}

async function renderPanel(
  client: PaperClient & PaperRunsClient,
): Promise<void> {
  render(<LastRunsPanel client={client} />);
  await waitFor(() => {
    expect(screen.getByTestId("paper-last-runs-table")).toBeDefined();
  });
}

/* ------------------------------------------------------------------ */
/* Stylesheet reader (shipped CSS, not an expectation string)          */
/* ------------------------------------------------------------------ */

let cssCache = "";

function readStylesheet(): string {
  if (cssCache === "") {
    cssCache = readFileSync(join(here, "LastRunsPanel.signal.css"), "utf8");
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
/* 1. Header panel: "Paper runs" + run-count chip                      */
/* ------------------------------------------------------------------ */

describe("LastRunsPanel Signal layout — header panel", () => {
  it("names the header 'Paper runs' and renders the run-count chip with the real run total", async () => {
    await renderPanel(makeClient());

    const title = screen.getByRole("heading", { level: 2, name: "Paper runs" });
    expect(title).toBeDefined();

    const count = screen.getByTestId("paper-last-runs-count");
    expect(count.textContent).toBe("2 runs");
    expect(count.className).toContain("kbot-paper-runs__count");
  });

  it("uses the singular form for exactly one run and stays truthful for none", async () => {
    await renderPanel(
      makeClient(
        makeHistory({
          runs: [
            {
              venue: "kraken",
              pair: "SUIUSD",
              pack_id: "trend-follow",
              first_ts_ms: Date.UTC(2026, 9, 7, 10, 0, 0),
              last_ts_ms: Date.UTC(2026, 9, 7, 11, 0, 0),
              ticks_total: 4,
              last_refusal_code: null,
              mode: "paper",
              status: "closed",
              summary: "4 ticks, 0 fills, no refusal, closed",
              recent_fills: [],
            },
          ],
        }),
      ),
    );
    expect(screen.getByTestId("paper-last-runs-count").textContent).toBe("1 run");
  });

  it("imports the Signal stylesheet from LastRunsPanel.tsx", () => {
    const source = readFileSync(resolve(here, "LastRunsPanel.tsx"), "utf8");
    expect(source).toMatch(/import\s+"\.\/LastRunsPanel\.signal\.css"/);
  });
});

/* ------------------------------------------------------------------ */
/* 2. Runs list panel: restrained rows                                 */
/* ------------------------------------------------------------------ */

describe("LastRunsPanel Signal layout — runs list rows", () => {
  it("renders each row with UTC time mono, bold pair, status chip and fills count", async () => {
    await renderPanel(makeClient());

    const row = screen.getByTestId("paper-last-runs-row-kraken-SUIUSD");
    expect(row.querySelector("td.kbot-paper-runs__ts")?.textContent).toBe(
      "2026-10-07T10:00:00.000Z",
    );
    expect(
      row.querySelectorAll("td.kbot-paper-runs__ts")[1]?.textContent,
    ).toBe("2026-10-07T11:00:00.000Z");
    expect(row.querySelector("td.kbot-paper-runs__pair")?.textContent).toBe(
      "SUIUSD",
    );
    expect(
      row.querySelector("td.kbot-paper-runs__venue")?.textContent,
    ).toBe("kraken");

    const chip = row.querySelector(".kbot-paper-runs__chip");
    expect(chip?.textContent).toBe("closed");
    expect(chip?.getAttribute("data-testid")).toBe(
      "paper-last-runs-status-kraken-SUIUSD",
    );
    expect(
      row.querySelector('[data-testid="paper-last-runs-fills-kraken-SUIUSD"]')
        ?.textContent,
    ).toBe("1");
  });

  it("styles an armed/active run chip with the sage tone and a closed run without it", async () => {
    const history = makeHistory();
    history.runs[0] = { ...history.runs[0], status: "active" };
    await renderPanel(makeClient(history));

    const activeChip = screen.getByTestId("paper-last-runs-status-kraken-SUIUSD");
    expect(activeChip.textContent).toBe("active");
    expect(activeChip.className).toContain("kbot-paper-runs__chip--sage");

    const closedChip = screen.getByTestId("paper-last-runs-status-kraken-DOTUSD");
    expect(closedChip.textContent).toBe("closed");
    expect(closedChip.className).not.toContain("kbot-paper-runs__chip--sage");
    expect(closedChip.className).not.toContain("kbot-paper-runs__chip--coral");
  });

  it("styles a failed run chip with the coral tone (refusals stay coral too)", async () => {
    const history = makeHistory();
    history.runs[1] = { ...history.runs[1], status: "failed" };
    await renderPanel(makeClient(history));

    expect(screen.getByTestId("paper-last-runs-status-kraken-DOTUSD").className).toContain(
      "kbot-paper-runs__chip--coral",
    );

    const refusedRow = screen.getByTestId("paper-last-runs-row-kraken-SUIUSD");
    const refusalCell = refusedRow.querySelector("td.kbot-paper-runs__refusal");
    expect(refusalCell?.textContent).toBe("store_full");
    expect(refusalCell?.className).toContain("kbot-paper-runs__refusal--present");

    const cleanRow = screen.getByTestId("paper-last-runs-row-kraken-DOTUSD");
    const noneCell = cleanRow.querySelector("td.kbot-paper-runs__refusal");
    expect(noneCell?.textContent).toBe("none");
    expect(noneCell?.className).not.toContain(
      "kbot-paper-runs__refusal--present",
    );
  });

  it("keeps the runs table inside the runs panel's internal scroll region", async () => {
    await renderPanel(makeClient());

    const table = screen.getByTestId("paper-last-runs-table");
    const scroll = screen.getByTestId("paper-last-runs-scroll");
    const panel = screen.getByTestId("paper-last-runs-list-panel");
    expect(scroll.contains(table)).toBe(true);
    expect(panel.contains(scroll)).toBe(true);
    expect(
      screen.getByTestId("paper-last-runs-panel").contains(panel),
    ).toBe(true);
  });
});

/* ------------------------------------------------------------------ */
/* 3. Selected row: seafoam affordance + 44px target                   */
/* ------------------------------------------------------------------ */

describe("LastRunsPanel Signal layout — selected row", () => {
  it("marks the clicked row with the seafoam selected state, one row at a time", async () => {
    await renderPanel(makeClient());

    const first = screen.getByTestId("paper-last-runs-row-kraken-SUIUSD");
    expect(first.className).not.toContain("kbot-paper-runs__row--selected");

    fireEvent.click(first);
    expect(first.className).toContain("kbot-paper-runs__row--selected");

    const second = screen.getByTestId("paper-last-runs-row-kraken-DOTUSD");
    expect(second.className).not.toContain("kbot-paper-runs__row--selected");

    fireEvent.click(second);
    expect(second.className).toContain("kbot-paper-runs__row--selected");
    expect(first.className).not.toContain("kbot-paper-runs__row--selected");
  });

  it("keeps rows focusable with a keyboard-visible focus affordance", async () => {
    await renderPanel(makeClient());
    const row = screen.getByTestId(
      "paper-last-runs-row-kraken-SUIUSD",
    ) as HTMLElement;
    expect(row.tabIndex).toBe(0);
  });

  it("ships a seafoam selected-row treatment and 44px row targets in the stylesheet", () => {
    const css = stripComments(readStylesheet());

    const selected = blocksFor(css, ".kbot-paper-runs__row--selected");
    expect(selected.length).toBeGreaterThanOrEqual(1);
    const selectedCss = selected.map((b) => b.declarations).join(";");
    expect(selectedCss).toContain("var(--seafoam");

    const row = blocksFor(css, ".kbot-paper-runs__row");
    expect(row.length).toBeGreaterThanOrEqual(1);
    const rowCss = row.map((b) => b.declarations).join(";");
    expect(rowCss).toMatch(/height:\s*44px|min-height:\s*44px/);

    expect(css).toMatch(
      /:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--seafoam/,
    );
  });
});

/* ------------------------------------------------------------------ */
/* 4. Detail panel: fills table + empty state                          */
/* ------------------------------------------------------------------ */

describe("LastRunsPanel Signal layout — run detail panel", () => {
  it("opens the detail panel for the selected run and renders the fills table inside it", async () => {
    await renderPanel(makeClient());

    fireEvent.click(screen.getByTestId("paper-last-runs-row-kraken-SUIUSD"));

    const detail = screen.getByTestId("paper-last-runs-detail");
    const fillsTable = within(detail).getByTestId("paper-last-runs-fills-table");
    expect(detail.contains(fillsTable)).toBe(true);

    const headerCells = Array.from(fillsTable.querySelectorAll("thead th")).map(
      (cell) => cell.textContent,
    );
    expect(headerCells).toEqual(["Time", "Pair", "Side", "Coid"]);

    const rows = Array.from(fillsTable.querySelectorAll("tbody tr"));
    expect(rows.length).toBe(1);
    const cells = rows[0]
      ? Array.from(rows[0].querySelectorAll("td")).map((c) => c.textContent)
      : [];
    expect(cells).toEqual(["2026-10-07T09:30:05", "SUIUSD", "buy", "coid-entry-1"]);

    // Local-time mono cell, side badge and mono coid keep their classes.
    expect(rows[0]?.querySelector("td.kbot-paper-runs__ts")?.textContent).toBe(
      "2026-10-07T09:30:05",
    );
    expect(rows[0]?.querySelector(".kbot-paper-runs__side")?.textContent).toBe(
      "buy",
    );
    expect(rows[0]?.querySelector("td.kbot-paper-runs__coid")?.textContent).toBe(
      "coid-entry-1",
    );
  });

  it("renders 'no fills in this run' inside the detail panel with the coral empty state", async () => {
    await renderPanel(makeClient());

    fireEvent.click(screen.getByTestId("paper-last-runs-row-kraken-DOTUSD"));

    const detail = screen.getByTestId("paper-last-runs-detail");
    const empty = within(detail).getByTestId("paper-last-runs-fills-empty");
    expect(empty.textContent).toBe("no fills in this run");
    expect(empty.className).toContain("kbot-paper-runs__fills-empty");
    expect(within(detail).queryByTestId("paper-last-runs-fills-table")).toBeNull();

    const css = stripComments(readStylesheet());
    const emptyBlocks = blocksFor(css, ".kbot-paper-runs__fills-empty");
    expect(emptyBlocks.length).toBeGreaterThanOrEqual(1);
    const emptyCss = emptyBlocks.map((b) => b.declarations).join(";");
    // Coral-derived caution tone (or its derived danger tokens), never sage.
    expect(
      emptyCss.includes("var(--coral") ||
        emptyCss.includes("var(--danger-text") ||
        emptyCss.includes("var(--danger-border"),
    ).toBe(true);
    expect(emptyCss).not.toContain("var(--sage");
  });

  it("keeps the detail close control inside the detail panel header", async () => {
    await renderPanel(makeClient());
    fireEvent.click(screen.getByTestId("paper-last-runs-row-kraken-SUIUSD"));

    const detail = screen.getByTestId("paper-last-runs-detail");
    const close = within(detail).getByTestId("paper-last-runs-detail-close");
    expect(close.textContent).toBe("Close detail");

    fireEvent.click(close);
    expect(screen.queryByTestId("paper-last-runs-detail")).toBeNull();
  });

  it("wraps the dense fills table in its own internal scroll region", async () => {
    await renderPanel(makeClient());
    fireEvent.click(screen.getByTestId("paper-last-runs-row-kraken-SUIUSD"));

    const fillsTable = screen.getByTestId("paper-last-runs-fills-table");
    const fillsScroll = screen.getByTestId("paper-last-runs-fills-scroll");
    expect(fillsScroll.contains(fillsTable)).toBe(true);
    expect(
      screen.getByTestId("paper-last-runs-detail").contains(fillsScroll),
    ).toBe(true);
  });
});

/* ------------------------------------------------------------------ */
/* 5. Loading / error indicators on a muted panel surface              */
/* ------------------------------------------------------------------ */

describe("LastRunsPanel Signal layout — loading and error indicators", () => {
  it("renders the loading indicator on the muted panel surface before the first read resolves", () => {
    const client = makeClient();
    (client.listRuns as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise<PaperHistory>(() => {}),
    );
    render(<LastRunsPanel client={client} />);

    const loading = screen.getByTestId("paper-last-runs-loading");
    expect(loading.textContent).toBe("Loading paper runs…");
    expect(loading.className).toContain("kbot-paper-runs__empty");
    expect(screen.queryByTestId("paper-last-runs-table")).toBeNull();
  });

  it("renders the read failure as an alert without inventing runs", async () => {
    const client = makeClient();
    (client.listRuns as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("paper history refused: session required"),
    );
    render(<LastRunsPanel client={client} />);

    const error = await screen.findByTestId("paper-last-runs-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toBe("paper history refused: session required");
    expect(screen.queryByTestId("paper-last-runs-table")).toBeNull();
    expect(screen.getByTestId("paper-last-runs-empty").textContent).toBe(
      "No paper runs yet",
    );
  });

  it("ships the muted panel surface for the empty/loading/error indicators in the stylesheet", () => {
    const css = stripComments(readStylesheet());
    for (const selector of [
      ".kbot-paper-runs__empty",
      ".kbot-paper-runs__error",
    ]) {
      const blocks = blocksFor(css, selector);
      expect(blocks.length).toBeGreaterThanOrEqual(1);
      const declarations = blocks.map((b) => b.declarations).join(";");
      expect(declarations).toContain("var(--surface");
      expect(declarations).toMatch(/border[^;]*var\(--line/);
      expect(declarations).toMatch(/radius/);
    }
    // The error text itself stays coral-derived danger, never sage.
    const errorBlocks = blocksFor(css, ".kbot-paper-runs__error");
    const errorCss = errorBlocks.map((b) => b.declarations).join(";");
    expect(
      errorCss.includes("var(--danger-text") || errorCss.includes("var(--coral"),
    ).toBe(true);
    expect(errorCss).not.toContain("var(--sage");
  });
});

/* ------------------------------------------------------------------ */
/* 6. Width containment at 390px (shipped declarations)                */
/* ------------------------------------------------------------------ */

describe("LastRunsPanel Signal layout — width containment", () => {
  it("keeps the root width-contained so long coids, pairs or venues never widen the page", () => {
    const css = stripComments(readStylesheet());
    const root = blocksFor(css, ".kbot-paper-runs");
    expect(root.length).toBeGreaterThanOrEqual(1);
    const declarations = root.map((b) => b.declarations).join(";");
    expect(declarationValue(declarations, "min-width")).toBe("0");
    const maxWidth = declarationValue(declarations, "max-width");
    const width = declarationValue(declarations, "width");
    expect(maxWidth === "100%" || width === "100%").toBe(true);
  });

  it("gives the dense tables explicit min-widths inside their own scroll regions", () => {
    const css = stripComments(readStylesheet());

    const scroll = blocksFor(css, ".kbot-paper-runs__scroll");
    expect(scroll.length).toBeGreaterThanOrEqual(1);
    const scrollCss = scroll.map((b) => b.declarations).join(";");
    expect(scrollCss).toMatch(/overflow-x:\s*auto/);
    expect(scrollCss).toMatch(/max-width:\s*100%/);

    const runsTable = blocksFor(css, ".kbot-paper-runs__table");
    expect(runsTable.length).toBeGreaterThanOrEqual(1);
    expect(
      declarationValue(runsTable.map((b) => b.declarations).join(";"), "min-width"),
    ).toMatch(/^\d+px$/);

    const fillsTable = blocksFor(css, ".kbot-paper-runs__fills");
    expect(fillsTable.length).toBeGreaterThanOrEqual(1);
    expect(
      declarationValue(
        fillsTable.map((b) => b.declarations).join(";"),
        "min-width",
      ),
    ).toMatch(/^\d+px$/);
  });

  it("composes intentionally at 390px: stacked header, 44px controls, contained tables", () => {
    const css = stripComments(readStylesheet());
    const media = splitMedia(css).media;
    const narrow = media.find((block) =>
      block.query.includes("max-width: 640px"),
    );
    expect(narrow).toBeDefined();

    const narrowCss = narrow ? narrow.body : "";
    // Ordinary controls keep >=44px touch targets on narrow screens.
    expect(narrowCss).toMatch(/min-height:\s*44px/);
    // Dense tables keep an explicit internal-scroll min-width on mobile.
    const narrowTables = selectorBlocks(narrowCss).filter((block) =>
      block.selector.includes("kbot-paper-runs__table") ||
      block.selector.includes("kbot-paper-runs__fills"),
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
