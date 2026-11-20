/**
 * Fresh install: full-screen wizard paper path, then a quiet shell.
 * Advanced stays reachable. The win screen is the only celebration.
 */
import { test, expect } from "../e2e/journey-harness/journey-harness";
import {
  clickNav,
  walkFirstRunWizardToWin,
} from "./helpers/journey-steps";

test.use({ wizardColdOpen: "fresh" });

test("a fresh install finishes the wizard paper path and opens a quiet shell with Advanced available", async ({
  journey,
}) => {
  const page = journey.page;
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(journey.workstation.baseURL);
  await walkFirstRunWizardToWin(page);

  await page.getByTestId("first-run-wizard-primary").click();
  await journey.waitForSessionReady(page);

  await expect(page.getByTestId("first-run-wizard")).toHaveCount(0);
  await expect(page.getByTestId("kbot-shell")).toBeVisible();
  await expect(page.getByTestId("app-home")).toBeVisible();
  await expect(page.getByTestId("app-home-path")).toHaveCount(0);
  await expect(page.getByTestId("app-home-keys-rail")).toHaveCount(0);
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);
  await expect(page.getByTestId("first-run-coach")).toHaveCount(0);
  await expect(page.getByTestId("activation-checklist")).toHaveCount(0);
  await expect(page.locator("[data-testid='soft-studio-tip']")).toHaveCount(0);

  await clickNav(page, "Settings");
  await expect(page.getByTestId("settings-view")).toBeVisible();
  await expect(page.getByTestId("settings-section-keys")).toBeVisible();

  await clickNav(page, "Run");
  await expect(page.getByTestId("paper-status-entries")).toContainText(/active/i, {
    timeout: 20_000,
  });
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);

  await clickNav(page, "Strategy studio");
  await expect(
    page.getByRole("navigation", { name: "Workstation navigation" }).getByTestId(
      "kbot-nav-more-toggle",
    ),
  ).toHaveAttribute("aria-expanded", "true");

  await page.reload();
  await journey.waitForSessionReady(page);
  await expect(page.getByTestId("first-run-wizard")).toHaveCount(0);
  await expect(page.getByTestId("kbot-shell")).toBeVisible();
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);
  await clickNav(page, "Workspace");
  await expect(page.getByTestId("app-home")).toBeVisible();
  await expect(page.getByTestId("first-run-coach")).toHaveCount(0);
  await expect(page.getByTestId("activation-checklist")).toHaveCount(0);
});
