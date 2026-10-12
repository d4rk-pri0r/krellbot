/**
 * StatusPanel — Signal presentation slice (KRELL-SIGNAL-20261010).
 *
 * These tests pin the approved Signal presentation for the mounted
 * StatusPanel, the central status surface of the Workstation paper
 * column, alongside the already-integrated StatusStrip.signal /
 * LastRunsPanel.signal / RehearsalPanel.signal / ArmedRecordsList.signal
 * / JobsDrawer.signal / CommandPalette.signal / Navigation.signal /
 * PaperStatusCsvExport.signal surfaces:
 *
 *  - the header panel keeps its "Paper status" name and carries the
 *    honest preview identity: the seafoam "Local preview" badge plus
 *    the "Live trading unavailable" caption, in every paper state;
 *  - the persistent owned-position / armed-state truth table: the
 *    entries sentence renders as a status chip — sage tone for
 *    "Entries active", coral-derived for "Entries paused" — with the
 *    verbatim sentence carrying the state, and the pack line and the
 *    owned-position sentence quoting the wire verbatim;
 *  - ordinary command controls keep the seafoam-accented selection
 *    treatment while Disarm alone carries the coral-derived danger
 *    treatment;
 *  - the stop-decimal input keeps its scoped control chrome, and the
 *    raise-stop echo renders on the sage-derived affirmative surface;
 *  - loading / unavailable / error indicators sit on a muted panel
 *    surface with coral-derived danger text, never sage;
 *  - every pre-existing data-testid value is preserved byte-equal and
 *    every existing affordance keeps a >=44px tap target at 390px.
 *
 * jsdom has no layout engine, so the containment/tap-target proofs
 * resolve the *actual shipped* declarations from
 * StatusPanel.signal.css (same approach as LastRunsPanel.signal.test.tsx).
 * They fail loudly when the stylesheet or its structural classes are
 * missing, so the suite is RED on the old plain-section presentation
 * and GREEN once the Signal slice ships. Real mounted measurements at
 * 1600x900 and 390x844 are captured by the browser evidence harness
 * outside this repository.
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
import { StatusPanel } from "./StatusPanel";
import type {
  PaperArmDraftSummary,
  PaperClient,
  PaperCommandResult,
  PaperPosition,
  PaperStatus,
} from "./client";

const here = dirname(fileURLToPath(import.meta.url));

const ROOT_SCOPE = "kbot-feature__status-panel-root";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/* ------------------------------------------------------------------ */
/* Client fakes                                                        */
/* ------------------------------------------------------------------ */

function armedStatus(extra: Partial<PaperStatus> = {}): PaperStatus {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    entries_paused: false,
    mode: "paper",
    pack_id: "trend-follow",
    ...extra,
  };
}

function ownedPosition(extra: Partial<PaperPosition> = {}): PaperPosition {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    free_cash: "250.5",
    holdings: [{ symbol: "BTC", qty: "0.25" }],
    ...extra,
  };
}

function runnableDrafts(): PaperArmDraftSummary[] {
  return [
    {
      revision_id: "rev-1",
      strategy_id: "trend",
      state: "deployed",
      runnable: true,
      label: "trend follow",
      pair: "SUIUSD",
    },
  ];
}

function okResult(message = "stop set: kraken SUIUSD -> 1050"): PaperCommandResult {
  return {
    schema_version: "1",
    code: "stop_set",
    ok: true,
    message,
    effect: "changed",
  };
}

function makeClient(overrides: Partial<PaperClient> = {}): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue(armedStatus()),
    getPosition: vi.fn().mockResolvedValue(ownedPosition()),
    pauseEntries: vi.fn().mockResolvedValue({ ok: true }),
    resumeEntries: vi.fn().mockResolvedValue({ ok: true }),
    disarm: vi.fn().mockResolvedValue({ ok: true }),
    listOwnedDrafts: vi.fn().mockResolvedValue(runnableDrafts()),
    arm: vi.fn().mockResolvedValue({ ok: true }),
    ...overrides,
  };
}

