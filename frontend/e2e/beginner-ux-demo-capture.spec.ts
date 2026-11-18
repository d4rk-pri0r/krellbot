/**
 * Ship-feel demo screenshots for beginner-default UX (M24 / KRE-194).
 * Writes PNGs to BEGINNER_UX_DEMO_DIR (store media path).
 */
import { test, expect } from "./journey-harness/journey-harness";
import { clickNav } from "../journeys/helpers/journey-steps";
import path from "node:path";
import fs from "node:fs";

const OUT =
  process.env.BEGINNER_UX_DEMO_DIR ||
  "/cursor/stores/bc-71c34276-af8e-4d34-9ec8-b481a6deff3a/media/beginner-ux-demo";

const DESKTOP = { width: 1440, height: 900 } as const;
const MOBILE = { width: 390, height: 844 } as const;

async function settle(page: import("@playwright/test").Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      }),
  );
}

async function shot(
  page: import("@playwright/test").Page,
  name: string,
): Promise<void> {
  fs.mkdirSync(OUT, { recursive: true });
  const file = path.join(OUT, name);
  await page.screenshot({ path: file, fullPage: false });
}

test("capture beginner UX ship-feel demo screenshots", async ({ journey }) => {
  const page = journey.page;
  await page.setViewportSize(DESKTOP);
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await settle(page);

  await expect(page.getByTestId("app-home")).toBeVisible();
  await expect(page.getByTestId("app-home-cta-paper")).toBeVisible();
  await shot(page, "01-home.png");

  await page.getByTestId("app-home-cta-paper").click();
  await settle(page);
  await expect(
    page.locator(".kbot-paper-starter-chooser").first(),
  ).toBeVisible({ timeout: 15_000 });
  await shot(page, "02-chooser.png");

  // Dismiss chooser if possible, then open Run.
  const dismiss = page.locator(".kbot-paper-starter-chooser__dismiss");
  if (await dismiss.isVisible().catch(() => false)) {
    await dismiss.click();
    await settle(page);
  }

  await clickNav(page, "Run");
  await settle(page);
  await shot(page, "03-run.png");

  await clickNav(page, "Workspace");
  await settle(page);
  const more = page.getByRole("button", { name: /^More$/i });
  await more.click();
  await settle(page);
  await expect(page.getByRole("button", { name: /Studio/i })).toBeVisible();
  await shot(page, "04-more.png");

  // Settings & trust Advanced cluster.
  const settings = page.getByTestId("app-home-settings-trust");
  await expect(settings).toBeVisible();
  await settings.getByRole("button", { name: /Settings & trust/i }).click();
  await settle(page);
  await shot(page, "05-settings-trust.png");

  // ⌘K palette — Start free paper strategy first.
  await page.keyboard.press("Meta+k");
  await settle(page);
  await expect(page.getByTestId("command-palette")).toBeVisible();
  await expect(
    page.getByTestId("command-palette-action-start-free-paper-strategy"),
  ).toBeVisible();
  await shot(page, "06-palette.png");
  await page.keyboard.press("Escape");
  await settle(page);

  // Mobile More targets.
  await page.setViewportSize(MOBILE);
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await settle(page);
  await page.getByRole("button", { name: /^More$/i }).click();
  await settle(page);
  await shot(page, "07-mobile-more.png");
});
