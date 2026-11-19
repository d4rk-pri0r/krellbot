import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "FirstRunWizard.signal.css"), "utf8");

describe("FirstRunWizard Signal CSS contract", () => {
  it("names Signal tokens, sage CTA, and disables motion under prefers-reduced-motion", () => {
    expect(css).toMatch(/KRELL-SIGNAL-20261010/);
    expect(css).toMatch(/--navy/);
    expect(css).toMatch(/--sage|--action-primary-bg/);
    expect(css).toMatch(/--seafoam|--focus-ring/);
    expect(css).toMatch(/--font-ui|Manrope/);
    expect(css).toMatch(/min-height:\s*44px/);
    expect(css).toMatch(/kbot-first-run-wizard-enter/);
    expect(css).toMatch(/kbot-first-run-wizard-win-enter/);
    expect(css).not.toMatch(/\bpurple\b/i);
    expect(css).not.toMatch(/box-shadow:[^;]*0\s+0\s+\d+px/i);
    expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    expect(css).toMatch(/animation:\s*none/);
  });
});
