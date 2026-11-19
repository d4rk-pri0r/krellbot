/**
 * Arrow setup tour after the intro wizard (KRELL-SIGNAL-20261010).
 *
 * Desktop 1440×900 and phone 390×844: the callout stays inside the
 * viewport, points at the real keys and paper controls, and does not
 * block the cockpit. Completion survives reload. Skip and replay work.
 * Set SETUP_TOUR_DEMO_DIR to also write step screenshots.
 */
import fs from "node:fs";
import path from "node:path";
import { test, expect, type Page } from "./journey-harness/journey-harness";
import { walkFirstRunWizardToWin } from "../journeys/helpers/journey-steps";

test.use({ wizardColdOpen: "fresh" });

const DESKTOP = { width: 1440, height: 900 } as const;
const MOBILE = { width: 390, height: 844 } as const;
const DEMO = process.env.SETUP_TOUR_DEMO_DIR?.trim() || "";

async function settle(page: Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      }),
  );
}

async function shot(page: Page, name: string): Promise<void> {
  if (!DEMO) {
    return;
  }
  fs.mkdirSync(DEMO, { recursive: true });
  await settle(page);
  await page.screenshot({
    path: path.join(DEMO, name),
    fullPage: false,
  });
}

async function expectCalloutInside(
  page: Page,
  viewport: { width: number; height: number },
): Promise<void> {
  await expect(page.getByTestId("workspace-setup-tour")).toHaveAttribute(
    "data-anchored",
    "1",
    { timeout: 15_000 },
  );
  await expect
    .poll(async () => {
      const card = await page.getByTestId("workspace-setup-tour-card").boundingBox();
      const arrow = await page.getByTestId("workspace-setup-tour-arrow").evaluate((el) => {
        const line = el.querySelector("line");
        if (!line) {
          return null;
        }
        return {
          x1: Number(line.getAttribute("x1")),
          y1: Number(line.getAttribute("y1")),
          x2: Number(line.getAttribute("x2")),
          y2: Number(line.getAttribute("y2")),
        };
      });
      if (!card || !arrow) {
        return false;
      }
      const cardInside =
        card.x >= -1 &&
        card.y >= -1 &&
        card.x + card.width <= viewport.width + 1 &&
        card.y + card.height <= viewport.height + 1;
      const arrowInside =
        [arrow.x1, arrow.x2].every(
          (value) => value >= -1 && value <= viewport.width + 1,
        ) &&
        [arrow.y1, arrow.y2].every(
          (value) => value >= -1 && value <= viewport.height + 1,
        );
      return cardInside && arrowInside;
    })
    .toBe(true);
}

async function expectPointerPassThrough(page: Page): Promise<void> {
  const pointers = await page.evaluate(() => {
    const root = document.querySelector<HTMLElement>(".kbot-setup-tour");
    const card = document.querySelector<HTMLElement>(".kbot-setup-tour__card");
    const spot = document.querySelector<HTMLElement>(".kbot-setup-tour__spotlight");
    return {
      root: root ? getComputedStyle(root).pointerEvents : "",
      card: card ? getComputedStyle(card).pointerEvents : "",
      spot: spot ? getComputedStyle(spot).pointerEvents : "",
    };
  });
  expect(pointers.root).toBe("none");
  expect(pointers.card).toBe("auto");
  expect(pointers.spot).toBe("none");
}

async function openShellFromWizard(page: Page): Promise<void> {
  await walkFirstRunWizardToWin(page);
  await expect(page.getByTestId("workspace-setup-tour")).toHaveCount(0);
  await page.getByTestId("first-run-wizard-primary").click();
  await expect(page.getByTestId("first-run-wizard")).toHaveCount(0);
  await expect(page.getByTestId("kbot-shell")).toBeVisible();
  await expect(page.getByTestId("workspace-setup-tour")).toBeVisible();
  await expect(page.getByTestId("workspace-setup-tour")).toHaveAttribute(
    "data-setup-step",
    "workspace",
  );
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);
  await expect(page.getByTestId("app-home-active-paper")).toBeVisible({
    timeout: 15_000,
  });
}

async function walkArmedTour(
  page: Page,
  viewport: { width: number; height: number },
  prefix: string,
): Promise<void> {
  await expectPointerPassThrough(page);
  await page.getByTestId("app-home-cta-paper").click({ trial: true });
  await page
    .getByRole("navigation", { name: "Workstation navigation" })
    .getByRole("button", { name: "Run", exact: true })
    .click({ trial: true });
  await expectCalloutInside(page, viewport);
  await shot(page, `${prefix}-step-1-workspace.png`);

  await page.getByTestId("workspace-setup-tour-next").click();
  await expect(page.getByTestId("workspace-setup-tour")).toHaveAttribute(
    "data-setup-step",
    "keys",
  );
  await expect(page.getByTestId("app-home-keys-rail")).toHaveAttribute(
    "data-open",
    "1",
  );
  await expect(page.getByTestId("keys-onboarding-kraken")).toBeVisible();
  await expect
    .poll(async () => page.getByTestId("workspace-setup-tour").getAttribute("data-anchor"))
    .toMatch(/keys-/);
  await expectCalloutInside(page, viewport);
  await shot(page, `${prefix}-step-2-keys.png`);

  await page.getByTestId("workspace-setup-tour-next").click();
  await expect(page.getByTestId("workspace-setup-tour")).toHaveAttribute(
    "data-setup-step",
    "strategy",
  );
  await expect(page.getByTestId("app-home")).toBeVisible();
  await expectCalloutInside(page, viewport);
  await shot(page, `${prefix}-step-3-strategy.png`);

  await page.getByTestId("workspace-setup-tour-next").click();
  await expect(page.getByTestId("workspace-setup-tour")).toHaveAttribute(
    "data-setup-step",
    "run",
  );
  await expect(page.getByTestId("paper-status-entries")).toContainText(/active/i, {
    timeout: 20_000,
  });
  await expect(page.getByTestId("workspace-setup-tour-next")).toHaveText("Done");
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);
  await expectCalloutInside(page, viewport);
  await shot(page, `${prefix}-step-4-run.png`);

  await page.getByTestId("workspace-setup-tour-next").click();
  await expect(page.getByTestId("workspace-setup-tour")).toHaveCount(0);
}

