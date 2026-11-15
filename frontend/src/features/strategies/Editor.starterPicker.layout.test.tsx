/**
 * Starter picker item layout — KRELL-SIGNAL-20261010.
 *
 * Pins the shipped Editor.signal.css declarations that keep starter
 * titles single-line readable and the Use action auto-sized at the
 * 1440×900 workstation viewport. jsdom has no layout engine, so these
 * assertions read the real stylesheet (same approach as other Signal
 * layout suites). They go RED if the two-column auto-placement that
 * crushed labels to ~0px / Use to ~26px returns.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));

function readStylesheet(): string {
  return readFileSync(join(here, "Editor.signal.css"), "utf8");
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "");
}

describe("starter picker item layout at 1440×900", () => {
  it("places label and description on the readable track with Use in an auto-sized action column", () => {
    const css = stripComments(readStylesheet());

    expect(css).toMatch(
      /\.kbot-strategy-editor\s+\.kbot-starter-picker__item\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+auto/,
    );
    expect(css).toMatch(
      /\.kbot-strategy-editor\s+\.kbot-starter-picker__item\s*\{[^}]*grid-template-areas:\s*"label action"\s*"description action"/,
    );
    expect(css).toMatch(
      /\.kbot-strategy-editor\s+\.kbot-starter-picker__item-label\s*\{[^}]*grid-area:\s*label/,
    );
    expect(css).toMatch(
      /\.kbot-strategy-editor\s+\.kbot-starter-picker__item-description\s*\{[^}]*grid-area:\s*description/,
    );
    expect(css).toMatch(
      /\.kbot-strategy-editor\s+\.kbot-starter-picker__action\s*\{[^}]*grid-area:\s*action/,
    );
  });

  it("keeps starter titles single-line (no overflow-wrap:anywhere letter stack)", () => {
    const css = stripComments(readStylesheet());
    const labelMatch = css.match(
      /\.kbot-strategy-editor\s+\.kbot-starter-picker__item-label\s*\{([^}]*)\}/,
    );
    expect(labelMatch).not.toBeNull();
    const labelCss = labelMatch![1];
    expect(labelCss).toMatch(/white-space:\s*nowrap/);
    expect(labelCss).toMatch(/text-overflow:\s*ellipsis/);
    expect(labelCss).not.toMatch(/overflow-wrap:\s*anywhere/);
  });

  it("sizes the Use action to its label instead of a crushed track", () => {
    const css = stripComments(readStylesheet());
    const actionMatch = css.match(
      /\.kbot-strategy-editor\s+\.kbot-starter-picker__action\s*\{([^}]*)\}/,
    );
    expect(actionMatch).not.toBeNull();
    const actionCss = actionMatch![1];
    expect(actionCss).toMatch(/width:\s*max-content/);
    expect(actionCss).toMatch(/white-space:\s*nowrap/);
    expect(actionCss).toMatch(/flex:\s*none/);
    expect(actionCss).toMatch(/min-height:\s*34px/);
  });
});
