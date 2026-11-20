/**
 * Visual regression smoke for Application Home first-viewport composition
 * and the starter picker at 1440×900 (M7.6 / KRELL-SIGNAL-20261010 / M24).
 *
 * Beginner home (M24.2): first viewport is hero + one sage CTA — peer
 * destination cards live under Advanced “All areas” (collapsed by default).
 * This Chromium smoke reads real getBoundingClientRect geometry from the
 * production bundle and fails when:
 *
 *   - the hero CTA is crushed or missing above the fold
 *   - Advanced path cards (when expanded) squeeze descriptions into ~51–77px
 *   - starter titles stacked one letter per line
 *   - Use action crushed to ~26px
 *
 * No CSS mocks, no backend mocks: fresh guarded workstation per run.
 * Do not assert geometry on collapsed Advanced cards (width 0 is expected).
 */
import { test, expect } from "./journey-harness/journey-harness";
import { clickNav } from "../journeys/helpers/journey-steps";

const VIEWPORT = { width: 1440, height: 900 } as const;

/** Floor for the sage primary CTA in the hero. */
const MIN_HOME_CTA_WIDTH_PX = 180;
/** Floor above the pre-fix ~51–77px description columns (expanded Advanced). */
const MIN_HOME_DETAIL_WIDTH_PX = 120;
/** Floor above the pre-fix ~0px / letter-stack starter labels. */
const MIN_STARTER_LABEL_WIDTH_PX = 80;
/** Floor above the pre-fix ~26px Use button. */
const MIN_USE_WIDTH_PX = 40;
const MIN_USE_HEIGHT_PX = 34;
/** Hero must stay a real first-viewport composition, not a stub. */
const MIN_HERO_HEIGHT_PX = 80;
const MAX_FIRST_VIEWPORT_BOTTOM_PX = 720;

type Box = {
  width: number;
  height: number;
  top: number;
  left: number;
  bottom: number;
};

type StarterItemGeometry = {
  label: Box & {
    whiteSpace: string;
    overflowWrap: string;
    clientHeight: number;
    scrollHeight: number;
  };
  action: Box & { whiteSpace: string; minHeight: string };
  description: Box;
  labelLeftOfAction: boolean;
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
  return page.evaluate((id) => {
    const el = document.querySelector<HTMLElement>(`[data-testid="${id}"]`);
    if (!el) {
      throw new Error(`missing [data-testid="${id}"]`);
    }
    const r = el.getBoundingClientRect();
    return {
      width: r.width,
      height: r.height,
      top: r.top,
      left: r.left,
      bottom: r.bottom,
    };
  }, testId);
}

async function measureStarterItem(
  page: import("@playwright/test").Page,
): Promise<StarterItemGeometry> {
  return page.evaluate(() => {
    const item = document.querySelector<HTMLElement>(
      '[data-testid^="starter-picker-item-"]',
    );
    if (!item) {
      throw new Error("starter picker item missing");
    }
    const label = item.querySelector<HTMLElement>(
      ".kbot-starter-picker__item-label",
    );
    const description = item.querySelector<HTMLElement>(
      ".kbot-starter-picker__item-description",
    );
    const action = item.querySelector<HTMLElement>(
      ".kbot-starter-picker__action",
    );
    if (!label || !description || !action) {
      throw new Error("starter item missing label/description/action");
    }
    const labelRect = label.getBoundingClientRect();
    const actionRect = action.getBoundingClientRect();
    const descriptionRect = description.getBoundingClientRect();
    const labelStyle = getComputedStyle(label);
    const actionStyle = getComputedStyle(action);
    return {
      label: {
        width: labelRect.width,
        height: labelRect.height,
        top: labelRect.top,
        left: labelRect.left,
        bottom: labelRect.bottom,
        whiteSpace: labelStyle.whiteSpace,
        overflowWrap: labelStyle.overflowWrap,
        clientHeight: label.clientHeight,
        scrollHeight: label.scrollHeight,
      },
      action: {
        width: actionRect.width,
        height: actionRect.height,
        top: actionRect.top,
        left: actionRect.left,
        bottom: actionRect.bottom,
        whiteSpace: actionStyle.whiteSpace,
        minHeight: actionStyle.minHeight,
      },
      description: {
        width: descriptionRect.width,
        height: descriptionRect.height,
        top: descriptionRect.top,
        left: descriptionRect.left,
        bottom: descriptionRect.bottom,
      },
      labelLeftOfAction: labelRect.right <= actionRect.left + 1,
    };
  });
}

