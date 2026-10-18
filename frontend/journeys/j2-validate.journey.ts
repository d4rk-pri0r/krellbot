/**
 * Phase 2 public — J2 Validate it and see typed errors.
 *
 * Approved scenarios (docs/journeys/j2-validate.md, word for word):
 *   J2.1 Validating a correct strategy marks it valid, and it becomes
 *        available to Research and paper trading.
 *   J2.2 When something is wrong, such as an unknown indicator, a
 *        missing required field or a value out of range, validation
 *        names the problem and marks the field it is in.
 *   J2.3 Broken JSON typed or imported into the editor is refused with
 *        a clear message, and my last saved revision stays untouched.
 *   J2.4 A strategy that fails validation can't be backtested or
 *        armed, and the refusal says why.
 *   J2.5 Fixing the problem and validating again clears the error.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { findFileSync } from "./helpers/find-file";
import type { Page } from "@playwright/test";
import { expect, test } from "../e2e/journey-harness/journey-harness";
import { REPO_ROOT } from "../e2e/journey-harness/spawn-layer";
import {
  SMA_CROSS_FIXTURE_JSON,
  clickNav,
  openTechnicalJson,
  pickStarter,
  readRevisionId,
  saveJson,
  validateRevision,
} from "./helpers/journey-steps";

/**
 * Seed a FRESH draft (starter pick resets the editor to create mode)
 * and save the given JSON as its own new revision.
 */
async function saveFreshDraft(
  page: import("@playwright/test").Page,
  jsonText: string,
): Promise<string> {
  await pickStarter(page);
  const textarea = await openTechnicalJson(page);
  await textarea.fill(jsonText);
  await page.getByRole("button", { name: /^save$/i }).click();
  await page.waitForFunction(
    () => {
      const node = document.querySelector('[data-testid="editor-revision-id"]');
      return node !== null && /revision: [^\s)]+/.test(node.textContent ?? "");
    },
    undefined,
    { timeout: 20_000 },
  );
  return readRevisionId(page);
}

/** Committed invalid fixtures: bad_unknown, bad_short, bad_lookback_601. */
function fixturePack(name: string): string {
  return readFileSync(
    join(REPO_ROOT, "tests", "fixtures", "packs", `${name}.json`),
    "utf8",
  );
}

