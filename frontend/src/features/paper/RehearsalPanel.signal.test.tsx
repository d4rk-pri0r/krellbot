// Pin the zone so the local-time fill stamps asserted below are
// deterministic regardless of the host running the suite.
process.env.TZ = "UTC";

/**
 * RehearsalPanel — Signal presentation slice (KRELL-SIGNAL-20261010).
 *
 * These tests pin the approved Signal presentation for the mounted
 * isolated synthetic rehearsal surface on the Workstation paper page,
 * next to the already-migrated operations / strategies / paper-runs
 * surfaces:
 *
 *  - a header panel that names the isolated rehearsal home and carries
 *    the rehearsal-state chip (sage while the loop runs, coral while
 *    the status cannot be confirmed, neutral otherwise);
 *  - a holdings/cash card whose balances, cursor, position and stop
 *    read in restrained IBM Plex Mono with tabular numerals — the
 *    rehearsal-only projection, never armed-paper state;
 *  - a grouped command form panel: Start is the one sage affirmative
 *    action, every command is a >=44px tap target on narrow screens,
 *    focus is keyboard-visible in seafoam, and refusals render in the
 *    coral-derived caution tone;
 *  - a rehearsal history list panel: fill rows carry sage buy / coral
 *    sell side badges, muted technical mono time/coid, and an explicit
 *    coral empty affordance when the backend reports no fills;
 *  - explicit loading / error / unavailable states on a muted panel
 *    surface;
 *  - the root stays width-contained: the dense fills table scrolls in
 *    its own region and the 390px composition never widens the page.
 *
 * jsdom has no layout engine, so the containment/tap-target proofs
 * resolve the *actual shipped* declarations from
 * RehearsalPanel.signal.css (same approach as
 * LastRunsPanel.signal.test.tsx). They fail loudly when the stylesheet
 * or its structural classes are missing, so the suite is RED on the
 * old unstyled presentation and GREEN once the Signal slice ships.
 * Real mounted measurements at 1600x900 and 390x844 are captured by
 * the browser evidence harness outside this repository.
 *
 * Transport note: every client here is an in-memory vi.fn() fake
 * standing in for the loopback rehearsal API. No real venue/engine
 * state, keys, orders, billing or fills are exercised or implied.
 * The seeded balances and fills are clearly-labeled test fixtures,
 * never a claim about the backend or any pack.
 */

import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RehearsalPanel } from "./RehearsalPanel";
import type {
  RehearsalClient,
  RehearsalCommandResult,
  RehearsalStatus,
} from "./rehearsalClient";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/* ------------------------------------------------------------------ */
/* Test-transport fixtures (clearly labeled, in-memory only)           */
/* ------------------------------------------------------------------ */

function rehearsalStatus(extra: Partial<RehearsalStatus> = {}): RehearsalStatus {
  return {
    schema_version: "1",
    label: "SYNTHETIC PAPER REHEARSAL — simulated fixture, not market data",
    status: "idle",
    cursor: 0,
    total_bars: 20,
    balances: { USD: "1000" },
    position: "0",
    resting_stop: null,
    recent_fills: [],
    ...extra,
  };
}

function commandResult(
  status: Partial<RehearsalStatus>,
): RehearsalCommandResult {
  return {
    schema_version: "1",
    code: "ok",
    ok: true,
    message: "ok",
    status: rehearsalStatus(status),
  };
}

function makeRehearsalClient(
  overrides: Partial<RehearsalClient> = {},
): RehearsalClient {
  return {
    getStatus: vi.fn().mockResolvedValue(rehearsalStatus()),
    start: vi.fn().mockResolvedValue(commandResult({ status: "running", cursor: 1 })),
    pause: vi.fn().mockResolvedValue(commandResult({ status: "paused" })),
    resume: vi.fn().mockResolvedValue(commandResult({ status: "running", cursor: 2 })),
    exit: vi.fn().mockResolvedValue(commandResult({ status: "exited" })),
    stop: vi.fn().mockResolvedValue(commandResult({ status: "stopped" })),
    ...overrides,
  };
}

/** A stateful fake: GET reflects exactly what the last confirmed
 *  command set, the way the real service does. */
