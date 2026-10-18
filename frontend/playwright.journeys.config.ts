/// <reference types="node" />
import { defineConfig } from "@playwright/test";

/**
 * Phase 2 (public) journey Playwright config.
 *
 * One spec file per journey (J1-J7); every scenario owns a fresh
 * workstation, home and Chromium profile. Two workers run isolated
 * spec files concurrently; scenarios within each file stay sequential.
 *
 * The brief sets a 15-minute budget for the whole suite; globalTimeout
 * enforces it. No retries: a retry would mask flakiness the suite is
 * supposed to expose.
 */

export default defineConfig({
  testDir: "journeys",
  // Custom suffix avoids Vitest's existing *.spec.ts collection without
  // changing its configuration or excluding any existing unit/e2e test.
  testMatch: /j[1-7]-.*\.journey\.ts/,
  fullyParallel: false,
  workers: 2,
  retries: 0,
  reporter: [
    ["list"],
    ["html", {open:"never", outputFolder:process.env.KRELLBOT_JOURNEY_HTML_REPORT ?? "playwright-journey-report"}],
    [
      "json",
      {
        outputFile:
          process.env.KRELLBOT_JOURNEY_JSON_REPORT ??
          "test-results/journeys.json",
      },
    ],
  ],
  timeout: 180_000,
  expect: { timeout: 20_000 },
  use: {
    headless: true,
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: "off",
  },
  globalTimeout: 900_000, // 15 min budget for the whole suite
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
});
