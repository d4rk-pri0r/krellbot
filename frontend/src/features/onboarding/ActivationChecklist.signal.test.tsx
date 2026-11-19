import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "ActivationChecklist.signal.css"), "utf8");

describe("ActivationChecklist Signal CSS contract", () => {
  it("names Signal tokens and disables check motion under prefers-reduced-motion", () => {
    expect(css).toMatch(/KRELL-SIGNAL-20261010/);
    expect(css).toMatch(/--seafoam|--focus-ring/);
    expect(css).toMatch(/--muted|--text|--line/);
    expect(css).toMatch(/kbot-activation-checklist/);
    expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    expect(css).toMatch(/animation:\s*none/);
  });
});