function makeStatefulRehearsalClient(): RehearsalClient {
  let current = rehearsalStatus();
  const running = rehearsalStatus({
    status: "running",
    cursor: 1,
    balances: { USD: "984.25", SUI: "1.5" },
    position: "1.5",
    resting_stop: "0.42",
    recent_fills: [
      {
        coid: "coid-entry-1",
        side: "buy",
        qty: "1.5",
        price: "0.45",
        ts_ms: Date.UTC(2026, 9, 7, 9, 30, 5),
        kind: "fill",
      },
      {
        coid: "coid-exit-2",
        side: "sell",
        qty: "1.5",
        price: "0.5",
        ts_ms: Date.UTC(2026, 9, 7, 10, 15, 0),
        kind: "fill",
      },
    ],
  });
  return makeRehearsalClient({
    getStatus: vi.fn().mockImplementation(() => Promise.resolve(current)),
    start: vi.fn().mockImplementation(() => {
      current = running;
      return Promise.resolve({
        schema_version: "1",
        code: "ok",
        ok: true,
        message: "ok",
        status: running,
      });
    }),
    stop: vi.fn().mockImplementation(() => {
      current = rehearsalStatus({ status: "stopped" });
      return Promise.resolve(commandResult({ status: "stopped" }));
    }),
  });
}

async function renderPanel(client: RehearsalClient): Promise<void> {
  render(<RehearsalPanel client={client} />);
  // Wait for the first confirmed read (whatever lifecycle it carries).
  await waitFor(() => {
    expect(screen.getByTestId("rehearsal-holdings-panel")).toBeDefined();
    expect(
      screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-status"),
    ).not.toBe("unknown");
  });
}

/* ------------------------------------------------------------------ */
/* Stylesheet reader (shipped CSS, not an expectation string)          */
/* ------------------------------------------------------------------ */

let cssCache = "";

