/**
 * First-run wizard desktop + mobile geometry, plain-English choose blurbs,
 * blended status visual, post-win running paper handoff on Home, mobile pill
 * & header compactness, and zero console 404s.
 */
import { test, expect } from "./journey-harness/journey-harness";

test.use({ wizardColdOpen: "fresh" });

async function settle(page: import("@playwright/test").Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      }),
  );
}

test("desktop first-run wizard stays roomy, hands off running paper strategy to Home, and logs zero console errors", async ({
  journey,
}) => {
  const page = journey.page;
  const consoleErrors: string[] = [];
  const failed4xx: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      consoleErrors.push(msg.text());
    }
  });
  page.on("response", (res) => {
    if (res.status() >= 400) {
      failed4xx.push(`${res.status()} ${res.url()}`);
    }
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(journey.workstation.baseURL);
  await expect(page.getByTestId("first-run-wizard")).toHaveAttribute(
    "data-wizard-step",
    "welcome",
  );

  await page.getByTestId("first-run-wizard-primary").click();
  await expect(page.getByTestId("first-run-wizard")).toHaveAttribute(
    "data-wizard-step",
    "choose",
  );
  await settle(page);

  await expect(
    page.getByTestId("first-run-wizard-blurb-starter-dual-ma-crossover"),
  ).toBeVisible();
  await expect(
    page.getByTestId("first-run-wizard-blurb-starter-mean-reversion-band"),
  ).toBeVisible();
  await expect(
    page.getByTestId("first-run-wizard-blurb-starter-range-breakout"),
  ).toBeVisible();

  const skipBox = await page
    .getByTestId("first-run-wizard-skip")
    .evaluate((el) => {
      const r = el.getBoundingClientRect();
      return { top: r.top, bottom: r.bottom, height: r.height };
    });
  expect(
    skipBox.bottom,
    "desktop choose Skip setup leaves generous bottom clearance",
  ).toBeLessThanOrEqual(900 - 40);

  await page
    .getByTestId("first-run-wizard-use-starter-dual-ma-crossover")
    .click();
  await expect(page.getByTestId("first-run-wizard")).toHaveAttribute(
    "data-wizard-step",
    "start_paper",
  );
  await page.getByTestId("first-run-wizard-primary").click();

  await expect(page.getByTestId("first-run-wizard")).toHaveAttribute(
    "data-wizard-step",
    "status",
  );
  await expect(page.getByTestId("first-run-wizard-visual")).toHaveAttribute(
    "data-wizard-visual",
    "krell_portrait.png",
  );
  await expect(page.getByTestId("first-run-wizard-sentence")).toHaveText(
    "It’s running on this computer (paper only — not live trading).",
  );
  await page.getByTestId("first-run-wizard-primary").click();

  await expect(page.getByTestId("first-run-wizard")).toHaveAttribute(
    "data-wizard-step",
    "win",
  );
  await page.getByTestId("first-run-wizard-primary").click();
  await journey.waitForSessionReady(page);

  await expect(page.getByTestId("app-home-active-paper")).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByTestId("app-home-active-paper")).toContainText(
    /Running: Dual moving average/i,
  );
  await expect(page.getByTestId("app-home-cta-paper")).toHaveText(
    "Open paper run",
  );

  await page.getByTestId("app-home-cta-paper").click();
  await expect(page.getByTestId("paper-status-entries")).toContainText(
    /active/i,
    { timeout: 15_000 },
  );

  expect(consoleErrors, "no browser console errors").toEqual([]);
  expect(failed4xx, "no HTTP 4xx/5xx responses (including favicon)").toEqual(
    [],
  );
});

test("mobile 390×844 keeps choose Skip setup inside viewport and renders clean Home header and pill", async ({
  journey,
}) => {
  const page = journey.page;
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      consoleErrors.push(msg.text());
    }
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(journey.workstation.baseURL);
  await expect(page.getByTestId("first-run-wizard")).toHaveAttribute(
    "data-wizard-step",
    "welcome",
  );

  await page.getByTestId("first-run-wizard-primary").click();
  await expect(page.getByTestId("first-run-wizard")).toHaveAttribute(
    "data-wizard-step",
    "choose",
  );
  await settle(page);

  const mobileChoose = await page.evaluate(() => {
    const skip = document
      .querySelector<HTMLElement>('[data-testid="first-run-wizard-skip"]')
      ?.getBoundingClientRect();
    return {
      overflowX:
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
      skipBottom: skip?.bottom ?? 9999,
      skipTop: skip?.top ?? -1,
    };
  });
  expect(mobileChoose.overflowX).toBeLessThanOrEqual(1);
  expect(mobileChoose.skipTop).toBeGreaterThanOrEqual(0);
  expect(
    mobileChoose.skipBottom,
    "mobile choose Skip setup stays inside the 844px viewport",
  ).toBeLessThanOrEqual(844 - 16);

  await page
    .getByTestId("first-run-wizard-use-starter-dual-ma-crossover")
    .click();
  await expect(page.getByTestId("first-run-wizard")).toHaveAttribute(
    "data-wizard-step",
    "start_paper",
  );
  await page.getByTestId("first-run-wizard-primary").click();
  await expect(page.getByTestId("first-run-wizard-sentence")).toHaveText(
    "It’s running on this computer (paper only — not live trading).",
  );
  await page.getByTestId("first-run-wizard-primary").click();
  await expect(page.getByTestId("first-run-wizard")).toHaveAttribute(
    "data-wizard-step",
    "win",
  );
  await page.getByTestId("first-run-wizard-primary").click();
  await journey.waitForSessionReady(page);

  await expect(page.getByTestId("app-home-active-paper")).toBeVisible({
    timeout: 15_000,
  });
  await settle(page);

  const mobileShell = await page.evaluate(() => {
    const navRoot = document
      .querySelector<HTMLElement>(".kbot-shell__nav-root")
      ?.getBoundingClientRect();
    const pill = document
      .querySelector<HTMLElement>('[data-testid="app-home-availability"]')
      ?.getBoundingClientRect();
    const activePaper = document
      .querySelector<HTMLElement>('[data-testid="app-home-active-paper"]')
      ?.getBoundingClientRect();
    return {
      overflowX:
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
      navRootHeight: navRoot?.height ?? 9999,
      pillHeight: pill?.height ?? 9999,
      activePaperBottom: activePaper?.bottom ?? 9999,
    };
  });
  expect(mobileShell.overflowX).toBeLessThanOrEqual(1);
  expect(
    mobileShell.navRootHeight,
    "mobile nav root has no 280px flex-basis void",
  ).toBeLessThanOrEqual(160);
  expect(
    mobileShell.pillHeight,
    "mobile availability pill stays compact on one line",
  ).toBeLessThanOrEqual(40);
  expect(
    mobileShell.activePaperBottom,
    "running paper strategy status is visible above the fold on phone",
  ).toBeLessThanOrEqual(844);
  expect(consoleErrors).toEqual([]);
});
