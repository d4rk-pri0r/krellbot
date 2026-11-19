/**
 * Wizard-first cold open → paper path → quiet M24 shell.
 * Density at 1440×900 after the win, with Advanced still reachable.
 */
import { test, expect } from "./journey-harness/journey-harness";
import {
  clickNav,
  walkFirstRunWizardToWin,
} from "../journeys/helpers/journey-steps";

test.use({ wizardColdOpen: "fresh" });

const VIEWPORT = { width: 1440, height: 900 } as const;
const MAX_FIRST_VIEWPORT_BOTTOM_PX = VIEWPORT.height - 8;

test("wizard paper path opens the shell without a second celebrate and keeps Advanced available", async ({
  journey,
}) => {
  const page = journey.page;
  await page.setViewportSize(VIEWPORT);
  await page.goto(journey.workstation.baseURL);
  await walkFirstRunWizardToWin(page);

  await page.getByTestId("first-run-wizard-primary").click();
  await journey.waitForSessionReady(page);

  await expect(page.getByTestId("first-run-wizard")).toHaveCount(0);
  await expect(page.getByTestId("kbot-shell")).toBeVisible();
  await expect(page.getByTestId("app-home")).toBeVisible();
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);
  await expect(page.getByTestId("first-run-coach")).toHaveCount(0);
  await expect(page.getByTestId("activation-checklist")).toHaveCount(0);
  await expect(page.locator("[data-testid='soft-studio-tip']")).toHaveCount(0);
  await expect(page.getByTestId("app-home")).toHaveAttribute(
    "data-home-advanced",
    "1",
  );
  await expect(page.getByTestId("app-home-cta-paper")).toHaveCount(1);
  await expect(page.getByTestId("app-home-path")).toHaveAttribute("data-open", "0");
  await expect(page.getByTestId("app-home-keys-rail-toggle")).toHaveAttribute(
    "aria-expanded",
    "false",
  );

  const hero = await page.getByTestId("app-home-first-viewport").evaluate((el) => {
    const rect = el.getBoundingClientRect();
    return { top: rect.top, bottom: rect.bottom, height: rect.height };
  });
  expect(hero.top, "home hero starts near the top").toBeGreaterThanOrEqual(0);
  expect(
    hero.bottom,
    "post-win home hero stays above the fold",
  ).toBeLessThanOrEqual(MAX_FIRST_VIEWPORT_BOTTOM_PX);
  expect(hero.height, "post-win home hero is a real composition").toBeGreaterThan(
    80,
  );

  await clickNav(page, "Run");
  await expect(page.getByTestId("paper-status-panel")).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByTestId("paper-status-entries")).toContainText(/active/i);
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);
  await expect(page.getByTestId("first-run-coach")).toHaveCount(0);
  await expect(page.getByTestId("activation-checklist")).toHaveCount(0);

  await clickNav(page, "Strategy studio");
  await expect(
    page.getByRole("navigation", { name: "Workstation navigation" }).getByTestId(
      "kbot-nav-more-toggle",
    ),
  ).toHaveAttribute("aria-expanded", "true");

  const flagged = await page.evaluate(() => {
    const html = document.documentElement.outerHTML;
    return {
      beginnerMode: /beginnerMode/.test(html),
      powerMode: /powerMode/.test(html),
    };
  });
  expect(flagged.beginnerMode).toBe(false);
  expect(flagged.powerMode).toBe(false);

  await page.reload();
  await journey.waitForSessionReady(page);
  await expect(page.getByTestId("first-run-wizard")).toHaveCount(0);
  await expect(page.getByTestId("kbot-shell")).toBeVisible();
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);
  await clickNav(page, "Run");
  await expect(page.getByTestId("paper-status-entries")).toContainText(/active/i, {
    timeout: 20_000,
  });
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);
});
