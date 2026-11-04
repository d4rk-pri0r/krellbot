import { test, expect } from "./journey-harness/journey-harness";
import { clickNav, saveJson, validateRevision, runResearch, waitForResearchResult, SMA_CROSS_FIXTURE_JSON } from "../journeys/helpers/journey-steps";

test("a completed synthetic research result reopens unchanged after workstation restart", async ({ journey }) => {
  const page = journey.page;
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await clickNav(page, "Strategies");
  await saveJson(page, SMA_CROSS_FIXTURE_JSON);
  await validateRevision(page, "validated");
  await clickNav(page, "Research");
  const { jobId } = await runResearch(page, { dataset: journey.workstation.editCsv, feeBps: "10", from: "1700000000000", to: "1701436400000" });
  await waitForResearchResult(page);
  const metrics = new Map<string, string>();
  for (const field of ["total-return-pct", "max-drawdown", "trade-count", "fee-bps", "data-manifest-sha256"]) {
    metrics.set(field, await page.getByTestId(`research-result-${field}`).innerText());
  }
  await journey.workstation.restartSameHome();
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await page.getByRole("button", { name: "Jobs", exact: true }).click();
  const row = page.getByTestId("job-row").filter({ hasText: jobId });
  await expect(row).toContainText("succeeded");
  await row.focus();
  await page.keyboard.press("Enter");
  await waitForResearchResult(page);
  for (const [field, value] of metrics) await expect(page.getByTestId(`research-result-${field}`)).toHaveText(value);
});