function readStylesheet(): string {
  if (cssCache === "") {
    cssCache = readFileSync(join(here, "RehearsalPanel.signal.css"), "utf8");
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
/* 1. Header panel: isolated rehearsal name + rehearsal-state chip     */
/* ------------------------------------------------------------------ */

describe("RehearsalPanel Signal layout — header panel", () => {
  it("names the isolated rehearsal home, keeps the synthetic disclosure and renders the state chip with the real lifecycle word", async () => {
    await renderPanel(makeRehearsalClient());

    const title = screen.getByRole("heading", { level: 2, name: "Synthetic paper rehearsal" });
    expect(title).toBeDefined();

    // The header names the isolated rehearsal surface so it is never
    // conflated with the armed-paper state above it.
    const eyebrow = screen.getByTestId("rehearsal-eyebrow");
    expect(eyebrow.textContent).toBe("Isolated rehearsal");

    // The backend's own synthetic disclaimer stays verbatim.
    expect(screen.getByTestId("rehearsal-label").textContent).toBe(
      "SYNTHETIC PAPER REHEARSAL — simulated fixture, not market data",
    );

    const chip = screen.getByTestId("rehearsal-state-chip");
    expect(chip.textContent).toBe("idle");
    // Neutral lifecycle: neither sage nor coral.
    expect(chip.className).not.toContain("kbot-rehearsal__chip--sage");
    expect(chip.className).not.toContain("kbot-rehearsal__chip--coral");
    expect(chip.className).toContain("kbot-rehearsal__chip");
  });

  it("carries the sage tone on the state chip only while the backend says the loop is running", async () => {
    const client = makeStatefulRehearsalClient();
    await renderPanel(client);

    const chip = screen.getByTestId("rehearsal-state-chip");
    expect(chip.textContent).toBe("idle");

    fireEvent.click(screen.getByRole("button", { name: /start rehearsal/i }));
    await waitFor(() => {
      expect(screen.getByTestId("rehearsal-state-chip").textContent).toBe("running");
    });
    expect(screen.getByTestId("rehearsal-state-chip").className).toContain(
      "kbot-rehearsal__chip--sage",
    );
    expect(screen.getByTestId("rehearsal-state-chip").className).not.toContain(
      "kbot-rehearsal__chip--coral",
    );
    // The lifecycle sentence and the panel's own state attribute agree.
    expect(screen.getByTestId("rehearsal-sentence").textContent).toBe(
      "Rehearsal running — evaluating simulated bars",
    );
  });

  it("carries the coral tone on the state chip when the status cannot be confirmed", async () => {
    const client = makeRehearsalClient({
      getStatus: vi.fn().mockRejectedValue(new Error("rehearsal status failed: 503")),
    });
    render(<RehearsalPanel client={client} />);

    const chip = await screen.findByTestId("rehearsal-state-chip");
    expect(chip.textContent).toBe("unknown");
    expect(chip.className).toContain("kbot-rehearsal__chip--coral");
    // The honest unavailable copy stays; no idle claim is invented.
    expect(screen.getByTestId("rehearsal-load-failed").textContent).toBe(
      "Rehearsal status unavailable",
    );
    expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-status")).toBe("unknown");
  });

  it("imports the Signal stylesheet from RehearsalPanel.tsx", () => {
    const source = readFileSync(resolve(here, "RehearsalPanel.tsx"), "utf8");
    expect(source).toMatch(/import\s+"\.\/RehearsalPanel\.signal\.css"/);
  });
});

/* ------------------------------------------------------------------ */
/* 2. Holdings / cash card: restrained numeric mono                    */
/* ------------------------------------------------------------------ */

describe("RehearsalPanel Signal layout — holdings and cash card", () => {
  it("renders the rehearsal-only balances projection inside the holdings card with restrained numeric mono", async () => {
    const client = makeRehearsalClient({
      getStatus: vi.fn().mockResolvedValue(
        rehearsalStatus({
          status: "running",
          cursor: 7,
          total_bars: 20,
          balances: { USD: "984.25", SUI: "1.5" },
          position: "1.5",
          resting_stop: "0.42",
        }),
      ),
    });
    await renderPanel(client);

    const holdings = screen.getByTestId("rehearsal-holdings-panel");
    expect(holdings.className).toContain("kbot-rehearsal__panel");

    // The balances are the backend's own rehearsal projection, verbatim,
    // sorted by asset; each carries the numeric mono treatment.
    const balances = within(holdings).getAllByTestId("rehearsal-balance");
    expect(balances.map((dd) => dd.textContent)).toEqual(["1.5", "984.25"]);
    for (const dd of balances) {
      expect(dd.className).toContain("kbot-rehearsal__num");
    }
    const labels = within(holdings)
      .getAllByRole("definition")
      .map((dd) => dd.previousElementSibling?.textContent ?? "");
    expect(labels).toContain("Balance USD");
    expect(labels).toContain("Balance SUI");
  });

  it("keeps the cursor, position and stop facts on the same restrained numeric treatment", async () => {
    const client = makeRehearsalClient({
      getStatus: vi.fn().mockResolvedValue(
        rehearsalStatus({
          status: "paused",
          cursor: 7,
          total_bars: 20,
          position: "1.5",
          resting_stop: "0.42",
        }),
      ),
    });
    await renderPanel(client);

    const holdings = screen.getByTestId("rehearsal-holdings-panel");
    expect(within(holdings).getByTestId("rehearsal-cursor").textContent).toBe(
      "Bar 7 of 20",
    );
    expect(within(holdings).getByTestId("rehearsal-position").textContent).toBe(
      "Position 1.5",
    );
    expect(within(holdings).getByTestId("rehearsal-stop").textContent).toBe(
      "Resting stop 0.42",
    );
    for (const testid of [
      "rehearsal-cursor",
      "rehearsal-position",
      "rehearsal-stop",
    ]) {
      expect(within(holdings).getByTestId(testid).className).toContain(
        "kbot-rehearsal__num",
      );
    }
  });

  it("ships the restrained numeric mono declarations for the card values", () => {
    const css = stripComments(readStylesheet());
    const num = blocksFor(css, ".kbot-rehearsal__num");
    expect(num.length).toBeGreaterThanOrEqual(1);
    const numCss = num.map((b) => b.declarations).join(";");
    expect(numCss).toMatch(/font-family:\s*var\(--font-mono/);
    expect(numCss).toMatch(/font-variant-numeric:\s*tabular-nums/);

    // The card itself is a grouped surface panel on the shared tokens.
    const panel = blocksFor(css, ".kbot-rehearsal__panel");
    expect(panel.length).toBeGreaterThanOrEqual(1);
    const panelCss = panel.map((b) => b.declarations).join(";");
    expect(panelCss).toContain("var(--panel");
    expect(panelCss).toContain("var(--line");
    expect(panelCss).toMatch(/radius/);
  });
});

/* ------------------------------------------------------------------ */
/* 3. Command form: sage primary, seafoam focus, 44px targets          */
/* ------------------------------------------------------------------ */

describe("RehearsalPanel Signal layout — command form", () => {
  it("groups the command set in a panel with Start as the one sage affirmative action", async () => {
    await renderPanel(makeRehearsalClient());

    const commands = screen.getByTestId("rehearsal-commands-panel");
    const start = within(commands).getByRole("button", { name: /start rehearsal/i });
    expect(start.className).toContain("kbot-rehearsal__action--primary");

    // The other lifecycle commands stay neutral, never success-colored.
    for (const name of [
      /pause rehearsal/i,
      /resume rehearsal/i,
      /exit rehearsal/i,
      /stop rehearsal/i,
      /refresh status/i,
    ]) {
      const button = within(commands).getByRole("button", { name });
      expect(button.className).not.toContain("kbot-rehearsal__action--primary");
    }
    expect(within(commands).getAllByRole("button").length).toBe(6);
  });

  it("disables the commands the current lifecycle does not allow, with pending copy while in flight", async () => {
    let resolveStart: (r: RehearsalCommandResult) => void = () => {};
    const gate = new Promise<RehearsalCommandResult>((resolve) => {
      resolveStart = resolve;
    });
    const client = makeRehearsalClient({ start: vi.fn().mockReturnValue(gate) });
    await renderPanel(client);

    // From idle: only start (and stop/refresh) are offered.
    expect(
      within(screen.getByTestId("rehearsal-commands-panel"))
        .getByRole("button", { name: /pause rehearsal/i })
        .getAttribute("disabled"),
    ).toBe("");
    expect(
      within(screen.getByTestId("rehearsal-commands-panel"))
        .getByRole("button", { name: /start rehearsal/i })
        .getAttribute("disabled"),
    ).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /start rehearsal/i }));
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /starting…|starting\.\.\./i }),
      ).toBeDefined();
    });
    // Every command is disabled while one is pending.
    for (const name of [
      /pause rehearsal/i,
      /resume rehearsal/i,
      /exit rehearsal/i,
      /stop rehearsal/i,
    ]) {
      expect(screen.getByRole("button", { name }).getAttribute("disabled")).toBe("");
    }

    resolveStart(commandResult({ status: "running" }));
    await waitFor(() => {
      expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-pending")).toBe("");
    });
  });

  it("issues the start command through the isolated rehearsal client and reconciles from the readback", async () => {
    const client = makeStatefulRehearsalClient();
    await renderPanel(client);

    fireEvent.click(screen.getByRole("button", { name: /start rehearsal/i }));
    await waitFor(() => {
      expect(client.start).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-status")).toBe("running");
    });
    // The readback's own holdings projection renders in the card.
    expect(screen.getByTestId("rehearsal-holdings-panel").textContent).toMatch(
      /984\.25/,
    );
  });

  it("ships the sage primary action, the seafoam focus state and the 44px narrow targets in the stylesheet", () => {
    const css = stripComments(readStylesheet());

    // Sage carries the one affirmative primary action.
    const primary = blocksFor(css, ".kbot-rehearsal__action--primary");
    expect(primary.length).toBeGreaterThanOrEqual(1);
    const primaryCss = primary.map((b) => b.declarations).join(";");
    expect(primaryCss).toContain("var(--sage");
    expect(primaryCss).not.toContain("var(--coral");

    // Keyboard focus is visible, in seafoam.
    expect(css).toMatch(
      /:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--seafoam/,
    );

    // The disabled affordance never looks like an active command.
    const disabled = blocksFor(css, ".kbot-rehearsal__action:disabled");
    expect(disabled.length).toBeGreaterThanOrEqual(1);
    const disabledCss = disabled.map((b) => b.declarations).join(";");
    expect(disabledCss).toMatch(/opacity|cursor/);

    // Ordinary controls keep >=44px touch targets on narrow screens.
    const media = splitMedia(css).media;
    const narrow = media.find((block) => block.query.includes("max-width: 640px"));
    expect(narrow).toBeDefined();
    const narrowCss = narrow ? narrow.body : "";
    expect(narrowCss).toMatch(/min-height:\s*44px/);
  });
});

