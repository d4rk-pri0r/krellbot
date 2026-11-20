/**
 * First-viewport density visual smoke at 1440×900 (M18.6 / KRE-140 /
 * docs/ui-density.md / KRELL-SIGNAL-20261010).
 *
 * Extends the M7.6 Chromium geometry pattern (screenshot-equivalent
 * getBoundingClientRect proof). Pins Workspace home + Workstation
 * compositions above the fold and fails when tall empty scrolls or
 * collapsed Advanced regressions return.
 *
 * No CSS mocks, no backend mocks: fresh guarded workstation per run.
 */
import { test, expect } from "./journey-harness/journey-harness";
import { clickNav } from "../journeys/helpers/journey-steps";

const VIEWPORT = { width: 1440, height: 900 } as const;

/** Hero / operator summary must finish inside the content viewport. */
const MAX_FIRST_VIEWPORT_BOTTOM_PX = VIEWPORT.height - 8;
/** Compact path / destination strip starts above the fold. */
const MAX_PATH_TOP_PX = VIEWPORT.height - 120;

type Box = {
  top: number;
  bottom: number;
  height: number;
  width: number;
};

async function settle(page: import("@playwright/test").Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      }),
  );
}

async function boxFor(
  page: import("@playwright/test").Page,
  testId: string,
): Promise<Box> {
  const locator = page.getByTestId(testId);
  await expect(locator).toBeVisible();
  const handle = await locator.elementHandle();
  if (!handle) {
    throw new Error(`missing element ${testId}`);
  }
  return handle.evaluate((el) => {
    const rect = el.getBoundingClientRect();
    return {
      top: rect.top,
      bottom: rect.bottom,
      height: rect.height,
      width: rect.width,
    };
  });
}

