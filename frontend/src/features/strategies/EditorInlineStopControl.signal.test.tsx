/**
 * EditorInlineStopControl — Signal presentation slice (KRELL-SIGNAL-20261010).
 *
 * These tests pin the approved Signal presentation for the inline
 * stop/pause/resume/disarm/raise-stop control the Editor mounts on every
 * Paper workstation open, so it reads as one surface with the already
 * migrated StatusStrip / AppHome / Navigation / StatusPanel:
 *
 *  - a scoped `.kbot-shell__inline-stop-root` section (the shell's own
 *    vocabulary, like StatusStrip) with the legacy
 *    `kbot-strategy-editor__inline-stop*` classes fully retired;
 *  - the armed/disarmed state line carries the scoped status chip
 *    vocabulary, with `--armed` / `--disarmed` / `--paused` modifiers
 *    derived only from the confirmed backend status — never from color
 *    alone, and never claiming "disarmed" while availability is unknown;
 *  - the raise-stop pair keeps its frozen contract (input, Apply, the
 *    remembered `stop at <value>` echo, verbatim refusal sentences from
 *    summarizePaperCommandRefusal) with sage reinforcing a confirmed
 *    raise and coral a refusal;
 *  - a new caption span renders the human-readable state sentence below
 *    the row without dropping any existing content;
 *  - `refreshSignal` still forces exactly one status read — no polling,
 *    no remount.
 *
 * jsdom has no layout engine, so the containment/tap-target/animation
 * proofs resolve the *actual shipped* declarations from
 * EditorInlineStopControl.signal.css (same approach as
 * LivePreflight.signal.test.tsx and BarInspector.signal.test.tsx). The
 * suite is RED on the old inherited-shell presentation and GREEN once
 * the Signal slice ships. The existing EditorInlineStopControl*.test.tsx
 * surfaces stay untouched and green.
 *
 * Transport note: every client here is an in-memory vi.fn() fake
 * standing in for the loopback command API. No real venue/engine state,
 * keys, orders or fills are exercised or implied by these tests.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EditorInlineStopControl } from "./EditorInlineStopControl";
import type {
  PaperClient,
  PaperCommandResult,
  PaperStatus,
} from "../paper/client";
import { summarizePaperCommandRefusal } from "../paper/paperCommandRefusalSummary";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(cleanup);

const ROOT = "kbot-shell__inline-stop-root";
const STATUS = "kbot-shell__inline-stop-status";
const APPLY = "kbot-shell__inline-stop-apply";

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

const unarmedStatus: PaperStatus = { schema_version: "1", armed: false };

function raiseOk(newStop: string): PaperCommandResult {
  return {
    schema_version: "1",
    code: "stop_raised",
    ok: true,
    message: `stop set: kraken SUIUSD -> ${newStop}`,
    effect: "changed",
  };
}

function refusalResult(message: string): PaperCommandResult {
  return {
    schema_version: "1",
    code: "invalid_stop",
    ok: false,
    message,
  };
}

// Hand-rolled fake: only the command surface the inline control touches.
// No network, no fetch; status reads are sequenced through refreshSignal.
function makePaperClient(
  overrides: Partial<PaperClient> = {},
): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue(armedStatus()),
    pauseEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_paused",
      ok: true,
      effect: "changed",
    }),
    resumeEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_resumed",
      ok: true,
      effect: "changed",
    }),
    disarm: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "disarmed",
      ok: true,
      effect: "changed",
    }),
    raiseStop: vi.fn().mockResolvedValue(raiseOk("6.5")),
    ...overrides,
  };
}

async function rootOf(client: PaperClient): Promise<HTMLElement> {
  render(<EditorInlineStopControl paperClient={client} refreshSignal={0} />);
  return (await screen.findByTestId("editor-inline-stop")) as HTMLElement;
}

function statusChip(root: HTMLElement): HTMLElement {
  const chip = root.querySelector(`.${STATUS}`) as HTMLElement | null;
  expect(chip).not.toBeNull();
  return chip as HTMLElement;
}

function applyButton(): HTMLButtonElement {
  return screen.getByTestId("editor-inline-stop-apply") as HTMLButtonElement;
}

function disarmButton(): HTMLButtonElement {
  return screen.getByTestId(
    "editor-inline-stop-disarm",
  ) as HTMLButtonElement;
}

/* ------------------------------------------------------------------ */
/* 1 + 2. Scoped wrapper: the legacy editor vocabulary is retired      */
/* ------------------------------------------------------------------ */

