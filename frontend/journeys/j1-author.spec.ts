/**
 * Phase 2 public — J1 Author a strategy without an account.
 *
 * Approved scenarios (docs/journeys/j1-author.md, word for word):
 *   J1.1 On a fresh install with no account, no exchange key and no
 *        internet, I can open Strategies, pick a starter and get an
 *        editable draft.
 *   J1.2 I can change the draft, for example an indicator length or
 *        the stop, and save it. It appears in my library as a new
 *        revision.
 *   J1.3 Saving with no changes tells me nothing changed and creates
 *        no new revision.
 *   J1.4 I can compare two revisions of a strategy and see exactly
 *        what changed between them.
 *   J1.5 After I restart the workstation, my strategies and all their
 *        revisions are still there, unchanged.
 *
 * Every observation is GUI behavior. The fresh home has no account,
 * no keys; the network guard denies anything off loopback (rule 1).
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import { expect, test } from "../e2e/journey-harness/journey-harness";
import {
  SMA_CROSS_FIXTURE_JSON,
  clickNav,
  openTechnicalJson,
  pickStarter,
  readRevisionId,
  saveJson,
  saveJsonExpecting,
  libraryRowFor,
  openLibrary,
} from "./helpers/journey-steps";

test.describe("J1 author", () => {
  let page: Page;

  test.beforeEach(async ({ journey }) => {
    page = journey.page;
    await page.goto(journey.workstation.baseURL);
    await journey.waitForSessionReady(page);
  });

  test("J1.1 On a fresh install with no account, no exchange key and no internet, I can open Strategies, pick a starter and get an editable draft", async ({ journey }) => {
    await clickNav(page, "Strategies");

    // The starter picker is the "pick a starter" affordance.
    const picker = page.getByTestId("starter-picker");
    await expect(picker).toBeVisible();
    await pickStarter(page);

    // "get an editable draft": the editor announces an unsaved draft
    // (no revision yet) and the raw JSON textarea exists, is editable,
    // and holds the starter's own parseable pack.
    await expect(
      page.getByText("No saved revision yet — Save creates one."),
    ).toBeVisible();
    const textarea = await openTechnicalJson(page);
    await expect(textarea).toBeEditable();
    const raw = await textarea.inputValue();
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    expect(typeof parsed).toBe("object");
    // A real DSL pack carries the fields the editor edits.
    for (const key of ["id", "indicators", "entry", "exit", "risk"]) {
      expect(parsed[key], `draft must carry ${key}`).toBeDefined();
    }
    // Editability is proven by editing: change the label through the
    // readable field and see the draft accept the change.
    await page.getByLabel(/^label$/i).fill("J1.1 edited draft");
    const labelValue = await page.getByLabel(/^label$/i).inputValue();
    expect(labelValue).toBe("J1.1 edited draft");
  });

  test("J1.2 I can change the draft, for example an indicator length or the stop, and save it. It appears in my library as a new revision", async () => {
    await clickNav(page, "Strategies");

    // Revision A: the committed sma_cross fixture pack, saved as a new
    // draft from a starter seed.
    const revisionA = await saveJson(page, SMA_CROSS_FIXTURE_JSON);
    expect(revisionA).not.toBe("");

    // Change BOTH an indicator length and the stop (the scenario's own
    // examples), then save. The edited JSON is what the editor holds.
    const changed = JSON.parse(SMA_CROSS_FIXTURE_JSON) as Record<string, unknown>;
    const indicators = changed.indicators as Record<string, { len: number }>;
    indicators.sma2.len = 7;
    const risk = changed.risk as { stop: { pct: number } };
    risk.stop.pct = 33;
    const textarea = await openTechnicalJson(page);
    await textarea.fill(JSON.stringify(changed, null, 2));
    const revisionB = await saveJsonExpecting(page, /saved new revision|selected existing revision/);
    expect(revisionB).not.toBe(revisionA);

    // "It appears in my library as a new revision": both revisions are
    // visible rows in the saved-strategy library.
    await openLibrary(page);
    await expect(libraryRowFor(page, revisionA)).toBeVisible();
    await expect(libraryRowFor(page, revisionB)).toBeVisible();

    // And revision B is genuinely the edited pack: the editor's JSON
    // holds the new length and stop, proving the change was saved with
    // the revision rather than silently dropped.
    const afterSave = await openTechnicalJson(page);
    const savedRaw = await afterSave.inputValue();
    expect(savedRaw).toContain('"len": 7');
    expect(savedRaw).toContain('"pct": 33');
  });

  test("J1.3 Saving with no changes tells me nothing changed and creates no new revision", async ({journey}) => {
    await clickNav(page, "Strategies");
    const revisionA = await saveJson(page, SMA_CROSS_FIXTURE_JSON);
    expect(revisionA).not.toBe("");
    await openLibrary(page);
    await expect(libraryRowFor(page, revisionA)).toBeVisible();
    const ids = () => page.getByTestId("library-row").evaluateAll(rows => rows.map(row => row.getAttribute("data-revision-id")));
    const before = await ids();
    expect(before.length, "no-op count must observe a real saved row").toBeGreaterThan(0);
    expect(before).toEqual([revisionA]);
    const draftFilesBefore = Object.keys(snapshotDir(join(journey.workstation.homeDir, "drafts"))).sort();
    expect(draftFilesBefore.length).toBeGreaterThan(0);

    await page.getByRole("button", {name: /^save$/i}).click();
    await expect(page.getByTestId("editor-save-outcome")).toContainText(/no change/i);
    expect(await readRevisionId(page)).toBe(revisionA);
    await openLibrary(page); // unmount/remount forces a real refreshed list
    await expect(libraryRowFor(page, revisionA)).toBeVisible();
    expect(await ids()).toEqual(before);
    expect(Object.keys(snapshotDir(join(journey.workstation.homeDir, "drafts"))).sort()).toEqual(draftFilesBefore);
  });

  test("J1.4 I can compare two revisions of a strategy and see exactly what changed between them", async () => {
    await clickNav(page, "Strategies");
    // Two revisions of ONE strategy: first save, then edit-in-place.
    const revisionA = await saveJson(page, SMA_CROSS_FIXTURE_JSON);
    const changed = JSON.parse(SMA_CROSS_FIXTURE_JSON) as Record<string, unknown>;
    const indicators = changed.indicators as Record<string, { len: number }>;
    indicators.sma2.len = 9;
    (changed.risk as { stop: { pct: number } }).stop.pct = 41;
    const textarea = await openTechnicalJson(page);
    await textarea.fill(JSON.stringify(changed, null, 2));
    const revisionB = await saveJsonExpecting(page, /saved new revision|selected existing revision/);
    expect(revisionB).not.toBe(revisionA);

    // Open the comparator and compare A -> B.
    await openLibrary(page);
    const rowB = libraryRowFor(page, revisionB);
    await rowB.locator('[data-testid="library-row-compare"]').click();
    await expect(page.getByTestId("revision-compare")).toBeVisible();
    await page.getByTestId("revision-compare-left").selectOption(revisionA);
    await page.getByTestId("revision-compare-right").selectOption(revisionB);
    await page.getByTestId("revision-compare-run").click();

    // "see exactly what changed": the change table names the two
    // edited paths — indicators.sma2.len (2 -> 9) and risk.stop.pct
    // (50 -> 41) — with earlier/later values, and nothing else.
    const changes = page.getByTestId("revision-compare-changes");
    await expect(changes).toBeVisible({ timeout: 20_000 });
    const rows = changes.locator('[data-testid="revision-compare-change"]');
    await expect(rows).toHaveCount(2, { timeout: 20_000 });
    const bodyText = await changes.innerText();
    expect(bodyText).toContain("indicators.sma2.len");
    expect(bodyText).toContain("risk.stop.pct");
    expect(bodyText).toContain("9");
    expect(bodyText).toContain("41");
    for (const [path, previous, next] of [["indicators.sma2.len", "2", "9"], ["risk.stop.pct", "50", "41"]]) {
      const cells=rows.filter({hasText:path}).getByRole("cell");
      await expect(cells.nth(2)).toHaveText(previous);
      await expect(cells.nth(3)).toHaveText(next);
    }
    // Nothing else changed — exactly the two edited paths.
    const allRowTexts = await rows.allInnerTexts();
    expect(
      allRowTexts.every((t) => /sma2\.len|risk\.stop\.pct/.test(t)),
      `unexpected changed paths: ${allRowTexts.join(" | ")}`,
    ).toBe(true);
    await page.getByTestId("revision-compare-close").click();
  });

  test("J1.5 After I restart the workstation, my strategies and all their revisions are still there, unchanged", async ({ journey }) => {
    // Independent setup (no dependency on earlier tests): create two
    // revisions of one strategy now.
    await clickNav(page, "Strategies");
    const revisionA = await saveJson(page, SMA_CROSS_FIXTURE_JSON);
    const changed = JSON.parse(SMA_CROSS_FIXTURE_JSON) as Record<string, unknown>;
    (changed.indicators as Record<string, { len: number }>).sma2.len = 11;
    const textarea = await openTechnicalJson(page);
    await textarea.fill(JSON.stringify(changed, null, 2));
    const revisionB = await saveJsonExpecting(page, /saved new revision|selected existing revision/);
    expect(revisionB).not.toBe(revisionA);

    // Snapshot the on-disk drafts tree — independent persisted
    // evidence the restart must preserve byte-for-byte.
    const draftsBefore = snapshotDir(join(journey.workstation.homeDir, "drafts"));

    // Restart on the SAME home (the harness re-binds the same port).
    await journey.workstation.restartSameHome();
    await page.goto(journey.workstation.baseURL);
    await journey.waitForSessionReady(page);

    // The drafts tree is unchanged...
    const draftsAfter = snapshotDir(join(journey.workstation.homeDir, "drafts"));
    expect(draftsAfter).toEqual(draftsBefore);

    // ...and the GUI still shows both revisions in the library.
    await clickNav(page, "Strategies");
    await openLibrary(page);
    await expect(libraryRowFor(page, revisionA)).toBeVisible({ timeout: 20_000 });
    await expect(libraryRowFor(page, revisionB)).toBeVisible();
  });
});

/** Map of relative path -> bytes for every file under dir. */
function snapshotDir(dir: string): Record<string, string> {
  const out: Record<string, string> = {};
  const walk = (current: string, prefix: string): void => {
    for (const entry of readdirSync(current)) {
      const full = join(current, entry);
      const rel = prefix ? `${prefix}/${entry}` : entry;
      if (statSync(full).isDirectory()) {
        walk(full, rel);
      } else {
        out[rel] = readFileSync(full, "utf8");
      }
    }
  };
  walk(dir, "");
  return out;
}