test("home and workstation first-viewports stay dense at 1440×900", async ({
  journey,
}) => {
  const page = journey.page;
  await page.setViewportSize(VIEWPORT);
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await settle(page);

  const home = page.getByTestId("app-home");
  await expect(home).toBeVisible();

  const first = page.getByTestId("app-home-first-viewport");
  await expect(first).toBeVisible();
  await expect(page.getByTestId("app-home-cta-paper")).toBeVisible();
  await expect(page.getByTestId("app-home-availability")).toContainText(
    /Local preview/i,
  );
  await expect(page.getByTestId("app-home-availability")).toContainText(
    /Live trading unavailable/i,
  );

  const hero = await boxFor(page, "app-home-first-viewport");
  expect(hero.top, "home hero starts near the top").toBeGreaterThanOrEqual(0);
  expect(
    hero.bottom,
    "home hero stays above the fold (no tall empty scroll)",
  ).toBeLessThanOrEqual(MAX_FIRST_VIEWPORT_BOTTOM_PX);
  expect(hero.height, "home hero is a real composition, not a stub").toBeGreaterThan(
    80,
  );

  // Focused Home hero: one sage CTA; no duplicate destination wall or home keys rail.
  await expect(page.getByTestId("app-home-cta-paper")).toContainText(
    /Start with a free paper strategy/i,
  );
  expect(
    await page.getByTestId("app-home-cta-paper").count(),
    "exactly one primary paper CTA",
  ).toBe(1);
  await expect(page.getByTestId("app-home-cta-packs")).toBeVisible();
  await expect(page.getByTestId("first-run-coach")).toHaveCount(0);
  await expect(page.getByTestId("activation-checklist")).toHaveCount(0);
  await expect(page.getByTestId("app-home-works")).toHaveCount(0);
  await expect(page.getByTestId("app-home-path")).toHaveCount(0);
  await expect(page.getByTestId("app-home-keys-rail")).toHaveCount(0);

  // Document should not be padded with sparse empty viewport below the hero.
  const homeScroll = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    clientHeight: document.documentElement.clientHeight,
  }));
  expect(
    homeScroll.scrollHeight,
    "fresh home must not invent a multi-viewport empty scroll",
  ).toBeLessThan(VIEWPORT.height * 2);

  // Dedicated Settings view hosts Exchange keys in a clean spacious layout.
  await clickNav(page, "Settings");
  await expect(page.getByTestId("settings-view")).toBeVisible();
  await expect(page.getByTestId("settings-section-keys")).toBeVisible();
  const keysBox = await boxFor(page, "settings-section-keys");
  expect(
    keysBox.top,
    "Settings Exchange keys begins above the fold",
  ).toBeLessThanOrEqual(MAX_PATH_TOP_PX);

  await clickNav(page, "Run");
  await expect(page.getByTestId("paper-status-panel")).toBeVisible({
    timeout: 20_000,
  });
  await settle(page);

  const workstationFirst = page.getByTestId("paper-workstation-first-viewport");
  await expect(workstationFirst).toBeVisible();
  await expect(page.getByTestId("paper-status-next-action")).toBeVisible();
  await expect(page.getByTestId("paper-status-empty")).toBeVisible();
  // M25.6: first-session empty is a single arm prompt; chart is Advanced.
  await expect(page.getByTestId("paper-first-session-arm")).toBeVisible();
  await expect(page.getByTestId("paper-status-empty")).toContainText(
    /Start a paper run with the strategy you picked/i,
  );
  await expect(page.getByTestId("paper-status-next-action")).toContainText(
    /start your paper run/i,
  );
  await expect(page.getByTestId("paper-first-session-chart-disclosure")).toHaveAttribute(
    "data-open",
    "0",
  );
  await expect(
    page.getByTestId("paper-first-session-chart-disclosure-toggle"),
  ).toHaveAttribute("aria-expanded", "false");
  // Fresh install: no fabricated chart series.
  await expect(page.getByTestId("paper-pnl-chart-svg")).toHaveCount(0);
  await expect(page.getByTestId("paper-pnl-position-chart")).toHaveCount(0);

  // Density contract pins next action + arm prompt above the fold.
  const nextAction = await boxFor(page, "paper-status-next-action");
  const armPrompt = await boxFor(page, "paper-first-session-arm");
  expect(
    nextAction.bottom,
    "next action stays above the fold",
  ).toBeLessThanOrEqual(MAX_FIRST_VIEWPORT_BOTTOM_PX);
  expect(
    armPrompt.top,
    "first-session arm prompt begins in the first viewport",
  ).toBeLessThanOrEqual(MAX_FIRST_VIEWPORT_BOTTOM_PX);
  // Expand Advanced chart only to prove honesty copy still exists (demoted).
  await page.getByTestId("paper-first-session-chart-disclosure-toggle").click();
  await expect(page.getByTestId("paper-chart-honest-empty")).toBeVisible();
  await expect(page.getByTestId("paper-chart-honest-empty")).toContainText(
    /No journal series yet/i,
  );

  const portfolioToggle = page.getByTestId("paper-portfolio-disclosure-toggle");
  await expect(portfolioToggle).toBeVisible();
  await expect(portfolioToggle).toHaveAttribute("aria-expanded", "false");

  const armedToggle = page.getByTestId("paper-armed-records-disclosure-toggle");
  await expect(armedToggle).toBeVisible();
  await expect(armedToggle).toHaveAttribute("aria-expanded", "false");

  const rehearsalToggle = page.getByTestId("paper-rehearsal-disclosure-toggle");
  await expect(rehearsalToggle).toBeVisible();
  await expect(rehearsalToggle).toHaveAttribute("aria-expanded", "false");

  // Power destinations remain reachable via More (no beginnerMode flag).
  await clickNav(page, "Strategy studio");
  await settle(page);
  await expect(
    page.getByRole("navigation", { name: "Workstation navigation" }).getByTestId(
      "kbot-nav-more-toggle",
    ),
  ).toHaveAttribute("aria-expanded", "true");
});

test("no beginnerMode or powerMode flags in the shipped shell", async ({
  journey,
}) => {
  const page = journey.page;
  await page.setViewportSize(VIEWPORT);
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  const flagged = await page.evaluate(() => {
    const html = document.documentElement.outerHTML;
    return {
      beginnerMode: /beginnerMode/.test(html),
      powerMode: /powerMode/.test(html),
    };
  });
  expect(flagged.beginnerMode).toBe(false);
  expect(flagged.powerMode).toBe(false);
});
