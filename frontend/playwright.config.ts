import { defineConfig } from "@playwright/test";

/**
 * NS20 Playwright config.
 *
 * - Chromium only (matches the Playwright revision cached at
 *   ``~/Library/Caches/ms-playwright``); the brief forbids
 *   ``playwright install``.
 * - One worker, no retries: the suite uses the same workstation port,
 *   so parallelism would race. A retry on a flaky Research trace would
 *   just re-run a 100k-row backtest, which we want to avoid.
 * - ``baseURL`` is filled in by ``global-setup.ts``; the env var is
 *   what the tests actually read.
 * - The 180 s per-test timeout covers the 100k-row backtest + scroll
 *   probe without flaking on slower runners.
 */
export default defineConfig({
  testDir: "e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 180_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.KRELLBOT_E2E_BASE_URL ?? "http://127.0.0.1:1/",
    headless: true,
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: "off",
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
});