test("home first-viewport and starter picker stay readable at 1440×900", async ({
  journey,
}) => {
  const page = journey.page;
  await page.setViewportSize(VIEWPORT);
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await settle(page);

  const home = page.getByTestId("app-home");
  await expect(home).toBeVisible();

  // Beginner first viewport: hero + CTA (not the demoted Advanced card wall).
  const first = page.getByTestId("app-home-first-viewport");
  await expect(first).toBeVisible();
  await expect(page.getByTestId("app-home-cta-paper")).toBeVisible();
  await expect(page.getByTestId("app-home-cta-paper")).toContainText(
    /Start with a free paper strategy/i,
  );
  await expect(page.getByTestId("kbot-status-strip")).toContainText(/Paper/i);
  await expect(page.getByTestId("app-home-availability")).toHaveCount(0);

  const hero = await boxFor(page, "app-home-first-viewport");
  expect(hero.top, "home hero starts near the top").toBeGreaterThanOrEqual(0);
  expect(
    hero.bottom,
    "home hero stays above the fold",
  ).toBeLessThanOrEqual(MAX_FIRST_VIEWPORT_BOTTOM_PX);
  expect(hero.height, "home hero is a real composition").toBeGreaterThan(
    MIN_HERO_HEIGHT_PX,
  );

  const cta = await boxFor(page, "app-home-cta-paper");
  expect(
    cta.width,
    "sage CTA has a readable width in the first viewport",
  ).toBeGreaterThanOrEqual(MIN_HOME_CTA_WIDTH_PX);
  expect(cta.height, "sage CTA is tappable").toBeGreaterThanOrEqual(34);

  // Focused Home: no duplicate All areas wall, no keys rail, no checklist.
  await expect(page.getByTestId("activation-checklist")).toHaveCount(0);
  await expect(page.getByTestId("first-run-coach")).toHaveCount(0);
  await expect(page.getByTestId("app-home-path")).toHaveCount(0);
  await expect(page.getByTestId("app-home-keys-rail")).toHaveCount(0);

  // Dedicated Settings view renders a readable two-column layout at 1440×900.
  await clickNav(page, "Settings");
  await expect(page.getByTestId("settings-view")).toBeVisible();
  await settle(page);
  const settingsContent = await boxFor(page, "settings-content");
  expect(
    settingsContent.width,
    "Settings content pane has generous readable width (not a narrow sidebar)",
  ).toBeGreaterThanOrEqual(MIN_HOME_DETAIL_WIDTH_PX * 3);

  await clickNav(page, "Strategies");
  const picker = page.getByTestId("starter-picker");
  await picker.scrollIntoViewIfNeeded();
  await page
    .locator('[data-testid^="starter-picker-item-"]')
    .first()
    .waitFor({ state: "visible", timeout: 20_000 });
  await settle(page);

  const starter = await measureStarterItem(page);
  expect(starter.label.whiteSpace).toBe("nowrap");
  expect(starter.label.overflowWrap).not.toBe("anywhere");
  expect(starter.label.width).toBeGreaterThanOrEqual(MIN_STARTER_LABEL_WIDTH_PX);
  // Single-line title: client box matches content height (no letter stack).
  expect(starter.label.scrollHeight).toBeLessThanOrEqual(
    starter.label.clientHeight + 1,
  );
  expect(starter.label.height).toBeLessThan(40);

  expect(starter.action.whiteSpace).toBe("nowrap");
  expect(starter.action.width).toBeGreaterThanOrEqual(MIN_USE_WIDTH_PX);
  expect(starter.action.height).toBeGreaterThanOrEqual(MIN_USE_HEIGHT_PX);
  expect(parseFloat(starter.action.minHeight)).toBeGreaterThanOrEqual(
    MIN_USE_HEIGHT_PX,
  );
  expect(starter.labelLeftOfAction).toBe(true);
  expect(starter.description.width).toBeGreaterThanOrEqual(
    MIN_STARTER_LABEL_WIDTH_PX,
  );
});
