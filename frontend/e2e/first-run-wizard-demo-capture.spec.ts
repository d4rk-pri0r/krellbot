/**
 * M26.8 Krell first-run wizard demo capture (KRELL-SIGNAL-20261010).
 *
 * Opt-in only: set FIRST_RUN_WIZARD_DEMO_DIR to a writable path
 * (Project store media/krell-first-run-wizard-demo). Skipped in CI.
 */
import { test, expect } from "./journey-harness/journey-harness";
import path from "node:path";
import fs from "node:fs";

const OUT = process.env.FIRST_RUN_WIZARD_DEMO_DIR?.trim() || "";

const DESKTOP = { width: 1440, height: 900 } as const;
const MOBILE = { width: 390, height: 844 } as const;

test.skip(
  !OUT,
  "set FIRST_RUN_WIZARD_DEMO_DIR to capture the Krell first-run wizard demo",
);

test.use({ wizardColdOpen: "fresh" });

async function settle(page: import("@playwright/test").Page): Promise<void> {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    });
  });
  await page.waitForTimeout(320);
}

async function shot(
  page: import("@playwright/test").Page,
  name: string,
): Promise<void> {
  fs.mkdirSync(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, name), fullPage: false });
}

async function expectWizardOnly(
  page: import("@playwright/test").Page,
  step: string,
): Promise<void> {
  const wizard = page.getByTestId("first-run-wizard");
  await expect(wizard).toBeVisible();
  await expect(wizard).toHaveAttribute("data-wizard-step", step);
  await expect(page.getByTestId("kbot-shell")).toHaveCount(0);
  await expect(page.getByTestId("kbot-nav")).toHaveCount(0);
  await expect(page.getByTestId("app-home")).toHaveCount(0);
  await expect(page.getByTestId("first-run-coach")).toHaveCount(0);
  await expect(page.getByTestId("activation-checklist")).toHaveCount(0);
  const visual = page.getByTestId("first-run-wizard-visual");
  await expect(visual).toBeVisible();
  await expect
    .poll(async () =>
      visual.evaluate((img: HTMLImageElement) =>
        img.complete && img.naturalWidth > 0 ? img.naturalWidth : 0,
      ),
    )
    .toBeGreaterThan(0);
}

test("capture Krell first-run wizard demo frames", async ({ journey }) => {
  const page = journey.page;
  await page.setViewportSize(DESKTOP);
  await page.goto(journey.workstation.baseURL);

  // 1. Welcome — full-screen Krell, one sentence, one sage CTA. No cockpit.
  await expectWizardOnly(page, "welcome");
  await expect(page.getByTestId("first-run-wizard-sentence")).toContainText(
    /pretend trading bot/i,
  );
  await expect(page.getByTestId("first-run-wizard-primary")).toHaveText(
    "Let’s go",
  );
  await expect(page.getByTestId("first-run-wizard-skip")).toHaveCount(0);
  await settle(page);
  await shot(page, "01-welcome.png");

  // 2. Choose — three consumer tiles, each with a sage Use.
  await page.getByTestId("first-run-wizard-primary").click();
  await expectWizardOnly(page, "choose");
  await expect(page.getByTestId("first-run-wizard-tiles")).toBeVisible();
  await expect(page.getByRole("button", { name: "Use" })).toHaveCount(3);
  await expect(page.getByText("Dual moving average")).toBeVisible();
  await expect(page.getByText("Mean reversion")).toBeVisible();
  await expect(page.getByText("Range breakout")).toBeVisible();
  await settle(page);
  await shot(page, "02-choose-tiles.png");

  // 3. Start paper — one big Start paper run CTA.
  await page.getByTestId("first-run-wizard-use-starter-dual-ma-crossover").click();
  const chooseError = page.getByTestId("first-run-wizard-choose-error");
  await expect
    .poll(
      async () => {
        if ((await chooseError.count()) > 0) {
          return `error:${await chooseError.innerText()}`;
        }
        return (
          (await page
            .getByTestId("first-run-wizard")
            .getAttribute("data-wizard-step")) ?? ""
        );
      },
      { timeout: 20_000 },
    )
    .toBe("start_paper");
  await expectWizardOnly(page, "start_paper");
  await expect(page.getByTestId("first-run-wizard-primary")).toHaveText(
    "Start paper run",
  );
  await settle(page);
  await shot(page, "03-start-paper.png");

  // 4. Status honesty — paper running sentence + live-trading chip. Still no shell.
  await page.getByTestId("first-run-wizard-primary").click();
  const armError = page.getByTestId("first-run-wizard-arm-error");
  await expect
    .poll(
      async () => {
        if ((await armError.count()) > 0) {
          return `error:${await armError.innerText()}`;
        }
        return (
          (await page
            .getByTestId("first-run-wizard")
            .getAttribute("data-wizard-step")) ?? ""
        );
      },
      { timeout: 20_000 },
    )
    .toBe("status");
  await expectWizardOnly(page, "status");
  await expect(page.getByTestId("first-run-wizard-sentence")).toContainText(
    /running on this computer/i,
  );
  await expect(page.getByTestId("first-run-wizard-status-chip")).toContainText(
    /Live trading unavailable/i,
  );
  await expect(page.getByTestId("first-run-wizard-status-chip")).toHaveAttribute(
    "data-paper-status",
    "running",
  );
  await expect(page.getByTestId("first-run-wizard-primary")).toHaveText(
    "Looks good",
  );
  await settle(page);
  await shot(page, "04-status-honesty.png");

  // 5. Win screen — still the wizard, not a cockpit toast.
  await page.getByTestId("first-run-wizard-primary").click();
  await expectWizardOnly(page, "win");
  await expect(page.getByTestId("first-run-wizard-sentence")).toContainText(
    /You’re set/i,
  );
  await expect(page.getByTestId("first-run-wizard-primary")).toHaveText(
    "Open Krellbot",
  );
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);
  await settle(page);
  await shot(page, "05-win.png");

  // 6. Post-wizard shell — Advanced available, no re-trap, no second celebrate.
  await page.getByTestId("first-run-wizard-primary").click();
  await journey.waitForSessionReady(page);
  await expect(page.getByTestId("first-run-wizard")).toHaveCount(0);
  await expect(page.getByTestId("kbot-shell")).toBeVisible();
  await expect(page.getByTestId("app-home")).toBeVisible();
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);
  await expect(page.getByTestId("first-run-coach")).toHaveCount(0);
  await expect(page.getByTestId("activation-checklist")).toHaveCount(0);
  await settle(page);
  await shot(page, "06-post-wizard-shell.png");

  // 7. Mobile ~390 — cold welcome + sage CTA, still no cockpit.
  await page.setViewportSize(MOBILE);
  await page.evaluate(() => {
    window.localStorage.removeItem("krellbot.home.firstRunWizard");
  });
  await page.goto(journey.workstation.baseURL);
  await expectWizardOnly(page, "welcome");
  const cta = page.getByTestId("first-run-wizard-primary");
  await expect(cta).toHaveText("Let’s go");
  await expect(cta).toBeVisible();
  const box = await cta.boundingBox();
  expect(box, "mobile welcome CTA is on screen").not.toBeNull();
  expect(box!.width).toBeGreaterThanOrEqual(44);
  expect(box!.height).toBeGreaterThanOrEqual(44);
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(MOBILE.width + 1);
  await settle(page);
  await shot(page, "07-mobile-welcome-cta.png");
});
