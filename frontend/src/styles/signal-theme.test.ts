/**
 * Signal theme contract — KRELL-SIGNAL-20261010.
 *
 * Pins the approved named palette in tokens.css, the local font
 * declarations, and the semantic meaning of the legacy aliases:
 * --warn must stay a caution tone (never a success color), because its
 * consumers render caution/error meaning.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const stylesDir = dirname(fileURLToPath(import.meta.url));
const tokens = readFileSync(join(stylesDir, "tokens.css"), "utf8");
const shell = readFileSync(join(stylesDir, "shell.css"), "utf8");
const fonts = readFileSync(join(stylesDir, "fonts.css"), "utf8");

const APPROVED: ReadonlyArray<[string, string]> = [
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

describe("Signal tokens (KRELL-SIGNAL-20261010)", () => {
  it("declares the nine approved named palette tokens", () => {
    for (const [name, value] of APPROVED) {
      expect(tokens).toMatch(
        new RegExp(`${name}\\s*:\\s*${value.replace("#", "#?")}\\s*;`, "i"),
      );
    }
  });

  it("retires the legacy neon-lime/cyan literals", () => {
    for (const legacy of ["#07090d", "#5ce1ff", "#c6ff3d"]) {
      expect(tokens.toLowerCase()).not.toContain(legacy);
      expect(shell.toLowerCase()).not.toContain(legacy);
    }
  });

  it("keeps legacy aliases but maps --warn to a caution tone, not success", () => {
    // Aliases still exist for existing consumers.
    expect(tokens).toMatch(/--canvas\s*:\s*var\(--navy\)/);
    expect(tokens).toMatch(/--signal\s*:\s*var\(--seafoam\)/);
    expect(tokens).toMatch(/--ink\s*:\s*var\(--text\)/);
    // --warn means caution: it must not resolve to sage/success.
    expect(tokens).toMatch(/--warn\s*:\s*var\(--caution-text\)/);
    expect(tokens).not.toMatch(/--warn\s*:\s*var\(--sage\)/);
    expect(tokens).not.toMatch(/--warn\s*:\s*var\(--seafoam\)/);
  });

  it("bundles Manrope + IBM Plex Mono locally with no remote source", () => {
    expect(fonts).toMatch(/font-family:\s*"Manrope"/);
    expect(fonts).toMatch(/font-family:\s*"IBM Plex Mono"/);
    expect(fonts).not.toMatch(/https?:\/\//);
    expect(fonts).toMatch(/\.\.\/assets\/fonts\//);
  });

  it("styles the shell with the UI font, not a monospace wall", () => {
    expect(shell).toMatch(/font-family:\s*var\(--font-ui\)/);
    // Monospace is allowed only through the token, for technical labels.
    expect(shell).toMatch(/var\(--font-mono\)/);
    expect(shell).not.toMatch(/font-family:\s*ui-monospace/);
  });
});