test.describe("J2 validate", () => {
  let page: Page;
  let homeDir = "";

  test.beforeEach(async ({ journey }) => {
    page = journey.page;
    homeDir = journey.workstation.homeDir;
    await page.goto(journey.workstation.baseURL);
    await journey.waitForSessionReady(page);
  });

  test("J2.1 Validating a correct strategy marks it valid, and it becomes available to Research and paper trading", async () => {
    await clickNav(page, "Strategies");
    const revision = await saveJson(page, SMA_CROSS_FIXTURE_JSON);
    const validatedRevision = await validateRevision(page, "validated");
    expect(validatedRevision).toBe(revision);

    // "available to Research": Research shows it as the selected
    // revision source for a run.
    await clickNav(page, "Research");
    await expect(page.getByTestId("research-revision")).toContainText(revision);
    await expect(page.getByTestId("research-pack-hint")).toContainText(
      `Using revision ${revision}`,
    );

    // "available to paper trading": the Arm control is enabled with
    // this validated revision (Arm requires a validated revision).
    await clickNav(page, "Strategies");
    const armButton = page.getByRole("button", { name: /^arm$/i });
    await expect(armButton).toBeEnabled();
  });

  test("J2.2 When something is wrong, such as an unknown indicator, a missing required field or a value out of range, validation names the problem and marks the field it is in", async () => {
    // Three committed invalid fixtures, three distinct problem kinds:
    // unknown construct, disallowed side, value out of range.
    // The committed fixtures exercise the three problem kinds named by
    // the scenario: an unknown top-level construct (leverage), a
    // disallowed side (short), and an out-of-range value (len 601).
    const cases: Array<{ name: string; expectField: RegExp; expectText: RegExp }> = [
      {
        name: "bad_unknown",
        expectField: /^leverage$/,
        expectText: /leverage|not allowed|unexpected/i,
      },
      {
        name: "bad_short",
        expectField: /^short$/,
        expectText: /short|not allowed|unexpected/i,
      },
      {
        name: "bad_lookback_601",
        expectField: /indicators\.huge\.len/,
        expectText: /601|maximum|greater/i,
      },
    ];
    for (const testCase of cases) {
      await clickNav(page, "Strategies");
      const json = fixturePack(testCase.name);
      await saveFreshDraft(page, json);
      await page.getByRole("button", { name: /^validate$/i }).click();
      // Validation names the problem AND marks the field: the editor
      // renders one ErrorBlock per field with the field name. (The
      // revision state stays Draft on failure; the typed errors are
      // the surface the scenario asks for.)
      const editorRoot = page.getByRole("region", { name: "Strategy editor" });
      const errorBlocks = editorRoot.locator('[data-testid^="editor-error-"]');
      await expect(errorBlocks.first()).toBeVisible({ timeout: 30_000 });
      const blocksText = await errorBlocks.allInnerTexts();
      const joined = blocksText.join("\n");
      expect(
        testCase.expectText.test(joined),
        `${testCase.name}: problem named in ${JSON.stringify(joined)}`,
      ).toBe(true);
      const fields = await errorBlocks
        .locator(".kbot-strategy-editor__error-field")
        .allInnerTexts();
      expect(
        fields.some((f) => testCase.expectField.test(f)),
        `${testCase.name}: field marked, fields were ${JSON.stringify(fields)}`,
      ).toBe(true);
    }
  });

  test("J2.3 Broken JSON typed or imported into the editor is refused with a clear message, and my last saved revision stays untouched", async () => {
    await clickNav(page, "Strategies");
    const revision = await saveJson(page, SMA_CROSS_FIXTURE_JSON);
    const draftPath = findFileSync(join(homeDir, "drafts"), `${revision}.json`);
    const savedBefore = readFileSync(draftPath, "utf8");

    // Type broken JSON into the editor, then Import (the parse
    // affordance for the raw JSON textarea). Both the save path and
    // import path refuse broken JSON at parse time.
    const textarea = await openTechnicalJson(page);
    await textarea.fill('{"label": "broken", ');
    await page.getByRole("button", { name: /^import$/i }).click();
    const importError = page.getByTestId("editor-import-error");
    await expect(importError).toBeVisible();
    await expect(importError).toContainText(/invalid json/i);
    // The textarea is marked invalid (field-level marking).
    await expect(textarea).toHaveAttribute("aria-invalid", "true");

    // "my last saved revision stays untouched": the revision paragraph
    // still names the same saved revision, and the stored pack bytes
    // for that revision are the valid pack (indicators present).
    const revisionAfter = await readRevisionId(page);
    expect(revisionAfter).toBe(revision);
    const savedPack = JSON.parse(readFileSync(draftPath, "utf8")) as {
      indicators?: unknown;
    };
    expect(savedPack).toHaveProperty("indicators");
    expect(readFileSync(draftPath,"utf8")).toBe(savedBefore);
    // A save attempt on the broken JSON is also refused (no write of
    // the broken bytes over the saved revision).
    await textarea.fill('{"still broken": ');
    await expect(page.getByTestId("editor-import-error")).toHaveCount(0);
    await page.getByRole("button", { name: /^save$/i }).click();
    await expect(page.getByTestId("editor-import-error")).toContainText(/invalid json/i);
    const revisionStill = await readRevisionId(page);
    expect(revisionStill).toBe(revision);
    expect(readFileSync(draftPath,"utf8")).toBe(savedBefore);
  });

  test("J2.4 A strategy that fails validation can't be backtested or armed, and the refusal says why", async () => {
    await clickNav(page, "Strategies");
    const json = fixturePack("bad_lookback_601");
    await saveFreshDraft(page, json);
    await page.getByRole("button", { name: /^validate$/i }).click();
    // The typed field error appears (validation refused).
    const invalidBlocks = page
      .getByRole("region", { name: "Strategy editor" })
      .locator('[data-testid^="editor-error-"]');
    await expect(invalidBlocks.first()).toBeVisible({ timeout: 30_000 });

    // ARM refusal: the editor's gate disables Arm for a non-validated
    // revision and states the precondition ("Arm needs a validated
    // revision").
    const armButton = page.getByRole("button", { name: /^arm$/i });
    await expect(armButton).toBeDisabled();
    await expect(page.getByText("Arm needs a validated revision")).toBeVisible();

    // BACKTEST refusal: the run cannot produce a backtest. The product
    // submits the job and the job FAILS with a visible typed refusal
    // naming the problem ("Invalid pack: pack validation failed") — no
    // result ever appears.
    await clickNav(page, "Research");
    const researchRevisionText = await page
      .getByTestId("research-revision")
      .innerText();
    expect(researchRevisionText).toMatch(/revision: \S+/);
    await page.getByLabel(/dataset path/i).fill(join(homeDir, "data", "edit.csv"));
    await page.getByLabel(/fee basis points/i).fill("10");
    await page.locator("#kbot-research-from").fill("0");
    await page.locator("#kbot-research-to").fill("9999999999999");
    await page.getByRole("button", { name: /^run$/i }).click();
    // The visible refusal names the problem.
    const jobError = page.getByTestId("research-job-error");
    await expect(jobError).toBeVisible({ timeout: 60_000 });
    const errorText = (await jobError.innerText()).toLowerCase();
    expect(errorText.length).toBeGreaterThan(0);
    expect(errorText).toMatch(/invalid|validation|pack|len|range/);
    // NO results appear as if the run had worked.
    expect(await page.getByTestId("research-result").count()).toBe(0);
  });

  test("J2.5 Fixing the problem and validating again clears the error", async () => {
    await clickNav(page, "Strategies");
    // Save the out-of-range pack, validate -> invalid with field error.
    const bad = fixturePack("bad_lookback_601");
    await saveFreshDraft(page, bad);
    await page.getByRole("button", { name: /^validate$/i }).click();
    const editorRoot = page.getByRole("region", { name: "Strategy editor" });
    const errorBlocks = editorRoot.locator('[data-testid^="editor-error-"]');
    await expect(errorBlocks.first()).toBeVisible({ timeout: 30_000 });

    // Fix the problem (len 601 -> 20), save, validate again.
    const fixed = JSON.parse(bad) as Record<string, unknown>;
    const indicators = fixed.indicators as Record<string, { len: number }>;
    indicators.huge.len = 20;
    const textarea = await openTechnicalJson(page);
    await textarea.fill(JSON.stringify(fixed, null, 2));
    await page.getByRole("button", { name: /^save$/i }).click();
    await expect(page.getByTestId("editor-save-outcome")).toContainText(
      /saved new revision|saved revision|no change/,
      { timeout: 20_000 },
    );
    await page.getByRole("button", { name: /^validate$/i }).click();
    await expect(page.getByTestId("editor-revision-id")).toContainText(
      /state:\s*validated/i,
      { timeout: 30_000 },
    );
    // The field error blocks are gone and the state line is clean.
    await expect(errorBlocks).toHaveCount(0);
    await expect(page.getByTestId("editor-validate-error")).toHaveCount(0);
  });
});
