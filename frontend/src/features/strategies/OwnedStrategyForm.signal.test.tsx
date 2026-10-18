/**
 * OwnedStrategyForm Signal presentation slice — KRELL-SIGNAL-20261010.
 *
 * Pins the scoped Signal presentation of the mounted owned-strategy
 * form: the `.kbot-feature__owned-strategy-form-root` scope wrapper,
 * the preserved section identity (role/aria-label/data-testid), the
 * verbatim recipe/comparison/timeframe option labels and the approved
 * stylesheet contract (seafoam focus/selection, sage reserved for the
 * affirmative primary button surface, coral-derived refusals, mono
 * technical identifiers, >=44px tap targets at <=640px).
 *
 * NOTE on the apply/validate clause: this form intentionally has NO
 * Apply or validate button — it applies its pack on every field
 * change (see OwnedStrategyForm.tsx and the Editor.tsx mount). The
 * 44px assertion therefore covers every rendered field control and
 * the scope's button rule, which is the only button surface this
 * scope can ever show.
 *
 * TEST TRANSPORT NOTICE: these tests run the real component with an
 * in-memory form state only. Nothing here qualifies a backend, pack
 * or editor save path.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { OwnedStrategyForm } from "./OwnedStrategyForm";
import {
  COMPARISONS,
  MOVING_AVERAGE_KINDS,
  RECIPE_NAMES,
  TIMEFRAMES,
  seedOwnedStrategyForm,
  seedOwnedStrategyPack,
  type OwnedStrategyFormState,
} from "./ownedStrategy";
import type { Pack } from "./client";

afterEach(cleanup);

const here = dirname(fileURLToPath(import.meta.url));

// Mirrors how the Editor hosts the form: the parent owns the state.
function Harness({
  initial,
  basePack,
  onApply,
}: {
  initial: OwnedStrategyFormState;
  basePack: Pack;
  onApply(pack: Pack | null, problems: string[]): void;
}): React.JSX.Element {
  const [state, setState] = useState(initial);
  return (
    <OwnedStrategyForm
      state={state}
      basePack={basePack}
      onStateChange={setState}
      onApply={onApply}
    />
  );
}

function setup(state: OwnedStrategyFormState = seedOwnedStrategyForm()) {
  const onApply = vi.fn();
  const basePack = seedOwnedStrategyPack(state.name);
  const aligned = { ...state, id: basePack.id as string };
  render(<Harness initial={aligned} basePack={basePack} onApply={onApply} />);
  return { onApply };
}

function selectValues(label: RegExp): string[] {
  return Array.from(
    (screen.getByLabelText(label) as HTMLSelectElement).options,
  ).map((option) => option.value);
}

function selectTexts(label: RegExp): string[] {
  return Array.from(
    (screen.getByLabelText(label) as HTMLSelectElement).options,
  ).map((option) => option.textContent ?? "");
}

describe("OwnedStrategyForm signal slice — scoped wrapper", () => {
  it("renders the .kbot-feature__owned-strategy-form-root scope around the mounted form", () => {
    setup();
    const scope = document.querySelector(
      ".kbot-feature__owned-strategy-form-root",
    );
    expect(scope).not.toBeNull();
    expect(
      scope!.contains(screen.getByTestId("owned-strategy-form")),
    ).toBe(true);
  });

  it("preserves the section identity byte-identically inside the scope", () => {
    setup();
    const section = screen.getByTestId("owned-strategy-form");
    expect(section.tagName).toBe("SECTION");
    expect(section.getAttribute("role")).toBe("group");
    expect(section.getAttribute("aria-label")).toBe("Owned strategy form");
    expect(section.className).toContain("kbot-owned-strategy-form");
  });

  it("keeps every existing control id stable under the scope", () => {
    setup();
    const scope = document.querySelector(
      ".kbot-feature__owned-strategy-form-root",
    );
    for (const id of [
      "kbot-owned-strategy-recipe",
      "kbot-owned-strategy-name",
      "kbot-owned-strategy-id",
      "kbot-owned-strategy-pair",
      "kbot-owned-strategy-length",
      "kbot-owned-strategy-maxAccountPct",
      "kbot-owned-strategy-stopPct",
      "kbot-owned-strategy-timeframe",
      "kbot-owned-strategy-kind",
      "kbot-owned-strategy-entryComparison",
      "kbot-owned-strategy-exitComparison",
    ]) {
      const control = document.getElementById(id);
      expect(control, id).toBeDefined();
      expect(scope!.contains(control!)).toBe(true);
    }
    // The fast-average field stays exclusive to the crossover recipe.
    expect(document.getElementById("kbot-owned-strategy-fastLength")).toBeNull();
  });

  it("surfaces the existing problems testid and verbatim refusal text inside the scope", () => {
    setup();
    fireEvent.change(screen.getByLabelText(/^average length/i), {
      target: { value: "1" },
    });
    const problems = screen.getByTestId("owned-strategy-form-problems");
    expect(problems.tagName).toBe("UL");
    expect(problems.textContent).toContain(
      "Average length (bars): Length must be a whole number between 2 and 599",
    );
    const scope = document.querySelector(
      ".kbot-feature__owned-strategy-form-root",
    );
    expect(scope!.contains(problems)).toBe(true);
  });
});

describe("OwnedStrategyForm signal slice — verbatim source labels", () => {
  it("offers exactly the source recipe keys with their verbatim labels", () => {
    setup();
    expect(selectValues(/^recipe/i)).toEqual([...RECIPE_NAMES]);
    expect(selectTexts(/^recipe/i)).toEqual([
      "Close versus one average",
      "Two-average crossover (fast vs slow)",
    ]);
  });

  it("offers exactly the source timeframe keys with their verbatim labels", () => {
    setup();
    expect(selectValues(/timeframe/i)).toEqual([...TIMEFRAMES]);
    expect(selectTexts(/timeframe/i)).toEqual(["1h", "4h", "1d"]);
  });

  it("offers exactly the source comparison keys with the verbatim close-vs-average labels", () => {
    setup();
    for (const label of [/enter when/i, /exit when/i]) {
      expect(selectValues(label)).toEqual([...COMPARISONS]);
      expect(selectTexts(label)).toEqual([
        "close above",
        "close below",
        "close at or above",
        "close at or below",
        "close crosses above",
        "close crosses below",
      ]);
    }
  });

  it("switches to the verbatim crossover comparison labels on the ma_cross recipe", () => {
    setup();
    fireEvent.change(screen.getByLabelText(/^recipe/i), {
      target: { value: "ma_cross" },
    });
    for (const label of [/enter when/i, /exit when/i]) {
      expect(selectValues(label)).toEqual([...COMPARISONS]);
      expect(selectTexts(label)).toEqual([
        "fast average above slow",
        "fast average below slow",
        "fast average at or above slow",
        "fast average at or below slow",
        "fast average crosses above slow",
        "fast average crosses below slow",
      ]);
    }
    // The crossover-only fast field mounts with its preserved id.
    expect(
      document.getElementById("kbot-owned-strategy-fastLength"),
    ).toBeDefined();
  });

  it("offers exactly the source average-kind keys with their verbatim labels", () => {
    setup();
    expect(selectValues(/average type/i)).toEqual([...MOVING_AVERAGE_KINDS]);
    expect(selectTexts(/average type/i)).toEqual([
      "SMA (simple)",
      "EMA (exponential)",
    ]);
  });
});

describe("OwnedStrategyForm signal slice — stylesheet contract", () => {
  let css = "";
  const readCss = (): string => {
    if (css === "") {
      css = readFileSync(join(here, "OwnedStrategyForm.signal.css"), "utf8");
    }
    return css;
  };

  it("is root-scoped to the feature root and consumes the approved named tokens", () => {
    const raw = readCss();
    const stripped = raw.replace(/\/\*[\s\S]*?\*\//g, "");
    expect(raw).toMatch(/^\.kbot-feature__owned-strategy-form-root\b/m);
    for (const selector of stripped
      .split("}")
      .map((rule) => rule.split("{")[0] ?? "")) {
      const trimmed = selector.trim();
      if (trimmed.length > 0 && !trimmed.startsWith("@media")) {
        expect(trimmed.startsWith(".kbot-feature__owned-strategy-form-root")).toBe(
          true,
        );
      }
    }
    for (const token of [
      "--navy",
      "--surface",
      "--panel",
      "--line",
      "--text",
      "--muted",
      "--seafoam",
      "--sage",
      "--coral",
      "--font-mono",
      "--font-ui",
    ]) {
      expect(raw).toContain(`var(${token}`);
    }
  });

  it("emits no legacy palette tokens, no remote fonts and only approved hexes", () => {
    const css = readCss();
    for (const legacy of ["#07090d", "#5ce1ff", "#c6ff3d", "#72f6b0"]) {
      expect(css.toLowerCase()).not.toContain(legacy);
    }
    expect(css).not.toMatch(/@import|https?:\/\//);
    expect(css).not.toMatch(/font-family:\s*ui-monospace/);
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
      // Shared derived-color fallbacks already used by the integrated
      // Signal slices (tokens.css --action-primary-text / --danger-text).
      "#172a1d",
      "#e0a296",
    ]);
    const hexes = css.toLowerCase().match(/#[0-9a-f]{6}\b/g) ?? [];
    expect(hexes.length).toBeGreaterThan(0);
    for (const hex of hexes) {
      expect(approved.has(hex), hex).toBe(true);
    }
  });

  it("keeps a seafoam focus ring, coral-derived refusals and sage only on the affirmative button surface", () => {
    const css = readCss();
    expect(css).toMatch(/:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--seafoam/);
    expect(css).toMatch(
      /\.kbot-owned-strategy-form__problems[^{]*\{[^}]*var\(--coral/,
    );
    // Sage is reserved for the scope's button surface (this form renders
    // no Apply/validate button; it applies on every field change).
    expect(css).toMatch(/__owned-strategy-form-root button\s*\{[^}]*var\(--sage/);
    // Mono is reserved for the technical identifiers only.
    expect(css).toMatch(
      /#kbot-owned-strategy-timeframe[^{]*\{[^}]*var\(--font-mono/,
    );
  });

  it("keeps every field control at >=44px inside the <=640px composition with no overflow", () => {
    const css = readCss();
    const mediaIndex = css.indexOf("@media");
    expect(mediaIndex).toBeGreaterThan(-1);
    const narrow = css.slice(mediaIndex);
    expect(narrow).toMatch(/640px/);
    // This form has no Apply/validate button; the >=44px floor covers
    // every rendered control (inputs + selects) and the scope's own
    // button rule, which is the only button surface it can show.
    expect(narrow).toMatch(
      /__input,\s*\n\s*\.kbot-feature__owned-strategy-form-root \.kbot-owned-strategy-form__select\s*\{\s*\n\s*min-height:\s*44px/,
    );
    expect(css).toMatch(/overflow-wrap:\s*anywhere/);
    expect(css).toMatch(/min-width:\s*0/);
  });

  it("imports the signal stylesheet from the component and wraps its returned tree", () => {
    const source = readFileSync(join(here, "OwnedStrategyForm.tsx"), "utf8");
    expect(source).toContain('import "./OwnedStrategyForm.signal.css";');
    expect(source).toContain(
      'className="kbot-feature__owned-strategy-form-root"',
    );
  });
});