describe("EditorInlineStopControl Signal slice — scoped wrapper", () => {
  it("retires the legacy kbot-strategy-editor__inline-stop vocabulary and mounts the scoped shell root", async () => {
    const root = await rootOf(makePaperClient());

    expect(root.className).toContain(ROOT);
    // The old inherited-shell class set is gone from every element, not
    // merely composed underneath the new one.
    const legacy = root.querySelectorAll(
      '[class*="kbot-strategy-editor__inline-stop"]',
    );
    expect(legacy.length).toBe(0);
    expect(root.className).not.toContain("kbot-strategy-editor__inline-stop");
  });

  it("imports the Signal stylesheet from EditorInlineStopControl.tsx", () => {
    const source = readFileSync(
      join(here, "EditorInlineStopControl.tsx"),
      "utf8",
    );
    expect(source).toContain('import "./EditorInlineStopControl.signal.css";');
  });

  it("marks the status chip --disarmed (never --armed) when the confirmed status says armed === false", async () => {
    const client = makePaperClient({
      getStatus: vi.fn().mockResolvedValue(unarmedStatus),
    });
    const root = await rootOf(client);

    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();
    const chip = statusChip(root);
    expect(chip.className).toContain(`${STATUS}--disarmed`);
    expect(chip.className).not.toContain(`${STATUS}--armed`);
    expect(chip.textContent).toBe("No pack armed");
  });
});

/* ------------------------------------------------------------------ */
/* 3. Armed chip + entries badge modifiers                            */
/* ------------------------------------------------------------------ */

describe("EditorInlineStopControl Signal slice — armed status chip", () => {
  it("carries --armed while entries run, and adds the --paused badge modifier only when entries_paused is true", async () => {
    const running = await rootOf(
      makePaperClient({
        getStatus: vi.fn().mockResolvedValue(armedStatus()),
      }),
    );
    const runningChip = statusChip(running);
    expect(runningChip.className).toContain(`${STATUS}--armed`);
    expect(runningChip.className).not.toContain(`${STATUS}--disarmed`);
    expect(runningChip.className).not.toContain(`${STATUS}--paused`);
    expect(runningChip.textContent).toBe("Entries active");
    cleanup();

    const paused = await rootOf(
      makePaperClient({
        getStatus: vi.fn().mockResolvedValue(armedStatus({ entries_paused: true })),
      }),
    );
    const pausedChip = statusChip(paused);
    // The entries badge is the same chip: base status vocabulary plus the
    // --paused modifier; the verbatim sentence still carries the state.
    expect(pausedChip.className).toContain(`${STATUS}--armed`);
    expect(pausedChip.className).toContain(`${STATUS}--paused`);
    expect(pausedChip.textContent).toBe("Entries paused");
  });

  it("does not claim --disarmed while availability is unknown", async () => {
    const client = makePaperClient({
      getStatus: vi.fn().mockRejectedValue(new Error("transport down")),
    });
    const root = await rootOf(client);

    expect(
      await screen.findByTestId("editor-inline-stop-unavailable"),
    ).toBeDefined();
    const chip = statusChip(root);
    expect(chip.className).toContain(STATUS);
    expect(chip.className).not.toContain(`${STATUS}--disarmed`);
    expect(chip.className).not.toContain(`${STATUS}--armed`);
  });
});

/* ------------------------------------------------------------------ */
/* 4 + 5. Raise-stop outcome: sage success / coral refusal + caption  */
/* ------------------------------------------------------------------ */