/* ------------------------------------------------------------------ */
/* 4. Rehearsal history list: fill rows with state chips               */
/* ------------------------------------------------------------------ */

describe("RehearsalPanel Signal layout — rehearsal history list", () => {
  it("renders the backend's fill rows with side badges, muted mono time and coid inside the history panel", async () => {
    const client = makeRehearsalClient({
      getStatus: vi.fn().mockResolvedValue(
        rehearsalStatus({
          status: "running",
          recent_fills: [
            {
              coid: "coid-entry-1",
              side: "buy",
              qty: "1.5",
              price: "0.45",
              ts_ms: Date.UTC(2026, 9, 7, 9, 30, 5),
              kind: "fill",
            },
            {
              coid: "coid-exit-2",
              side: "sell",
              qty: "1.5",
              price: "0.5",
              ts_ms: Date.UTC(2026, 9, 7, 10, 15, 0),
              kind: "fill",
            },
          ],
        }),
      ),
    });
    await renderPanel(client);

    const history = screen.getByTestId("rehearsal-fills-panel");
    expect(history.className).toContain("kbot-rehearsal__panel");

    const rows = within(history).getAllByTestId("rehearsal-fill");
    expect(rows.length).toBe(2);

    // Sage buy badge, coral sell badge — the verbatim side word carries
    // the meaning, the tint only reinforces it.
    const buyBadge = rows[0].querySelector(".kbot-rehearsal__side");
    expect(buyBadge?.textContent).toBe("buy");
    expect(buyBadge?.className).toContain("kbot-rehearsal__side--buy");
    const sellBadge = rows[1].querySelector(".kbot-rehearsal__side");
    expect(sellBadge?.textContent).toBe("sell");
    expect(sellBadge?.className).toContain("kbot-rehearsal__side--sell");

    // Muted technical mono for the fill time and the coid.
    expect(rows[0].querySelector(".kbot-rehearsal__ts")?.textContent).toBe(
      new Date(Date.UTC(2026, 9, 7, 9, 30, 5)).toLocaleString(),
    );
    expect(rows[1].querySelector(".kbot-rehearsal__coid")?.textContent).toBe(
      "coid-exit-2",
    );

    // The fills caption keeps naming the history panel honestly.
    expect(
      within(history).getByText("Simulated fills").textContent,
    ).toBe("Simulated fills");
  });

  it("keeps the dense fills table inside its own internal scroll region", async () => {
    const client = makeRehearsalClient({
      getStatus: vi.fn().mockResolvedValue(
        rehearsalStatus({
          status: "running",
          recent_fills: [
            {
              coid: "coid-entry-1",
              side: "buy",
              qty: "1.5",
              price: "0.45",
              ts_ms: Date.UTC(2026, 9, 7, 9, 30, 5),
              kind: "fill",
            },
          ],
        }),
      ),
    });
    await renderPanel(client);

    const table = document.querySelector(".kbot-rehearsal__fills");
    const scroll = screen.getByTestId("rehearsal-fills-scroll");
    const history = screen.getByTestId("rehearsal-fills-panel");
    expect(scroll.contains(table as Node)).toBe(true);
    expect(history.contains(scroll)).toBe(true);
  });

  it("renders the explicit coral empty affordance when the backend reports no fills", async () => {
    await renderPanel(makeRehearsalClient());

    const history = screen.getByTestId("rehearsal-fills-panel");
    const empty = within(history).getByTestId("rehearsal-fills-empty");
    expect(empty.textContent).toBe("No simulated fills in this rehearsal yet");
    expect(empty.className).toContain("kbot-rehearsal__fills-empty");
    expect(document.querySelector(".kbot-rehearsal__fills")).toBeNull();
  });

  it("ships the sage/coral side badges and the coral empty affordance in the stylesheet", () => {
    const css = stripComments(readStylesheet());

    const buy = blocksFor(css, ".kbot-rehearsal__side--buy");
    expect(buy.length).toBeGreaterThanOrEqual(1);
    expect(buy.map((b) => b.declarations).join(";")).toContain("var(--sage");

    const sell = blocksFor(css, ".kbot-rehearsal__side--sell");
    expect(sell.length).toBeGreaterThanOrEqual(1);
    expect(sell.map((b) => b.declarations).join(";")).toContain("var(--coral");

    // The empty affordance stays coral-derived caution, never sage.
    const empty = blocksFor(css, ".kbot-rehearsal__fills-empty");
    expect(empty.length).toBeGreaterThanOrEqual(1);
    const emptyCss = empty.map((b) => b.declarations).join(";");
    expect(
      emptyCss.includes("var(--coral") ||
        emptyCss.includes("var(--danger-text"),
    ).toBe(true);
    expect(emptyCss).not.toContain("var(--sage");
  });
});

