/**
 * CommandPalette — scoped Signal presentation vocabulary evidence.
 * Contract: KRELL-SIGNAL-20261010.
 *
 * Pins the owner-approved scoped class vocabulary the mounted command
 * palette renders (frontend/src/shell/CommandPalette.tsx, mounted by
 * WorkstationShell behind the ⌘K/Ctrl+K binding) without touching the
 * legacy unscoped CommandPalette.test.tsx or the component itself:
 * every expectation here renders with open={true} and a no-op onClose
 * through the existing CommandPaletteProps contract, and every test
 * references an existing data-testid marker verbatim
 * (command-palette / command-palette-badge), which this slice must not
 * alter. The preserved Escape close, focus-on-open and return-focus
 * semantics are pinned here exactly as the component implements them.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { CommandPalette } from "./CommandPalette";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const cssSource = readFileSync(
  resolve(__dirname, "CommandPalette.signal.css"),
  "utf8",
);

function renderPalette(open = true): HTMLElement {
  render(<CommandPalette open={open} onClose={() => {}} />);
  return screen.getByTestId("command-palette");
}

describe("CommandPalette Signal presentation (KRELL-SIGNAL-20261010)", () => {
  it("mounts the scoped Signal root with the shared dialog semantics", () => {
    const root = renderPalette();
    expect(root).toBeInstanceOf(HTMLElement);
    // Exact tokens, not substrings: a renamed or suffixed class must fail.
    expect(root.classList.contains("kbot-shell__palette-root")).toBe(true);
    expect(root.classList.contains("kbot-palette")).toBe(true);
    expect(root.getAttribute("role")).toBe("dialog");
    expect(root.getAttribute("aria-modal")).toBe("true");
    expect(root.getAttribute("aria-label")).toBe("Command palette");
  });

  it("renders the scoped box without a duplicate Local preview badge", () => {
    const root = renderPalette();
    const box = root.querySelector<HTMLElement>(".kbot-shell__palette-box");
    expect(box).toBeInstanceOf(HTMLElement);
    expect(box?.classList.contains("kbot-palette__box")).toBe(true);
    expect(box?.parentElement).toBe(root);
    expect(screen.queryByTestId("command-palette-badge")).toBeNull();
  });

  it("un-hides the scoped label into the visible Signal heading and names the input", () => {
    const root = renderPalette();
    const label = root.querySelector<HTMLElement>(".kbot-shell__palette-label");
    expect(label).toBeInstanceOf(HTMLElement);
    expect(label?.classList.contains("kbot-palette__label")).toBe(true);
    expect(label?.tagName).toBe("LABEL");
    expect(label?.textContent).toBe("Find an action, strategy, or view");
    const input = root.querySelector<HTMLElement>(".kbot-shell__palette-input");
    expect(label?.getAttribute("for")).toBe(input?.getAttribute("id"));
    expect(input?.getAttribute("aria-label")).toBe("Command input");
  });

  it("keeps the scoped Manrope-first command input focused on open", () => {
    const root = renderPalette();
    const input = root.querySelector<HTMLElement>(".kbot-shell__palette-input");
    expect(input).toBeInstanceOf(HTMLElement);
    expect(input?.classList.contains("kbot-palette__input")).toBe(true);
    expect(input?.getAttribute("type")).toBe("text");
    expect(input?.getAttribute("autocomplete")).toBe("off");
    expect(input?.getAttribute("spellcheck")).toBe("false");
    expect(input?.getAttribute("placeholder")).toBe(
      "Type to search actions, strategies, or views",
    );
    // Focus-on-open semantics preserved exactly as mounted.
    expect(document.activeElement).toBe(input);
  });

  it("keeps the scoped keyboard hint naming both Esc and Ctrl+K", () => {
    const root = renderPalette();
    const hint = root.querySelector<HTMLElement>(".kbot-shell__palette-hint");
    expect(hint).toBeInstanceOf(HTMLElement);
    expect(hint?.classList.contains("kbot-palette__hint")).toBe(true);
    expect(hint?.tagName).toBe("P");
    expect(hint?.textContent).toBe("Press Esc to close · Ctrl+K from anywhere");
    expect(hint?.parentElement).toBe(
      root.querySelector<HTMLElement>(".kbot-shell__palette-box"),
    );
  });

  it("stays unmounted while closed", () => {
    render(<CommandPalette open={false} onClose={() => {}} />);
    expect(screen.queryByTestId("command-palette")).toBeNull();
  });

  it("preserves the Escape close semantics through the scoped root", () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);
    expect(screen.getByTestId("command-palette")).toBeInstanceOf(HTMLElement);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("preserves the return-focus semantics on close", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();

    const { unmount } = render(<CommandPalette open onClose={() => {}} />);
    expect(screen.getByTestId("command-palette")).toBeInstanceOf(HTMLElement);
    const input = screen
      .getByTestId("command-palette")
      .querySelector<HTMLElement>(".kbot-shell__palette-input");
    expect(document.activeElement).toBe(input);

    unmount();
    expect(document.activeElement).toBe(opener);
    document.body.removeChild(opener);
  });

  it("scopes every stylesheet rule under the approved palette root selector", () => {
    renderPalette();
    // @keyframes names are global; strip them. Nested @media bodies still
    // must scope every rule under the palette root (same contract as
    // CommandPalette.test.tsx).
    let stripped = cssSource.replace(/\/\*[\s\S]*?\*\//g, "");
    while (stripped.includes("@keyframes")) {
      const at = stripped.indexOf("@keyframes");
      const open = stripped.indexOf("{", at);
      let depth = 1;
      let j = open + 1;
      while (j < stripped.length && depth > 0) {
        if (stripped[j] === "{") depth += 1;
        else if (stripped[j] === "}") depth -= 1;
        j += 1;
      }
      stripped = stripped.slice(0, at) + stripped.slice(j);
    }
    const mediaBodies: string[] = [];
    let base = "";
    let i = 0;
    while (i < stripped.length) {
      const at = stripped.indexOf("@media", i);
      if (at === -1) {
        base += stripped.slice(i);
        break;
      }
      base += stripped.slice(i, at);
      const open = stripped.indexOf("{", at);
      let depth = 1;
      let j = open + 1;
      while (j < stripped.length && depth > 0) {
        if (stripped[j] === "{") depth += 1;
        else if (stripped[j] === "}") depth -= 1;
        j += 1;
      }
      mediaBodies.push(stripped.slice(open + 1, j - 1));
      i = j;
    }
    const blocks = Array.from(base.matchAll(/([^{}]+)\{([^{}]*)\}/g));
    expect(blocks.length).toBeGreaterThan(0);
    for (const block of blocks) {
      expect(block[1]).toContain(".kbot-shell__palette-root");
    }
    for (const body of mediaBodies) {
      for (const block of body.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
        expect(block[1]).toContain(".kbot-shell__palette-root");
      }
    }
    // The approved scoped child selectors are nested under the root, not flat.
    for (const scoped of [
      ".kbot-shell__palette-box",
      ".kbot-shell__palette-meta",
      ".kbot-shell__palette-badge",
      ".kbot-shell__palette-label",
      ".kbot-shell__palette-input",
      ".kbot-shell__palette-hint",
    ]) {
      expect(cssSource).toContain(`${".kbot-shell__palette-root"} ${scoped}`);
    }
  });

  it("keeps the approved Signal token fallbacks and the narrow-viewport layer", () => {
    renderPalette();
    expect(screen.getByTestId("command-palette")).toBeInstanceOf(HTMLElement);
    expect(cssSource).toContain('var(--font-ui, "Manrope"');
    expect(cssSource).toContain("var(--navy, #0e1c29)");
    expect(cssSource).toContain("var(--panel, #18354a)");
    expect(cssSource).toContain("var(--surface, #14222e)");
    expect(cssSource).toContain("var(--line, #22465d)");
    expect(cssSource).toContain("var(--text, #e9f0f5)");
    expect(cssSource).toContain("var(--muted, #abc4d8)");
    expect(cssSource).toContain("var(--seafoam, #a8d8d1)");
    expect(cssSource).toContain("@media (max-width: 640px)");
    expect(cssSource).toMatch(/height:\s*44px/);
    expect(cssSource).toMatch(/min-height:\s*44px/);
    expect(cssSource).toMatch(/overflow-wrap:\s*anywhere/);
    // No new color tokens of its own and no neon-lime/cyan reintroduction.
    expect([...cssSource.matchAll(/--[\w-]+\s*:/g)]).toEqual([]);
    expect(cssSource).not.toContain("#a3ff12");
    expect(cssSource).not.toContain("lime");
    expect(cssSource).not.toContain("cyan");
  });
});