describe("EditorInlineStopControl Signal slice — raise-stop outcome", () => {
  it("fills Apply sage and captions 'Stop raised to 6.5' after a confirmed raise_stop", async () => {
    const client = makePaperClient({
      raiseStop: vi.fn().mockResolvedValue(raiseOk("6.5")),
    });
    await rootOf(client);

    const input = await screen.findByTestId(
      "editor-inline-stop-new-stop",
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "6.5" } });
    await waitFor(() => {
      expect(applyButton().disabled).toBe(false);
    });
    fireEvent.click(applyButton());

    await waitFor(() => {
      expect(applyButton().className).toContain(`${APPLY}--success`);
    });
    expect(applyButton().className).not.toContain(`${APPLY}--refused`);
    expect(applyButton().className).toContain(APPLY);
    expect(
      screen.getByTestId("inline-stop-caption").textContent,
    ).toBe("Stop raised to 6.5");
    // The remembered echo stays, byte-identical: nothing is dropped.
    expect(screen.getByTestId("editor-inline-stop-at").textContent).toBe(
      "stop at 6.5",
    );
    expect(client.raiseStop).toHaveBeenCalledWith("kraken", "SUIUSD", "6.5");
  });

  it("fills Apply coral and captions the summarizePaperCommandRefusal reason verbatim after a refusal", async () => {
    const refusal = refusalResult(
      "new stop must be strictly above the current stop",
    );
    const client = makePaperClient({
      raiseStop: vi.fn().mockResolvedValue(refusal),
    });
    await rootOf(client);

    const input = await screen.findByTestId(
      "editor-inline-stop-new-stop",
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "0.25" } });
    await waitFor(() => {
      expect(applyButton().disabled).toBe(false);
    });
    fireEvent.click(applyButton());

    await waitFor(() => {
      expect(applyButton().className).toContain(`${APPLY}--refused`);
    });
    expect(applyButton().className).not.toContain(`${APPLY}--success`);
    expect(
      screen.getByTestId("inline-stop-caption").textContent,
    ).toBe(
      `Refused: ${summarizePaperCommandRefusal("Apply new stop", refusal).label}`,
    );
    // The verbatim refusal sentence surface is unchanged.
    expect(screen.getByTestId("editor-inline-stop-error").textContent).toBe(
      summarizePaperCommandRefusal("Apply new stop", refusal).label,
    );
  });

  it("keeps the scoped button/input vocabulary on the command row without widening the frozen contract", async () => {
    const root = await rootOf(makePaperClient());

    expect(
      screen.getByTestId("editor-inline-stop-pause").className,
    ).toContain("kbot-shell__inline-stop-pause");
    expect(
      screen.getByTestId("editor-inline-stop-resume").className,
    ).toContain("kbot-shell__inline-stop-resume");
    expect(
      screen.getByTestId("editor-inline-stop-disarm").className,
    ).toContain("kbot-shell__inline-stop-disarm");
    expect(
      screen.getByTestId("editor-inline-stop-pause").getAttribute("type"),
    ).toBe("button");
    expect(root.querySelector(".kbot-shell__inline-stop-row")).not.toBeNull();
    expect(
      root.querySelector(".kbot-shell__inline-stop-raise"),
    ).not.toBeNull();
    expect(
      screen.getByTestId("editor-inline-stop-new-stop").className,
    ).toContain("kbot-shell__inline-stop-input");
  });

  it("flips the pause/resume row from the resting seafoam treatment to the affirmative sage primary while armed", async () => {
    const css = stripComments(readStylesheet());
    // The armed (enabled, since disabled === !armed) pause/resume pair
    // carries the sage primary; the seafoam treatment is the resting
    // (disarmed) state and the Refresh affordance's.
    const sageArmedBlock = blocksFor(
      css,
      ".kbot-shell__inline-stop-pause:not(:disabled)",
    );
    expect(sageArmedBlock.length).toBeGreaterThan(0);
    const border = sageArmedBlock.find((block) =>
      block.declarations.includes("border-color"),
    );
    expect(border?.declarations).toContain("var(--sage, #b3dda8)");
    expect(border?.declarations).not.toContain("var(--seafoam");
  });
});

/* ------------------------------------------------------------------ */
/* 6. refreshSignal: exactly one read per bump, no polling             */
/* ------------------------------------------------------------------ */