/* ------------------------------------------------------------------ */
/* 5. Loading / error / unavailable indicators on a muted panel surface */
/* ------------------------------------------------------------------ */

describe("RehearsalPanel Signal layout — loading, error and unavailable states", () => {
  it("renders the explicit loading indicator on the muted panel surface before the first read resolves", () => {
    const client = makeRehearsalClient({
      getStatus: vi.fn().mockReturnValue(new Promise<RehearsalStatus>(() => {})),
    });
    render(<RehearsalPanel client={client} />);

    const loading = screen.getByTestId("rehearsal-loading");
    expect(loading.textContent).toBe("Reading rehearsal status…");
    expect(loading.className).toContain("kbot-rehearsal__loading");
    // No status was confirmed yet, so no lifecycle claim is rendered.
    expect(screen.queryByTestId("rehearsal-sentence")).toBeNull();
    expect(screen.queryByTestId("rehearsal-holdings-panel")).toBeNull();
  });

  it("renders the read failure honestly with the retry affordance, keeping the last confirmed status when there is one", async () => {
    const client = makeRehearsalClient({
      getStatus: vi
        .fn()
        .mockResolvedValueOnce(rehearsalStatus({ status: "paused" }))
        .mockRejectedValue(new Error("rehearsal status failed: 503")),
    });
    render(<RehearsalPanel client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-status")).toBe("paused");
    });

    fireEvent.click(screen.getByRole("button", { name: /refresh status/i }));
    const unknown = await screen.findByTestId("rehearsal-unknown");
    expect(unknown.getAttribute("role")).toBe("alert");
    expect(unknown.textContent).toMatch(/Rehearsal status refresh failed/i);
    // The last confirmed status is kept, never replaced by an idle claim.
    expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-status")).toBe("paused");
  });

  it("renders the first-read failure as the honest unavailable state with a retry control", async () => {
    const client = makeRehearsalClient({
      getStatus: vi.fn().mockRejectedValue(new Error("rehearsal status failed: 503")),
    });
    render(<RehearsalPanel client={client} />);

    expect(await screen.findByTestId("rehearsal-load-failed")).toBeDefined();
    expect(screen.getByTestId("rehearsal-error").textContent).toBe(
      "rehearsal status failed: 503",
    );
    const retry = screen.getByRole("button", { name: /retry status/i });
    expect(retry).toBeDefined();
    expect(screen.queryByTestId("rehearsal-holdings-panel")).toBeNull();
    expect(screen.queryByTestId("rehearsal-commands-panel")).toBeNull();
  });

  it("renders a refused command in the coral-derived caution tone, keeping the last confirmed status", async () => {
    const client = makeRehearsalClient({
      start: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "rehearsal_not_idle",
        ok: false,
        message: "rehearsal already running",
      } satisfies RehearsalCommandResult),
    });
    await renderPanel(client);

    fireEvent.click(screen.getByRole("button", { name: /start rehearsal/i }));
    const error = await screen.findByTestId("rehearsal-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toBe("rehearsal already running");
    expect(screen.getByTestId("rehearsal-panel").getAttribute("data-rehearsal-status")).toBe("idle");
  });

  it("renders the honest unavailable surface when no rehearsal client is wired", () => {
    render(<RehearsalPanel client={null} />);

    const panel = screen.getByTestId("rehearsal-unavailable");
    expect(panel.textContent).toMatch(/Synthetic paper rehearsal/i);
    expect(panel.textContent).toMatch(/Rehearsal controls unavailable/);
    expect(screen.getByTestId("rehearsal-state-chip").textContent).toBe(
      "unavailable",
    );
    expect(screen.getByTestId("rehearsal-state-chip").className).toContain(
      "kbot-rehearsal__chip--coral",
    );
  });

  it("ships the muted panel surface for the loading and error indicators in the stylesheet", () => {
    const css = stripComments(readStylesheet());
    for (const selector of [
      ".kbot-rehearsal__loading",
      ".kbot-rehearsal__empty",
      ".kbot-rehearsal__error",
      ".kbot-rehearsal__unknown",
    ]) {
      const blocks = blocksFor(css, selector);
      expect(blocks.length).toBeGreaterThanOrEqual(1);
      const declarations = blocks.map((b) => b.declarations).join(";");
      expect(declarations).toContain("var(--surface");
      expect(declarations).toMatch(/border[^;]*var\(--line/);
      expect(declarations).toMatch(/radius/);
    }
    // The error and unknown text stays coral-derived danger, never sage.
    for (const selector of [".kbot-rehearsal__error", ".kbot-rehearsal__unknown"]) {
      const blocks = blocksFor(css, selector);
      const errorCss = blocks.map((b) => b.declarations).join(";");
      expect(
        errorCss.includes("var(--danger-text") || errorCss.includes("var(--coral"),
      ).toBe(true);
      expect(errorCss).not.toContain("var(--sage");
    }
  });
});

