/**
 * M25.9 first-run activation demo capture (KRELL-SIGNAL-20261010).
 *
 * Opt-in only: set FIRST_RUN_ACTIVATION_DEMO_DIR to a writable path
 * (Project store media/first-run-activation-demo). Skipped in CI.
 */
import { test, expect } from "./journey-harness/journey-harness";
import { clickNav } from "../journeys/helpers/journey-steps";
import path from "node:path";
import fs from "node:fs";

const OUT = process.env.FIRST_RUN_ACTIVATION_DEMO_DIR?.trim() || "";
const RECORD = process.env.FIRST_RUN_ACTIVATION_DEMO_RECORD === "1";

const DESKTOP = { width: 1440, height: 900 } as const;
const MOBILE = { width: 390, height: 844 } as const;

async function settle(page: import("@playwright/test").Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      }),
  );
  await page.waitForTimeout(280);
}

async function shot(
  page: import("@playwright/test").Page,
  name: string,
): Promise<void> {
  fs.mkdirSync(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, name), fullPage: false });
}

test.use(
  RECORD && OUT
    ? {
        video: {
          mode: "on",
          size: DESKTOP,
        },
      }
    : {},
);

test("capture first-run activation walkthrough demo frames", async ({
  journey,
}, testInfo) => {
  test.skip(
    true,
    "hotspot coach walkthrough retired (M26.6); full-screen wizard demo is M26.8",
  );
  test.skip(
    !OUT,
    "set FIRST_RUN_ACTIVATION_DEMO_DIR to capture activation demos",
  );
  const page = journey.page;
  await page.setViewportSize(DESKTOP);
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await settle(page);

  // 1. Coach welcome on Workspace (one job: start the guide).
  await expect(page.getByTestId("first-run-coach")).toBeVisible();
  await expect(page.getByTestId("first-run-coach")).toHaveAttribute(
    "data-coach-step",
    "welcome",
  );
  await expect(page.getByTestId("app-home-cta-paper")).toBeVisible();
  await shot(page, "01-coach-welcome.png");

  // 2. After Start — spotlight on choose_starter CTA.
  await page.getByTestId("first-run-coach-primary").click();
  await settle(page);
  await expect(page.getByTestId("first-run-coach")).toHaveAttribute(
    "data-coach-step",
    "choose_starter",
  );
  await expect(page.getByTestId("first-run-coach-spotlight")).toBeVisible();
  await shot(page, "02-coach-cta-spotlight.png");

  // 3. Chooser — three clean consumer cards.
  await page.getByTestId("first-run-coach-primary").click();
  await settle(page);
  await expect(page.getByTestId("paper-starter-chooser")).toBeVisible({
    timeout: 15_000,
  });
  await expect(
    page.getByRole("button", { name: /Use Dual moving average/i }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Use Mean reversion/i }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Use Range breakout/i }),
  ).toBeVisible();
  await shot(page, "03-chooser-cards.png");

  // 4. Use a starter → Run arm prompt (pre-arm first session).
  await page.getByRole("button", { name: /Use Dual moving average/i }).click();
  await settle(page);
  await expect(page.getByTestId("paper-status-panel")).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByTestId("paper-first-session-arm")).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByTestId("paper-status-empty")).toContainText(
    /Start a paper run with the strategy you picked/i,
  );
  await shot(page, "04-run-arm-prompt.png");

  // 5–6. Arm → honest status + first-win celebrate.
  await page.getByTestId("paper-arm-balance").fill("1000");
  await page.getByTestId("paper-arm-submit").click();
  await settle(page);
  await expect(page.getByTestId("first-win-celebrate")).toBeVisible({
    timeout: 25_000,
  });
  await expect(page.getByTestId("first-win-celebrate-title")).toContainText(
    /Paper run is live on this computer/i,
  );
  // Status honesty under the toast (armed / paper-only).
  await expect(page.getByTestId("paper-status-panel")).toBeVisible();
  await shot(page, "05-status-after-arm.png");
  await shot(page, "06-win-celebrate.png");

  await page.getByTestId("first-win-celebrate-dismiss").click();
  await settle(page);
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);
  await expect(page.getByTestId("first-run-coach")).toHaveCount(0);

  // 7. Post-coach home — Advanced stack available, no trap.
  await clickNav(page, "Workspace");
  await settle(page);
  await expect(page.getByTestId("app-home")).toHaveAttribute(
    "data-home-advanced",
    "1",
  );
  await expect(page.getByTestId("app-home-path")).toBeVisible();
  await expect(page.getByTestId("app-home-path")).toHaveAttribute(
    "data-open",
    "0",
  );
  await shot(page, "07-post-coach-home.png");

  // 8. Mobile ~390 — coach + CTA composition (fresh home via new session
  // is expensive; resize and show post-coach CTA path instead, plus a
  // dedicated coach frame from a cold reload after clearing coach storage).
  await page.setViewportSize(MOBILE);
  await settle(page);
  await shot(page, "08-mobile-post-coach.png");

  // Cold mobile coach: clear coach + celebrate persistence and reload.
  await page.evaluate(() => {
    window.localStorage.removeItem("krellbot.home.firstRunCoach");
    window.localStorage.removeItem("krellbot.home.firstWinCelebrate");
  });
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await settle(page);
  await expect(page.getByTestId("first-run-coach")).toBeVisible();
  await expect(page.getByTestId("app-home-cta-paper")).toBeVisible();
  await shot(page, "09-mobile-coach-cta.png");

  if (RECORD) {
    // Persist Playwright video beside stills when recording was enabled.
    const video = page.video();
    if (video) {
      const src = await video.path();
      if (src) {
        const dest = path.join(OUT, "walkthrough-desktop.webm");
        fs.copyFileSync(src, dest);
        testInfo.attachments.push({
          name: "walkthrough-desktop",
          path: dest,
          contentType: "video/webm",
        });
      }
    }
  }
});