describe("EditorInlineStopControl Signal slice — refreshSignal read", () => {
  it("a refreshSignal bump triggers exactly one new status fetch with no polling and no remount", async () => {
    const getStatus = vi
      .fn<() => Promise<PaperStatus>>()
      .mockResolvedValueOnce(unarmedStatus)
      .mockResolvedValue(armedStatus({ entries_paused: true }));
    const client = makePaperClient({ getStatus });
    const view = render(
      <EditorInlineStopControl paperClient={client} refreshSignal={0} />,
    );

    expect(await screen.findByTestId("editor-inline-stop-empty")).toBeDefined();
    expect(getStatus).toHaveBeenCalledTimes(1);
    const before = view.container.querySelector(
      '[data-testid="editor-inline-stop"]',
    );

    view.rerender(
      <EditorInlineStopControl paperClient={client} refreshSignal={1} />,
    );

    await waitFor(() => {
      expect(disarmButton().disabled).toBe(false);
    });
    expect(getStatus).toHaveBeenCalledTimes(2);

    // Settle: no timer, no follow-up poll fires on its own.
    await new Promise((resolve) => {
      setTimeout(resolve, 60);
    });
    expect(getStatus).toHaveBeenCalledTimes(2);

    // Same mounted instance, reconciled in place, with the scoped surface.
    const after = view.container.querySelector(
      '[data-testid="editor-inline-stop"]',
    );
    expect(after).toBe(before);
    expect((after as HTMLElement).className).toContain(ROOT);
    // Caption reflects the confirmed armed state; no stop was ever raised,
    // so it must not manufacture a stop echo.
    expect(screen.getByTestId("inline-stop-caption").textContent).toBe(
      "Armed at kraken SUIUSD · Entries paused",
    );
  });
});

/* ------------------------------------------------------------------ */
/* 7. Remembered raise after rearm: history, never current protection  */
/* ------------------------------------------------------------------ */

describe("EditorInlineStopControl Signal slice — remembered raise after rearm", () => {
  it("labels the remembered 'stop at' as the last confirmed raise, never as backend protection supplied by the post-rearm read", async () => {
    const getStatus = vi
      .fn<() => Promise<PaperStatus>>()
      .mockResolvedValue(armedStatus());
    const raiseStop = vi.fn().mockResolvedValue(raiseOk("7.0"));
    const disarm = vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "disarmed",
      ok: true,
      effect: "changed",
    });
    const client = makePaperClient({ getStatus, raiseStop, disarm });
    const view = render(
      <EditorInlineStopControl paperClient={client} refreshSignal={0} />,
    );

    // Confirmed raise in this arm: the raise confirmation is current.
    const input = (await screen.findByTestId(
      "editor-inline-stop-new-stop",
    )) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "7.0" } });
    await waitFor(() => {
      expect(applyButton().disabled).toBe(false);
    });
    fireEvent.click(applyButton());
    await waitFor(() => {
      expect(screen.getByTestId("inline-stop-caption").textContent).toBe(
        "Stop raised to 7.0",
      );
    });
    expect(screen.getByTestId("editor-inline-stop-at").textContent).toBe(
      "stop at 7.0",
    );

    // Confirmed disarm: the armed surface goes away.
    fireEvent.click(disarmButton());
    await waitFor(() => {
      expect(screen.getByTestId("editor-inline-stop-empty").textContent).toMatch(
        /No pack armed/,
      );
    });

    // Parent re-arms and bumps the signal. The post-Arm read returns
    // armed=true but never carries the resting stop, so the remembered
    // echo must present itself as history, not as this read's protection.
    view.rerender(
      <EditorInlineStopControl paperClient={client} refreshSignal={1} />,
    );

    const remembered = await screen.findByTestId("editor-inline-stop-at");
    // Persist contract: the remembered echo survives verbatim, no re-raise.
    expect(remembered.textContent).toBe("stop at 7.0");
    expect(raiseStop).toHaveBeenCalledTimes(1);
    // Truth: the caption names the last confirmed raise and says the
    // current backend stop is not supplied by this read.
    expect(screen.getByTestId("inline-stop-caption").textContent).toBe(
      "Last confirmed raise: 7.0 · this status read does not supply the current backend stop",
    );
    expect(screen.getByTestId("inline-stop-caption").textContent).not.toBe(
      "Stop raised to 7.0",
    );
    expect(remembered.getAttribute("title")).toBe(
      "Historical confirmation from an earlier arm; the current status read does not supply the backend stop",
    );
    expect(disarm).toHaveBeenCalledTimes(1);
  });
});

