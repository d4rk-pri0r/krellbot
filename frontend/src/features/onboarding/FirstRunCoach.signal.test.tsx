import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "FirstRunCoach.signal.css"), "utf8");

describe("FirstRunCoach Signal CSS contract", () => {
  it("names Signal tokens and disables motion under prefers-reduced-motion", () => {
    expect(css).toMatch(/KRELL-SIGNAL-20261010/);
    expect(css).toMatch(/--sage|--action-primary-bg/);
    expect(css).toMatch(/--seafoam|--focus-ring/);
    expect(css).toMatch(/kbot-first-run-coach__spotlight/);
    expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    expect(css).toMatch(/animation:\s*none/);
  });
});
