/**
 * Beginner-default UX guards (M24.7): no dual Beginner/Power shell flags.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SHELL_ROOT = join(__dirname);

describe("beginner-default shell guards", () => {
  it("does not introduce beginnerMode or powerMode in shell sources", () => {
    const files = [
      "AppHome.tsx",
      "WorkstationShell.tsx",
      "Navigation.tsx",
      "CommandPalette.tsx",
    ];
    for (const name of files) {
      const text = readFileSync(join(SHELL_ROOT, name), "utf8");
      expect(text, name).not.toMatch(/beginnerMode|powerMode/);
    }
  });
});