/* ------------------------------------------------------------------ */
/* Stylesheet reader (shipped CSS, not an expectation string)          */
/* ------------------------------------------------------------------ */

let cssCache = "";

function readStylesheet(): string {
  if (cssCache === "") {
    cssCache = readFileSync(
      join(here, "EditorInlineStopControl.signal.css"),
      "utf8",
    );
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

function selectorMatches(selectorList: string, selector: string): boolean {
  return selectorList
    .split(",")
    .some((part) => part.trim().endsWith(selector));
}

function blocksFor(css: string, selector: string): CssBlock[] {
  return selectorBlocks(css).filter((block) =>
    selectorMatches(block.selector, selector),
  );
}

const APPROVED_HEX = new Set([
  "#0e1c29",
  "#14222e",
  "#18354a",
  "#22465d",
  "#a8d8d1",
  "#b3dda8",
  "#cc9689",
  "#e9f0f5",
  "#abc4d8",
  // tokens.css semantic-role values, used as var() fallbacks exactly as
  // StatusPanel.signal.css and shell.css consume them.
  "#172a1d", // --action-primary-text (sage-filled button label)
  "#e0a296", // --danger-text (coral-derived caution text)
]);

describe("EditorInlineStopControl Signal slice — stylesheet contract", () => {
  it("scopes every selector under .kbot-shell__inline-stop-root", () => {
    const css = stripComments(readStylesheet());
    const selectors = [
      ...css.matchAll(/(^|[{}])\s*([^{}@]+)\{/g),
    ].map((match) => match[2].trim());
    expect(selectors.length).toBeGreaterThan(0);
    for (const selector of selectors) {
      expect(selector).toContain(ROOT);
    }
  });

  it("consumes only the approved palette hexes as var() fallbacks", () => {
    const css = stripComments(readStylesheet());
    const hexes = css.match(/#[0-9a-fA-F]{3,8}\b/g) ?? [];
    expect(hexes.length).toBeGreaterThan(0);
    for (const hex of hexes) {
      expect(APPROVED_HEX.has(hex.toLowerCase())).toBe(true);
    }
  });

  it("adds no fonts, remote assets or base64 payloads", () => {
    const css = readStylesheet();
    expect(css).not.toMatch(/@font-face/);
    expect(css).not.toMatch(/url\(/i);
    expect(css).not.toMatch(/data:/i);
  });

  it("animates only the caption swap, opacity-only at 120ms", () => {
    const css = stripComments(readStylesheet());
    const transitions = [
      ...css.matchAll(/transition\s*:\s*([^;]+);/g),
    ].map((match) => match[1].trim());
    expect(transitions.length).toBeGreaterThan(0);
    for (const transition of transitions) {
      expect(transition).toMatch(/^opacity\s+120ms\s+ease$/);
    }
    expect(css).not.toMatch(/@keyframes/);
    expect(css).not.toMatch(/animation\s*:/);
  });

  it("keeps >=44px tap targets and a wrapping row at <=390px", () => {
    const css = stripComments(readStylesheet());
    const mobileMatch = css.match(
      /@media\s*\(max-width:\s*390px\)\s*\{([\s\S]*)\}\s*$/,
    );
    expect(mobileMatch).not.toBeNull();
    const mobile = mobileMatch as RegExpMatchArray;
    const body = mobile[1];
    expect(body).toMatch(
      new RegExp(`\\.kbot-shell__inline-stop-input[^}]*min-height\\s*:\\s*44px`),
    );
    expect(body).toMatch(
      new RegExp(`${APPLY}[^}]*min-height\\s*:\\s*44px`),
    );
    expect(body).toMatch(/flex-wrap\s*:\s*wrap/);
    expect(body).toMatch(/font-size\s*:\s*(?:1[0-4](?:\.[0-9]+)?px)/);
  });
});
