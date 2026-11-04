import { test, expect } from "./journey-harness/journey-harness";
import { clickNav, openTechnicalJson, openLibrary, libraryRowFor, saveJson, readRevisionId, SMA_CROSS_FIXTURE_JSON } from "../journeys/helpers/journey-steps";

test("two keyboard-created copies of a long strategy id save as independent revisions", async ({ journey }) => {
  const page = journey.page;
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await clickNav(page, "Strategies");
  const source = { ...JSON.parse(SMA_CROSS_FIXTURE_JSON), id: "a".repeat(32) };
  const origin = await saveJson(page, JSON.stringify(source));
  const revisions = new Set([origin]);
  const identities = new Set([source.id]);
  for (let i = 0; i < 2; i++) {
    await openLibrary(page);
    const button = libraryRowFor(page, origin).getByRole("button", { name: /copy as new/i });
    await button.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("editor-revision-id")).toHaveCount(0);
    const copy = JSON.parse(await (await openTechnicalJson(page)).inputValue());
    expect(copy.id).toMatch(/^[a-z0-9][a-z0-9-]{0,31}$/);
    expect(identities.has(copy.id)).toBe(false);
    const { id: _id, label: _label, ...settings } = copy;
    const { id: _sourceId, label: _sourceLabel, ...originalSettings } = source;
    expect(settings).toEqual(originalSettings);
    identities.add(copy.id);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByTestId("editor-revision-id")).toBeVisible();
    const revision = await readRevisionId(page);
    expect(revisions.has(revision)).toBe(false);
    revisions.add(revision);
  }
  await page.reload();
  await journey.waitForSessionReady(page);
  await clickNav(page, "Strategies");
  await openLibrary(page);
  for (const revision of revisions) await expect(libraryRowFor(page, revision)).toBeVisible();
});