/* ------------------------------------------------------------------ */
/* 6. Width containment at 390px (shipped declarations)                */
/* ------------------------------------------------------------------ */

describe("RehearsalPanel Signal layout — width containment", () => {
  it("keeps the root width-contained so long coids, balances or labels never widen the page", () => {
    const css = stripComments(readStylesheet());
    const root = blocksFor(css, ".kbot-rehearsal");
    expect(root.length).toBeGreaterThanOrEqual(1);
    const declarations = root.map((b) => b.declarations).join(";");
    expect(declarationValue(declarations, "min-width")).toBe("0");
    const maxWidth = declarationValue(declarations, "max-width");
    const width = declarationValue(declarations, "width");
    expect(maxWidth === "100%" || width === "100%").toBe(true);
  });

  it("gives the dense fills table an explicit min-width inside its own scroll region", () => {
    const css = stripComments(readStylesheet());

    const scroll = blocksFor(css, ".kbot-rehearsal__scroll");
    expect(scroll.length).toBeGreaterThanOrEqual(1);
    const scrollCss = scroll.map((b) => b.declarations).join(";");
    expect(scrollCss).toMatch(/overflow-x:\s*auto/);
    expect(scrollCss).toMatch(/max-width:\s*100%/);

    const fills = blocksFor(css, ".kbot-rehearsal__fills");
    expect(fills.length).toBeGreaterThanOrEqual(1);
    expect(
      declarationValue(fills.map((b) => b.declarations).join(";"), "min-width"),
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
    // The command set stacks instead of overflowing.
    const narrowActions = selectorBlocks(narrowCss).filter((block) =>
      block.selector.includes("kbot-rehearsal__actions"),
    );
    expect(narrowActions.length).toBeGreaterThanOrEqual(1);
    for (const block of narrowActions) {
      expect(
        declarationValue(block.declarations, "grid-template-columns") ??
          declarationValue(block.declarations, "flex-direction"),
      ).toMatch(/minmax\(0,\s*1fr\)|column/);
    }
    // Dense tables keep an explicit internal-scroll min-width on mobile.
    const narrowTables = selectorBlocks(narrowCss).filter((block) =>
      block.selector.includes("kbot-rehearsal__fills"),
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
