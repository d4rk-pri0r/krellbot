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
  const reopenedJson = await openTechnicalJson(page);
  // Reopen loads the saved revision asynchronously; the editor can still be
  // empty at this instant. Wait for the document, then assert it unchanged.
  await expect
    .poll(
      async () => {
        try {
          return JSON.parse(await reopenedJson.inputValue()).indicators?.ma?.len ?? null;
        } catch {
          return null;
        }
      },
      { timeout: 15_000 },
    )
    .toBe(41);
  const reopened = JSON.parse(await reopenedJson.inputValue());
  expect(reopened.indicators.ma.len).toBe(41);
  expect(reopened.risk.stop.pct).toBe(7);
});
