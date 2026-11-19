/**
 * M25.8 — first paper arm celebrates once, then silence (KRELL-SIGNAL-20261010).
 */
import { test, expect } from "./journey-harness/journey-harness";
import { armPaper } from "../journeys/helpers/paper-steps";
import { clickNav } from "../journeys/helpers/journey-steps";

test("first paper arm shows celebrate toast once and keeps the coach silent", async ({
  journey,
}) => {
  const page = journey.page;
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await armPaper(page, "1000");
  await clickNav(page, "Workstation");
  await expect(page.getByTestId("first-win-celebrate")).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByTestId("first-win-celebrate-title")).toContainText(
    /Paper run is live on this computer/i,
  );
  await expect(page.getByTestId("first-run-coach")).toHaveCount(0);
  await page.getByTestId("first-win-celebrate-dismiss").click();
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);
  await page.reload();
  await journey.waitForSessionReady(page);
  await clickNav(page, "Workstation");
  await expect(page.getByTestId("first-win-celebrate")).toHaveCount(0);
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
