/**
 * Keys onboarding Signal CSS contract (KRELL-SIGNAL-20261010).
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));

function readStylesheet(): string {
  return readFileSync(join(here, "KeysOnboardingPanel.signal.css"), "utf8");
}

describe("KeysOnboardingPanel Signal CSS", () => {
  it("names the Signal contract and uses sage for the store action", () => {
    const css = readStylesheet();
    expect(css).toMatch(/KRELL-SIGNAL-20261010/);
    expect(css).toMatch(/--sage/);
    expect(css).toMatch(/\.kbot-keys__store/);
    expect(css).toMatch(/outline:\s*2px\s+solid\s+var\(--seafoam/);
  });
});
