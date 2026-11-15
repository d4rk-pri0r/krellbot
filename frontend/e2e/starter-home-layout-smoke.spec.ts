/**
 * Visual regression smoke for Application Home cards and the starter
 * picker at 1440×900 (M7.6 / KRELL-SIGNAL-20261010).
 *
 * jsdom cannot measure layout, so M7.1 pinned the shipped CSS. This
 * Chromium smoke reads real getBoundingClientRect geometry from the
 * production bundle (screenshot-equivalent layout proof; same class as
 * ``alerts-search-touch.spec.ts``) and fails when the pre-fix
 * regressions return:
 *
 *   - home card descriptions squeezed into ~51–77px columns
 *   - starter titles stacked one letter per line
 *   - Use action crushed to ~26px
 *
 * No CSS mocks, no backend mocks: fresh guarded workstation per run.
 */
import { test, expect } from "./journey-harness/journey-harness";
import { clickNav } from "../journeys/helpers/journey-steps";

const VIEWPORT = { width: 1440, height: 900 } as const;

/** Floor above the pre-fix ~51–77px description columns. */
const MIN_HOME_DETAIL_WIDTH_PX = 120;
/** Floor above the pre-fix ~0px / letter-stack starter labels. */
const MIN_STARTER_LABEL_WIDTH_PX = 80;
/** Floor above the pre-fix ~26px Use button. */
const MIN_USE_WIDTH_PX = 40;
const MIN_USE_HEIGHT_PX = 34;

type Box = {
  width: number;
  height: number;
  top: number;
  left: number;
};

type HomeCardGeometry = {
  card: Box;
  detail: Box;
  bodyChildCount: number;
  detailBelowAction: boolean;
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

async function measureHomeCards(
  page: import("@playwright/test").Page,
): Promise<HomeCardGeometry[]> {
  return page.evaluate(() => {
    const cards = Array.from(
      document.querySelectorAll<HTMLElement>('[data-testid^="app-home-card-"]'),
    );
    return cards.map((card) => {
      const detail = card.querySelector<HTMLElement>(".app-home__card-detail");
      const action = card.querySelector<HTMLElement>(".app-home__card-action");
      const body = card.querySelector<HTMLElement>(".app-home__card-body");
      if (!detail || !action || !body) {
        throw new Error("home card missing body/action/detail");
      }
      const cardRect = card.getBoundingClientRect();
      const detailRect = detail.getBoundingClientRect();
      const actionRect = action.getBoundingClientRect();
      return {
        card: {
          width: cardRect.width,
          height: cardRect.height,
          top: cardRect.top,
          left: cardRect.left,
        },
        detail: {
          width: detailRect.width,
          height: detailRect.height,
          top: detailRect.top,
          left: detailRect.left,
        },
        bodyChildCount: body.children.length,
        detailBelowAction: detailRect.top >= actionRect.bottom - 1,
      };
    });
  });
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
        whiteSpace: actionStyle.whiteSpace,
        minHeight: actionStyle.minHeight,
      },
      description: {
        width: descriptionRect.width,
        height: descriptionRect.height,
        top: descriptionRect.top,
        left: descriptionRect.left,
      },
      labelLeftOfAction: labelRect.right <= actionRect.left + 1,
    };
  });
}

test("home cards and starter picker stay readable at 1440×900", async ({
  journey,
}) => {
  const page = journey.page;
  await page.setViewportSize(VIEWPORT);
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await settle(page);

  const home = page.getByTestId("app-home");
  await expect(home).toBeVisible();

  const homeGeometry = await measureHomeCards(page);
  expect(homeGeometry.length).toBeGreaterThanOrEqual(5);
  for (const [index, card] of homeGeometry.entries()) {
    expect(
      card.detail.width,
      `home card[${index}] detail width`,
    ).toBeGreaterThanOrEqual(MIN_HOME_DETAIL_WIDTH_PX);
    expect(
      card.detail.width,
      `home card[${index}] detail uses most of the card track`,
    ).toBeGreaterThan(card.card.width * 0.55);
    expect(card.bodyChildCount).toBeGreaterThanOrEqual(3);
    expect(card.detailBelowAction).toBe(true);
  }

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