/* ------------------------------------------------------------------ */
/* Stylesheet reader (shipped CSS, not an expectation string)          */
/* ------------------------------------------------------------------ */

let cssCache = "";

function readStylesheet(): string {
  if (cssCache === "") {
    cssCache = readFileSync(join(here, "StatusPanel.signal.css"), "utf8");
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

function declarationValue(declarations: string, property: string): string | null {
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
/* 1. Scoped wrapper + honest preview identity                         */
/* ------------------------------------------------------------------ */

describe("StatusPanel Signal presentation — scoped root and preview identity", () => {
  it("imports the Signal stylesheet from StatusPanel.tsx", () => {
    const source = readFileSync(resolve(here, "StatusPanel.tsx"), "utf8");
    expect(source).toMatch(/import\s+"\.\/StatusPanel\.signal\.css"/);
  });

  it("mounts the section under the .kbot-feature__status-panel-root scope while keeping the shared kbot-paper-status class", async () => {
    render(<StatusPanel client={makeClient()} />);
    const panel = (await screen.findByTestId("paper-status-panel")) as HTMLElement;
    expect(panel.className).toContain("kbot-paper-status");
    expect(panel.className).toContain(ROOT_SCOPE);
    expect(panel.getAttribute("role")).toBe("region");
    expect(panel.getAttribute("aria-label")).toBe("Paper controls");
  });

  it("renders the seafoam 'Local preview' badge and the 'Live trading unavailable' caption in the header for an armed paper status", async () => {
    render(<StatusPanel client={makeClient()} />);

    const badge = await screen.findByTestId("paper-status-local-preview");
    expect(badge.textContent).toBe("Local preview");
    expect(badge.className).toContain(`${ROOT_SCOPE}__badge`);

    const caption = screen.getByTestId("paper-status-live-unavailable");
    expect(caption.textContent).toBe("Live trading unavailable");
    expect(caption.className).toContain(`${ROOT_SCOPE}__note`);

    // The identity sits inside the panel header, next to the title.
    const header = badge.closest(`.kbot-paper-status__head`);
    expect(header).not.toBeNull();
    expect(
      within(header as HTMLElement).getByRole("heading", {
        level: 2,
        name: "Paper status",
      }),
    ).toBeDefined();
  });

  it("keeps the badge and caption mounted across the unarmed and unavailable states too", async () => {
    const unarmed = makeClient({
      getStatus: vi.fn().mockResolvedValue({ schema_version: "1", armed: false }),
    });
    const { rerender } = render(<StatusPanel client={unarmed} />);
    await screen.findByTestId("paper-arm-form");
    expect(screen.getByTestId("paper-status-local-preview").textContent).toBe(
      "Local preview",
    );
    expect(screen.getByTestId("paper-status-live-unavailable").textContent).toBe(
      "Live trading unavailable",
    );

    const unavailable = makeClient({
      getStatus: vi.fn().mockRejectedValue(new Error("session required")),
      listOwnedDrafts: vi.fn().mockRejectedValue(new Error("session required")),
    });
    rerender(<StatusPanel client={unavailable} />);
    await screen.findByTestId("paper-status-unavailable");
    expect(screen.getByTestId("paper-status-local-preview").textContent).toBe(
      "Local preview",
    );
    expect(screen.getByTestId("paper-status-live-unavailable").textContent).toBe(
      "Live trading unavailable",
    );
  });
});

/* ------------------------------------------------------------------ */
/* 2. Truth table: entries chip + verbatim wire evidence               */
/* ------------------------------------------------------------------ */

describe("StatusPanel Signal presentation — armed-state truth table", () => {
  it("renders the entries sentence as the sage tone chip while entries run", async () => {
    render(<StatusPanel client={makeClient()} />);
    const entries = await screen.findByTestId("paper-status-entries");
    expect(entries.textContent).toBe("Entries active");
    expect(entries.className).toContain(`${ROOT_SCOPE}__entries`);
    expect(entries.className).not.toContain(`${ROOT_SCOPE}__entries--paused`);
  });

  it("switches the chip to the coral-derived paused tone without changing the sentence vocabulary", async () => {
    render(
      <StatusPanel
        client={makeClient({
          getStatus: vi.fn().mockResolvedValue(armedStatus({ entries_paused: true })),
        })}
      />,
    );
    const entries = await screen.findByTestId("paper-status-entries");
    expect(entries.textContent).toBe("Entries paused");
    expect(entries.className).toContain(`${ROOT_SCOPE}__entries--paused`);
  });

  it("quotes the pack line and the owned position verbatim from the wire", async () => {
    render(<StatusPanel client={makeClient()} />);
    expect((await screen.findByTestId("paper-status-pack")).textContent).toBe(
      "trend-follow on kraken SUIUSD",
    );
    expect((await screen.findByTestId("paper-position")).textContent).toBe(
      "Owned position: 0.25 BTC — free cash 250.5 USD",
    );
  });

  it("keeps the honest pending read and the honest unavailable read in the armed branch", async () => {
    const pending = makeClient({
      getPosition: vi.fn().mockReturnValue(new Promise<PaperPosition>(() => {})),
    });
    const { unmount } = render(<StatusPanel client={pending} />);
    await screen.findByTestId("paper-status-entries");
    expect(screen.getByTestId("paper-position-pending").textContent).toBe(
      "Reading owned position…",
    );
    unmount();

    const failed = makeClient({
      getPosition: vi.fn().mockRejectedValue(new Error("wire refused")),
    });
    render(<StatusPanel client={failed} />);
    const unavailable = await screen.findByTestId("paper-position-unavailable");
    expect(unavailable.textContent).toBe("Owned position unavailable: wire refused");
  });
});

/* ------------------------------------------------------------------ */
/* 3. Command row: selection accents + the Disarm danger treatment     */
/* ------------------------------------------------------------------ */

describe("StatusPanel Signal presentation — command row", () => {
  it("keeps every ordinary control on the scoped seafoam-accented action chrome", async () => {
    render(<StatusPanel client={makeClient()} />);
    for (const name of [/pause entries/i, /resume entries/i, /^refresh status$/i]) {
      const button = await screen.findByRole("button", { name });
      expect(button.className).toContain("kbot-paper-status__action");
      expect(button.className).toContain(`${ROOT_SCOPE}__action`);
      expect(button.className).not.toContain(`${ROOT_SCOPE}__action--danger`);
    }
  });

  it("gives Disarm alone the coral-derived danger treatment", async () => {
    render(<StatusPanel client={makeClient()} />);
    const disarm = await screen.findByRole("button", { name: /^disarm$/i });
    expect(disarm.className).toContain("kbot-paper-status__action");
    expect(disarm.className).toContain(`${ROOT_SCOPE}__action--danger`);
  });
});

/* ------------------------------------------------------------------ */
/* 4. Stop-decimal field and the confirmed echo                        */
/* ------------------------------------------------------------------ */

describe("StatusPanel Signal presentation — raise-stop field", () => {
  it("keeps the stop-decimal input on the scoped mono control chrome", async () => {
    render(<StatusPanel client={makeClient()} />);
    const input = (await screen.findByTestId(
      "paper-raise-stop-input",
    )) as HTMLInputElement;
    expect(input.className).toContain("kbot-paper-status__input");
    expect(input.className).toContain(`${ROOT_SCOPE}__control`);
    expect(input.getAttribute("inputmode")).toBe("decimal");
  });

  it("renders the backend-confirmed raise-stop echo on the sage-derived affirmative surface", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => okResult("stop set: kraken SUIUSD -> 1050"),
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      const client = makeClient({
        getStatus: vi
          .fn()
          .mockResolvedValueOnce(armedStatus())
          .mockResolvedValue(armedStatus()),
      });
      render(<StatusPanel client={client} />);
      await screen.findByTestId("paper-status-entries");

      const input = (await screen.findByTestId(
        "paper-raise-stop-input",
      )) as HTMLInputElement;
      fireEvent.change(input, { target: { value: "1050" } });

      const apply = await screen.findByTestId("paper-raise-stop-apply");
      expect(apply.className).toContain(`${ROOT_SCOPE}__action`);
      fireEvent.click(apply);

      const echo = await screen.findByTestId("paper-raise-stop-ok");
      expect(echo.textContent).toBe("raised stop to 1050");
      expect(echo.className).toContain(`${ROOT_SCOPE}__ok`);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

/* ------------------------------------------------------------------ */
/* 5. Loading / unavailable / error indicators                         */
/* ------------------------------------------------------------------ */

describe("StatusPanel Signal presentation — loading and error indicators", () => {
  it("renders the pre-read loading line and the failed-read unavailable line with their alerts", async () => {
    const pending = makeClient({
      getStatus: vi.fn().mockReturnValue(new Promise<PaperStatus>(() => {})),
    });
    const { unmount } = render(<StatusPanel client={pending} />);
    expect(screen.getByTestId("paper-status-loading").textContent).toBe(
      "Checking paper status…",
    );
    unmount();

    const failed = makeClient({
      getStatus: vi.fn().mockRejectedValue(new Error("offline")),
    });
    render(<StatusPanel client={failed} />);
    const unavailable = await screen.findByTestId("paper-status-unavailable");
    expect(unavailable.getAttribute("role")).toBe("alert");
    expect(screen.getByRole("button", { name: /retry status/i }).className).toContain(
      `${ROOT_SCOPE}__action`,
    );
  });

  it("keeps refusal copy on the shared error class, never on the sage surface", async () => {
    render(
      <StatusPanel
        client={makeClient({
          getStatus: vi.fn().mockResolvedValue(armedStatus({ mode: "live" })),
        })}
      />,
    );
    const empty = await screen.findByTestId("paper-status-empty");
    expect(empty.textContent).toBe("Controls unavailable");
    expect(empty.className).toContain("kbot-paper-status__empty");
    expect(empty.className).not.toContain(`${ROOT_SCOPE}__ok`);
  });
});

/* ------------------------------------------------------------------ */
/* 6. Shipped stylesheet proofs (containment, targets, tokens)         */
/* ------------------------------------------------------------------ */

describe("StatusPanel Signal presentation — shipped stylesheet", () => {
  it("scopes every rule under .kbot-feature__status-panel-root", () => {
    const raw = readStylesheet();
    const css = stripComments(raw);
    for (const selector of css.split("}").map((rule) => rule.split("{")[0] ?? "")) {
      const trimmed = selector.trim();
      if (trimmed.length > 0 && !trimmed.startsWith("@media")) {
        expect(trimmed.startsWith(`.${ROOT_SCOPE}`)).toBe(true);
      }
    }
  });

  it("begins with the approved Signal comment block", () => {
    const raw = readStylesheet();
    expect(raw.startsWith("/*\n * Paper status — Signal + Krell Asset Pack v2")).toBe(
      true,
    );
    expect(raw).toContain("KRELL-SIGNAL-20261010");
    expect(raw).toContain("frontend/src/features/paper/StatusPanel.tsx");
    expect(raw).toContain("frontend/src/styles/tokens.css");
  });

  it("ships the badge chrome in the seafoam selection tone and the caption in the muted tone", () => {
    const css = stripComments(readStylesheet());

    const badge = blocksFor(css, `${ROOT_SCOPE}__badge`);
    expect(badge.length).toBeGreaterThanOrEqual(1);
    const badgeCss = badge.map((b) => b.declarations).join(";");
    expect(badgeCss).toContain("var(--seafoam");
    expect(badgeCss).not.toContain("var(--sage");

    const note = blocksFor(css, `${ROOT_SCOPE}__note`);
    expect(note.length).toBeGreaterThanOrEqual(1);
    expect(note.map((b) => b.declarations).join(";")).toContain("var(--muted");
  });

  it("ships the sage tone for the active entries chip and the coral-derived tone for the paused one", () => {
    const css = stripComments(readStylesheet());

    const active = blocksFor(css, `${ROOT_SCOPE}__entries`);
    expect(active.length).toBeGreaterThanOrEqual(1);
    const activeCss = active
      .filter((b) => !b.selector.includes("--paused"))
      .map((b) => b.declarations)
      .join(";");
    expect(activeCss).toContain("var(--sage");
    expect(activeCss).not.toContain("var(--coral");

    const paused = blocksFor(css, `${ROOT_SCOPE}__entries--paused`);
    expect(paused.length).toBeGreaterThanOrEqual(1);
    const pausedCss = paused.map((b) => b.declarations).join(";");
    expect(
      pausedCss.includes("var(--coral") ||
        pausedCss.includes("var(--danger-text"),
    ).toBe(true);
    expect(pausedCss).not.toContain("var(--sage");
  });

  it("ships the seafoam selection accent for ordinary actions and the coral-derived danger accent for Disarm", () => {
    const css = stripComments(readStylesheet());

    const action = blocksFor(css, `${ROOT_SCOPE}__action`);
    expect(action.length).toBeGreaterThanOrEqual(1);
    const actionCss = action
      .filter((b) => !b.selector.includes("--danger"))
      .map((b) => b.declarations)
      .join(";");
    expect(actionCss).toContain("var(--seafoam");

    const danger = blocksFor(css, `${ROOT_SCOPE}__action--danger`);
    expect(danger.length).toBeGreaterThanOrEqual(1);
    const dangerCss = danger.map((b) => b.declarations).join(";");
    expect(
      dangerCss.includes("var(--coral") ||
        dangerCss.includes("var(--danger-text"),
    ).toBe(true);
    expect(dangerCss).not.toContain("var(--sage");
  });

  it("ships the muted panel surface for loading/unavailable/error indicators, never sage", () => {
    const css = stripComments(readStylesheet());
    for (const selector of [
      ".kbot-paper-status__empty",
      ".kbot-paper-status__unknown",
      ".kbot-paper-status__error",
    ]) {
      const blocks = blocksFor(css, selector);
      expect(blocks.length).toBeGreaterThanOrEqual(1);
      const declarations = blocks.map((b) => b.declarations).join(";");
      expect(declarations).toContain("var(--surface");
      expect(declarations).toMatch(/radius/);
      expect(declarations).not.toContain("var(--sage");
    }
  });

  it("keeps the root width-contained so long balances, pairs or refusal messages never widen the page", () => {
    const css = stripComments(readStylesheet());
    const root = blocksFor(css, `.${ROOT_SCOPE}`);
    expect(root.length).toBeGreaterThanOrEqual(1);
    const declarations = root.map((b) => b.declarations).join(";");
    expect(declarationValue(declarations, "min-width")).toBe("0");
    const maxWidth = declarationValue(declarations, "max-width");
    const width = declarationValue(declarations, "width");
    expect(maxWidth === "100%" || width === "100%").toBe(true);
  });

  it("gives the existing affordances >=44px tap targets at 390px (Arm button, stop-decimal input, Disarm button)", () => {
    const css = stripComments(readStylesheet());
    const media = splitMedia(css).media;
    const narrow = media.find((block) =>
      block.query.includes("max-width: 640px"),
    );
    expect(narrow).toBeDefined();

    const narrowCss = narrow ? narrow.body : "";
    // Ordinary controls (command row + arm submit + retry) and the
    // decimal inputs/selects (stop input, balance, revision) all keep
    // a 44px minimum on small viewports.
    for (const target of [`${ROOT_SCOPE}__action`, `${ROOT_SCOPE}__control`]) {
      const matches = selectorBlocks(narrowCss).filter((block) =>
        block.selector.includes(target),
      );
      expect(matches.length).toBeGreaterThanOrEqual(1);
      const heights = matches
        .map((block) => declarationValue(block.declarations, "min-height"))
        .filter((value): value is string => value !== null);
      expect(heights.length).toBeGreaterThanOrEqual(1);
      for (const height of heights) {
        expect(height).toBe("44px");
      }
    }
  });

  it("ships the seafoam focus-visible ring for keyboard affordances", () => {
    const css = stripComments(readStylesheet());
    expect(css).toMatch(
      new RegExp(
        `\\.${ROOT_SCOPE}[^{]*:focus-visible\\s*\\{[^}]*outline:\\s*2px solid var\\(--seafoam`,
      ),
    );
  });

  it("reuses only the approved Signal tokens — no new palette, nothing remote, no retired hues", () => {
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
      "#e0a296",
    ]);
    const hexes = css.toLowerCase().match(/#[0-9a-f]{6}\b/g) ?? [];
    for (const hex of hexes) {
      expect(approved.has(hex)).toBe(true);
    }
  });
});

/* ------------------------------------------------------------------ */
/* 7. Byte-equal data-testid preservation across the whole surface     */
/* ------------------------------------------------------------------ */

describe("StatusPanel Signal presentation — preserved data-testid contract", () => {
  it("keeps every pre-existing data-testid value byte-equal in StatusPanel.tsx", () => {
    const source = readFileSync(resolve(here, "StatusPanel.tsx"), "utf8");
    const expected = [
      "paper-status-panel",
      "paper-status-entries",
      "paper-status-pack",
      "paper-position-unavailable",
      "paper-position",
      "paper-position-pending",
      "paper-raise-stop",
      "paper-raise-stop-input",
      "paper-raise-stop-apply",
      "paper-raise-stop-error",
      "paper-raise-stop-ok",
      "paper-status-error",
      "paper-status-empty",
      "paper-status-unavailable",
      "paper-status-loading",
      "paper-status-unknown",
      "paper-arm-unavailable",
      "paper-arm-form",
      "paper-arm-load-failed",
      "paper-arm-error",
      "paper-arm-loading",
      "paper-arm-empty",
      "paper-arm-revision",
      "paper-arm-venue",
      "paper-arm-balance",
      "paper-arm-balance-error",
      "paper-arm-unknown",
    ];
    for (const id of expected) {
      expect(source).toContain(`data-testid="${id}"`);
    }
  });

  it("keeps the arm form's inputs on the scoped control chrome with their ids intact", async () => {
    render(
      <StatusPanel
        client={makeClient({
          getStatus: vi.fn().mockResolvedValue({ schema_version: "1", armed: false }),
        })}
      />,
    );
    const balance = (await screen.findByTestId(
      "paper-arm-balance",
    )) as HTMLInputElement;
    expect(balance.id).toBe("paper-arm-balance");
    expect(balance.className).toContain("kbot-paper-status__input");
    expect(balance.className).toContain(`${ROOT_SCOPE}__control`);

    const revision = (await screen.findByTestId(
      "paper-arm-revision",
    )) as HTMLSelectElement;
    expect(revision.id).toBe("paper-arm-revision");
    expect(revision.className).toContain(`${ROOT_SCOPE}__control`);

    const arm = await screen.findByRole("button", { name: /arm paper pack/i });
    expect(arm.className).toContain("kbot-paper-status__action");
    expect(arm.className).toContain(`${ROOT_SCOPE}__action`);
  });
});
