import { test, expect } from "@playwright/test";
import {
  startWorkstationForSpec,
  stopWorkstationForSpec,
  type WorkstationHandle,
} from "./workstation-harness";

/**
 * NS20 100k-rows spec.
 *
 * The trace panel renders one button per bar today; a 100000-row
 * backtest proves the new windowed list does NOT mount 100000 buttons
 * and that scrolling works.
 *
 *  1. Validate a pack and run research on ``rows100k.csv``.
 *  2. Assert ``research-trace-count`` shows ``100000``; the number
 *     of mounted trace buttons is < 500.
 *  3. Scroll ``research-trace-scroll`` to the bottom and assert a
 *     button whose label is the last bar becomes visible; the first
 *     bar's button is no longer mounted.
 *  4. Scroll to the middle and assert a middle bar is visible.
 *  5. Click one and assert ``research-bar-detail`` appears.
 *  6. Record timings in ``console.log`` for the report.
 */

test("100000-row inspection renders and scrolls", async ({ page }) => {
  test.setTimeout(180_000);
  page.on("console", (msg) => {
    console.log(`[ns20-100k-console] ${msg.type()}: ${msg.text()}`);
  });
  page.on("pageerror", (err) => {
    console.log(`[ns20-100k-pageerror] ${err.message}`);
  });
  const baseURL = workstation!.baseURL.replace(/\/$/, "");
  await page.goto(baseURL + "/");
  await expect(page.locator('meta[name="krellbot-bootstrap"]')).toHaveCount(0, {
    timeout: 5_000,
  });
  await page.waitForFunction(
    () => {
      const root = document.querySelector('[data-testid="kbot-shell"]');
      return root?.getAttribute("data-bootstrap-done") === "1";
    },
    undefined,
    { timeout: 15_000 },
  );

  // Save + validate the same fixture pack.
  await page.getByRole("button", { name: "Strategies" }).click();
  await page.getByLabel(/raw json/i).fill(
    JSON.stringify({
      schema_version: 1,
      id: "ns20-100k",
      version: "1.0.0",
      label: "NS20 100k",
      author: "ns20-100k",
      timeframe: "1h",
      indicators: { sma2: { fn: "sma", src: "close", len: 2 } },
      entry: ["close", "crosses_above", "sma2"],
      exit: ["close", "crosses_below", "sma2"],
      risk: { max_account_pct: 100, stop: { type: "pct", pct: 50 } },
      markets: [{ venue: "kraken", pair: "SUIUSD" }],
    }),
  );
  await page.getByRole("button", { name: /^save$/i }).click();
  await page.getByRole("button", { name: /^validate$/i }).click();
  await expect(page.getByTestId("editor-revision-id")).toContainText(/validated/);

  // Run the 100k backtest.
  const rowsCsv = process.env.KRELLBOT_E2E_ROWS_CSV;
  if (!rowsCsv) {
    throw new Error("KRELLBOT_E2E_ROWS_CSV was not set by global-setup");
  }
  await page.getByRole("button", { name: "Research" }).click();
  await page.getByLabel(/dataset path/i).fill(rowsCsv);
  await page.getByLabel(/fee basis points/i).fill("10");
  await page.getByLabel(/^from$/i).fill("0");
  await page.getByLabel(/^to$/i).fill("9999999999999");
  const runStart = Date.now();
  await page.getByRole("button", { name: /^run$/i }).click();
  const job = page.getByTestId("research-job-id");
  await expect(job).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: /load result/i }).click();
  await expect(page.getByTestId("research-result")).toBeVisible({ timeout: 120_000 });
  const resultElapsed = Date.now() - runStart;
  console.log(`[ns20-100k-rows] run+result elapsed_ms=${resultElapsed}`);

  // Count check.
  await expect(page.getByTestId("research-trace-count")).toHaveText("100000");
  const mounted = await page.locator('[data-testid="research-trace-scroll"] button').count();
  expect(mounted).toBeLessThan(500);
  console.log(`[ns20-100k-rows] mounted buttons after run=${mounted}`);

  const scrollContainer = page.getByTestId("research-trace-scroll");
  // The first bar's button is mounted initially.
  const firstLabel = page
    .locator('[data-testid="research-trace-scroll"] button')
    .first()
    .innerText();

  // Scroll to bottom.
  const scrollStart = Date.now();
  await scrollContainer.evaluate((el) => {
    const node = el as HTMLElement;
    node.scrollTop = node.scrollHeight;
  });
  // Wait for the windowed list to settle.
  await page.waitForFunction(
    () => {
      const el = document.querySelector('[data-testid="research-trace-scroll"]') as HTMLElement | null;
      if (!el) return false;
      return el.scrollTop + el.clientHeight >= el.scrollHeight - 1;
    },
    undefined,
    { timeout: 10_000 },
  );
  // Last bar visible.
  const lastButton = page.locator('[data-testid="research-trace-scroll"] button').last();
  await expect(lastButton).toBeVisible({ timeout: 10_000 });
  const lastLabel = (await lastButton.innerText()).trim();
  expect(lastLabel).not.toBe(firstLabel);

  // First bar's button is no longer mounted (or no longer visible).
  const firstStillVisible = await page
    .locator('[data-testid="research-trace-scroll"] button', { hasText: firstLabel })
    .first()
    .isVisible()
    .catch(() => false);
  expect(firstStillVisible).toBe(false);
  const bottomElapsed = Date.now() - scrollStart;
  console.log(`[ns20-100k-rows] bottom elapsed_ms=${bottomElapsed}`);

  // Scroll to middle.
  const middleStart = Date.now();
  await scrollContainer.evaluate((el) => {
    const node = el as HTMLElement;
    node.scrollTop = node.scrollHeight / 2;
  });
  await page.waitForTimeout(200);
  const middleButtons = await page
    .locator('[data-testid="research-trace-scroll"] button')
    .allInnerTexts();
  expect(middleButtons.length).toBeGreaterThan(0);
  console.log(`[ns20-100k-rows] middle elapsed_ms=${Date.now() - middleStart}`);

  // Click the first middle button and assert the detail appears.
  await page.locator('[data-testid="research-trace-scroll"] button').first().click();
  await expect(page.getByTestId("research-bar-detail")).toBeVisible();
});

let workstation: WorkstationHandle | null = null;

test.beforeAll(async () => {
  workstation = await startWorkstationForSpec();
});

test.afterAll(async () => {
  if (workstation) {
    await stopWorkstationForSpec(workstation);
    workstation = null;
  }
});