test("desktop wizard handoff walks every arrow step, then completion survives reload and replay can be skipped", async ({
  journey,
}) => {
  const page = journey.page;
  await page.setViewportSize(DESKTOP);
  await page.goto(journey.workstation.baseURL);
  await openShellFromWizard(page);
  await walkArmedTour(page, DESKTOP, "desktop");

  await page.reload();
  await journey.waitForSessionReady(page);
  await expect(page.getByTestId("first-run-wizard")).toHaveCount(0);
  await expect(page.getByTestId("workspace-setup-tour")).toHaveCount(0);
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);
  await page
    .getByRole("navigation", { name: "Workstation navigation" })
    .getByRole("button", { name: "Workspace", exact: true })
    .click();
  await expect(page.getByTestId("workspace-setup-tour-replay")).toBeVisible();
  await page.getByTestId("workspace-setup-tour-replay").click();
  await expect(page.getByTestId("workspace-setup-tour")).toHaveAttribute(
    "data-setup-step",
    "workspace",
  );
  await shot(page, "desktop-replay.png");
  await page.getByTestId("workspace-setup-tour-skip").click();
  await expect(page.getByTestId("workspace-setup-tour")).toHaveCount(0);
  await page.reload();
  await journey.waitForSessionReady(page);
  await expect(page.getByTestId("workspace-setup-tour")).toHaveCount(0);
});

test("mobile wizard handoff keeps every arrow step inside 390×844", async ({
  journey,
}) => {
  const page = journey.page;
  await page.setViewportSize(MOBILE);
  await page.goto(journey.workstation.baseURL);
  await openShellFromWizard(page);
  await walkArmedTour(page, MOBILE, "mobile");

  await page.reload();
  await journey.waitForSessionReady(page);
  await expect(page.getByTestId("workspace-setup-tour")).toHaveCount(0);
  await page
    .getByRole("navigation", { name: "Workstation navigation" })
    .getByRole("button", { name: "Workspace", exact: true })
    .click();
  await expect(page.getByTestId("workspace-setup-tour-replay")).toBeVisible();
});

test("skipping the wizard still opens the tour and one click starts a paper simulation", async ({
  journey,
}) => {
  const page = journey.page;
  await page.setViewportSize(DESKTOP);
  await page.goto(journey.workstation.baseURL);
  await expect(page.getByTestId("workspace-setup-tour")).toHaveCount(0);
  await journey.waitForSessionReady(page);
  await expect(page.getByTestId("first-run-wizard")).toHaveCount(0);
  await expect(page.getByTestId("workspace-setup-tour")).toBeVisible();
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);
  await expectPointerPassThrough(page);

  await page.getByTestId("workspace-setup-tour-next").click();
  await expect(page.getByTestId("keys-onboarding-kraken")).toBeVisible();
  await page.getByTestId("workspace-setup-tour-next").click();
  await expect(page.getByTestId("workspace-setup-tour")).toHaveAttribute(
    "data-setup-step",
    "strategy",
  );
  await expect(page.getByTestId("paper-arm-form")).toBeVisible({ timeout: 15_000 });
  await page.getByTestId("workspace-setup-tour-next").click();
  await expect(page.getByTestId("workspace-setup-tour")).toHaveAttribute(
    "data-setup-step",
    "run",
  );
  await expect(page.getByTestId("workspace-setup-tour-next")).toHaveText(
    "Start paper run",
  );
  await expect(page.getByTestId("workspace-setup-tour")).toHaveAttribute(
    "data-anchor",
    /paper-arm|paper-status-empty/,
    { timeout: 15_000 },
  );
  await expect(page.getByTestId("workspace-setup-tour")).toHaveAttribute(
    "data-anchored",
    "1",
  );
  await shot(page, "desktop-step-4-launch.png");
  await page.getByTestId("workspace-setup-tour-next").click();
  await expect(page.getByTestId("paper-status-entries")).toContainText(/active/i, {
    timeout: 20_000,
  });
  await expect(page.getByTestId("workspace-setup-tour-error")).toHaveCount(0);
  await expect(page.getByTestId("workspace-setup-tour-next")).toHaveText("Done", {
    timeout: 15_000,
  });
  await shot(page, "desktop-step-4-launched.png");
});
