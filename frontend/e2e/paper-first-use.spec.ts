import { test, expect } from "./journey-harness/journey-harness";
import { clickNav, pickStarter, openLibrary, validateRevision, runResearch, waitForResearchResult, armCurrentRevision } from "../journeys/helpers/journey-steps";

test("paper first use: save, validate, research synthetic data, arm, inspect and disarm", async ({ journey }) => {
  // Own fresh home, unused loopback port, fake keyring and network guards.
  // No owner deployment or real market history is touched by this smoke.
  const page = journey.page;
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await clickNav(page, "Strategies");
  await openLibrary(page);
  await expect(page.getByTestId("library-empty")).toBeVisible();
  await pickStarter(page);
  await page.getByRole("button", { name: /^save$/i }).click();
  await expect(page.getByTestId("editor-revision-id")).toBeVisible();
  await validateRevision(page, "validated");
  await clickNav(page, "Studio");
  await expect(page.getByTestId("graph-canvas")).toBeVisible();
  await clickNav(page, "Research");
  await runResearch(page, { dataset: journey.workstation.editCsv, feeBps: "10", from: "1700000000000", to: "1701436400000" });
  await waitForResearchResult(page);
  await expect(page.getByTestId("research-result-fee-bps")).toHaveText("10");
  await clickNav(page, "Strategies");
  await armCurrentRevision(page, "kraken", "1000");
  await expect(page.getByTestId("editor-inline-stop-entries")).toContainText(/active|armed/i);
  await clickNav(page, "Operations");
  await expect(page.getByRole("heading", { name: /operations/i }).first()).toBeVisible();
  await clickNav(page, "Workstation");
  await expect(page.getByTestId("paper-armed-row")).toHaveCount(1);
  await expect(page.getByTestId("paper-status-entries")).toContainText(/active/i);
  await clickNav(page, "Strategies");
  await page.getByRole("button", { name: /^disarm$/i }).click();
  await expect(page.getByTestId("editor-inline-stop-empty")).toHaveText("No pack armed");
  await clickNav(page, "Workstation");
  await expect(page.getByTestId("paper-armed-row")).toHaveCount(0);
});
