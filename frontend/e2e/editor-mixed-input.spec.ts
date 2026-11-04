import { test, expect } from "./journey-harness/journey-harness";
import { clickNav, openTechnicalJson, openLibrary, libraryRowFor, readRevisionId, validateRevision } from "../journeys/helpers/journey-steps";

test("mixed raw JSON and readable edits persist together after reopening", async ({ journey }) => {
  const page = journey.page;
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await clickNav(page, "Strategies");
  await page.getByRole("button", { name: "Create new owned strategy", exact: true }).click();
  const raw = await openTechnicalJson(page);
  const pack = JSON.parse(await raw.inputValue());
  pack.indicators.ma.len = 41;
  await raw.fill(JSON.stringify(pack));
  await expect(page.getByLabel("Average length (bars)", { exact: true })).toHaveValue("41");
  await page.getByLabel("Protective stop percent", { exact: true }).fill("7");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByTestId("editor-revision-id")).toBeVisible();
  const revision = await readRevisionId(page);
  await validateRevision(page, "validated");
  await page.reload();
  await journey.waitForSessionReady(page);
  await clickNav(page, "Strategies");
  await openLibrary(page);
  await libraryRowFor(page, revision).getByRole("button", { name: /reopen/i }).click();
  const reopened = JSON.parse(await (await openTechnicalJson(page)).inputValue());
  expect(reopened.indicators.ma.len).toBe(41);
  expect(reopened.risk.stop.pct).toBe(7);
});
