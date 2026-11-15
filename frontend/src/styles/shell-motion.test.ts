/**
 * Shell intentional motion — KRELL-SIGNAL-20261010 / M7.5.
 *
 * Pins the three product motions on primary journeys (command palette
 * enter, jobs drawer enter, App Home hero enter), their shared motion
 * tokens, and prefers-reduced-motion disablement.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const stylesDir = dirname(fileURLToPath(import.meta.url));
const shellDir = join(stylesDir, "..", "shell");
const tokens = readFileSync(join(stylesDir, "tokens.css"), "utf8");
const shell = readFileSync(join(stylesDir, "shell.css"), "utf8");
const appHome = readFileSync(join(shellDir, "AppHome.signal.css"), "utf8");
const designSystem = readFileSync(
  join(stylesDir, "..", "..", "..", "docs", "design-system.md"),
  "utf8",
);

describe("Shell intentional motion (M7.5 / KRELL-SIGNAL-20261010)", () => {
  it("keeps motion tokens in tokens.css for shell consumers", () => {
    expect(tokens).toMatch(/--motion-duration-fast\s*:\s*120ms/);
    expect(tokens).toMatch(/--motion-duration-enter\s*:\s*180ms/);
    expect(tokens).toMatch(/--motion-ease-standard\s*:/);
  });

  it("defines palette enter, jobs enter, and shared fade keyframes", () => {
    expect(shell).toMatch(/@keyframes\s+kbot-shell-fade-in/);
    expect(shell).toMatch(/@keyframes\s+kbot-shell-palette-enter/);
    expect(shell).toMatch(/@keyframes\s+kbot-shell-jobs-enter/);
    expect(shell).toMatch(
      /\.kbot-palette\s*\{[^}]*animation:\s*kbot-shell-fade-in\s+var\(--motion-duration-enter\)/s,
    );
    expect(shell).toMatch(
      /\.kbot-palette__box\s*\{[^}]*animation:\s*kbot-shell-palette-enter\s+var\(--motion-duration-enter\)/s,
    );
    expect(shell).toMatch(
      /\.kbot-jobs__scrim\s*\{[^}]*animation:\s*kbot-shell-fade-in\s+var\(--motion-duration-enter\)/s,
    );
    expect(shell).toMatch(
      /\.kbot-jobs__dialog\s*\{[^}]*animation:\s*kbot-shell-jobs-enter\s+var\(--motion-duration-enter\)/s,
    );
  });

  it("defines the App Home hero orientation enter motion", () => {
    expect(appHome).toMatch(/@keyframes\s+kbot-shell-home-enter/);
    expect(appHome).toMatch(
      /\.app-home__hero\s*\{[^}]*animation:\s*kbot-shell-home-enter\s+var\(--motion-duration-enter/s,
    );
  });

  it("disables shell and home motion under prefers-reduced-motion", () => {
    expect(shell).toMatch(
      /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[^}]*animation:\s*none/s,
    );
    expect(appHome).toMatch(
      /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[^}]*\.app-home__hero\s*\{[^}]*animation:\s*none/s,
    );
  });

  it("documents the three motions in the design-system contract", () => {
    expect(designSystem).toMatch(/## Motion/);
    expect(designSystem).toMatch(/Command palette enter/);
    expect(designSystem).toMatch(/Jobs drawer enter/);
    expect(designSystem).toMatch(/Home orientation/);
    expect(designSystem).toMatch(/prefers-reduced-motion/);
  });
});
