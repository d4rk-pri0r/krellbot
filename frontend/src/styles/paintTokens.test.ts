/**
 * Paint primitives — KRELL-SIGNAL-20261010 (issue 96).
 *
 * Ordinary operational white/black color-mix paint (the sage primary
 * button's 92% white highlight mixes and the overlay #000 shadow
 * washes) must come from the two shared primitive tokens
 * --paint-white / --paint-black, declared once in tokens.css, instead
 * of per-file raw literals.
 *
 * This pins the exact substitution contract: computed colors, mix
 * percentages, var() fallback literals, selectors and layout are all
 * unchanged — only the raw white/black color-mix arguments become
 * var(--paint-white)/var(--paint-black). Supplied artwork literals
 * elsewhere are out of scope here and remain untouched.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const stylesDir = dirname(fileURLToPath(import.meta.url));
const css = (relative: string): string =>
  readFileSync(join(stylesDir, relative), "utf8");

const tokens = css("tokens.css");

/** The seven operational surfaces named by the issue, relative to styles/. */
const SURFACES: ReadonlyArray<[string, string]> = [
  ["LivePreflight", "../features/deployments/LivePreflight.signal.css"],
  ["RehearsalPanel", "../features/paper/RehearsalPanel.signal.css"],
  ["Editor", "../features/strategies/Editor.signal.css"],
  ["SavedStrategyLibrary", "../features/strategies/SavedStrategyLibrary.signal.css"],
  ["CommandPalette", "../shell/CommandPalette.signal.css"],
  ["JobsDrawer", "../shell/JobsDrawer.signal.css"],
  ["shell", "shell.css"],
];

/** Total color-mix( ... ) calls per surface before/after the change. */
const EXPECTED_MIX_COUNTS: Readonly<Record<string, number>> = {
  LivePreflight: 6,
  RehearsalPanel: 26,
  Editor: 30,
  SavedStrategyLibrary: 13,
  CommandPalette: 10,
  JobsDrawer: 16,
  shell: 21,
};

/** Paint-token references each surface must carry after substitution. */
const EXPECTED_PAINT_REFS: Readonly<Record<string, [number, number]>> = {
  // [var(--paint-white) count, var(--paint-black) count]
  LivePreflight: [2, 0],
  RehearsalPanel: [2, 0],
  Editor: [2, 0],
  SavedStrategyLibrary: [2, 0],
  CommandPalette: [0, 1],
  JobsDrawer: [0, 1],
  shell: [0, 2],
};

/** Extract every color-mix( ... ) call (balanced parens) from source. */
function colorMixCalls(source: string): string[] {
  const calls: string[] = [];
  const marker = "color-mix(";
  let at = source.indexOf(marker);
  while (at !== -1) {
    let depth = 1;
    let end = at + marker.length;
    while (end < source.length && depth > 0) {
      if (source[end] === "(") depth += 1;
      else if (source[end] === ")") depth -= 1;
      end += 1;
    }
    calls.push(source.slice(at, end));
    at = source.indexOf(marker, end);
  }
  return calls;
}

/**
 * True when a mix call still carries raw white/black paint outside
 * var() fallbacks: #fff/#ffffff, #000/#000000 or the bare keywords.
 */
function hasRawPaint(call: string): boolean {
  const outsideVarFallbacks = call.replace(/var\([^)]*\)/g, "");
  return /#fff(?:fff)?\b|#000(?:000)?\b|\bwhite\b|\bblack\b/i.test(
    outsideVarFallbacks,
  );
}

const count = (source: string, needle: string): number =>
  source.split(needle).length - 1;

describe("Paint primitives (issue 96, KRELL-SIGNAL-20261010)", () => {
  it("declares the shared primitive paint tokens with exact values", () => {
    expect(tokens).toMatch(/--paint-white\s*:\s*#ffffff\s*;/i);
    expect(tokens).toMatch(/--paint-black\s*:\s*#000000\s*;/i);
  });

  it("keeps the nine approved palette tokens unchanged", () => {
    const approved: ReadonlyArray<[string, string]> = [
      ["--navy", "#0e1c29"],
      ["--surface", "#14222e"],
      ["--panel", "#18354a"],
      ["--line", "#22465d"],
      ["--text", "#e9f0f5"],
      ["--muted", "#abc4d8"],
      ["--seafoam", "#a8d8d1"],
      ["--sage", "#b3dda8"],
      ["--coral", "#cc9689"],
    ];
    for (const [name, value] of approved) {
      expect(tokens).toMatch(new RegExp(`${name}\\s*:\\s*${value}\\s*;`, "i"));
    }
  });

  describe.each(SURFACES)("%s", (name, rel) => {
    const source = css(rel);

    it("declares the same total number of color-mix formulas", () => {
      expect(colorMixCalls(source)).toHaveLength(EXPECTED_MIX_COUNTS[name]);
    });

    it("carries no raw white/black paint inside color-mix arguments", () => {
      const raw = colorMixCalls(source).filter(hasRawPaint);
      expect(raw).toEqual([]);
    });

    it("references the shared paint tokens exactly as often as substituted", () => {
      expect(count(source, "var(--paint-white)")).toBe(
        EXPECTED_PAINT_REFS[name][0],
      );
      expect(count(source, "var(--paint-black)")).toBe(
        EXPECTED_PAINT_REFS[name][1],
      );
    });
  });

  it("preserves the exact substituted formulas and mix percentages", () => {
    const whiteMix =
      "color-mix(in srgb, var(--sage, #b3dda8) 92%, var(--paint-white))";
    for (const rel of [
      "../features/deployments/LivePreflight.signal.css",
      "../features/paper/RehearsalPanel.signal.css",
      "../features/strategies/Editor.signal.css",
      "../features/strategies/SavedStrategyLibrary.signal.css",
    ]) {
      expect(count(css(rel), whiteMix)).toBe(2);
    }
    expect(
      count(
        css("shell.css"),
        "color-mix(in srgb, var(--paint-black) 45%, transparent)",
      ),
    ).toBe(2);
    expect(
      count(
        css("../shell/JobsDrawer.signal.css"),
        "color-mix(in srgb, var(--paint-black) 45%, transparent)",
      ),
    ).toBe(1);
    expect(
      count(
        css("../shell/CommandPalette.signal.css"),
        "color-mix(in srgb, var(--paint-black) 50%, transparent)",
      ),
    ).toBe(1);
  });
});
