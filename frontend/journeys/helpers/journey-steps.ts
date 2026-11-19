/**
 * Shared GUI journey steps (scenario-safe helpers).
 *
 * Each helper drives a real GUI affordance (button, field, drawer).
 * Nothing here substitutes an API call for a user action; the file
 * reads allowed by the brief (temp-home journals) live in the specs.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import type { Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { REPO_ROOT } from "../../e2e/journey-harness/spawn-layer";

/** The committed pack fixture, byte-for-byte from tests/fixtures/packs. */
export const SMA_CROSS_FIXTURE_JSON = readFileSync(
  join(REPO_ROOT, "tests", "fixtures", "packs", "sma_cross.json"),
  "utf8",
);

/** The committed 8-row candle fixture (kraken_SUIUSD_1h_sample.csv). */
export const COMMITTED_CANDLE_CSV = join(
  REPO_ROOT,
  "tests",
  "fixtures",
  "candles",
  "kraken_SUIUSD_1h_sample.csv",
);

/** Labels that live under the More overflow (M24 primary + More nav). */
const MORE_NAV_LABELS = new Set([
  "Research",
  "Strategy studio",
  "Operations",
  "Deploy",
]);

export async function clickNav(page: Page, label: string): Promise<void> {
  // A modal Jobs drawer (left open by an expected-fail scenario) would
  // intercept pointer events; close it first so scenario order never
  // matters.
  const closeButton = page.getByRole("button", { name: /close jobs drawer/i });
  if (await closeButton.count()) {
    await closeButton.click().catch(() => undefined);
    await page
      .waitForSelector('[data-testid="kbot-jobs-dialog"]', { state: "detached", timeout: 5_000 })
      .catch(() => undefined);
  }
  // M24: UI label "Workstation" → "Run"; route id stays workstation.
  const resolved = label === "Workstation" ? "Run" : label;
  const nav = page.getByRole("navigation", { name: "Workstation navigation" });
  if (MORE_NAV_LABELS.has(resolved)) {
    const moreToggle = nav.getByTestId("kbot-nav-more-toggle");
    if ((await moreToggle.getAttribute("aria-expanded")) !== "true") {
      await moreToggle.click();
    }
    await expect(moreToggle).toHaveAttribute("aria-expanded", "true");
  }
  await nav.getByRole("button", { name: resolved, exact: true }).click();
}

/**
 * Expand a DisclosureSection by its `data-testid` root (toggle is `${id}-toggle`).
 * M18.4 collapses Operations Advanced panels by default.
 */
export async function expandDisclosure(page: Page, panelTestId: string): Promise<void> {
  const toggle = page.getByTestId(`${panelTestId}-toggle`);
  await expect(toggle).toBeVisible();
  if ((await toggle.getAttribute("aria-expanded")) !== "true") {
    await toggle.click();
  }
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
}

/** Matches `FIRST_RUN_WIZARD_STORAGE_KEY` in firstRunWizardPersistence. */
export const FIRST_RUN_WIZARD_E2E_STORAGE_KEY = "krellbot.home.firstRunWizard";

/** Skipped persistence so App mounts WorkstationShell (shell suites). */
export const DISMISSED_FIRST_RUN_WIZARD_JSON = JSON.stringify({
  status: "skipped",
  stepId: "welcome",
  selectedStarterId: null,
});

type InitScriptHost = {
  addInitScript: (
    script: (arg: { key: string; value: string }) => void,
    arg: { key: string; value: string },
  ) => Promise<void>;
};

/**
 * Seed dismissed wizard before the first navigation so App cold-opens the
 * shell (M26.4). Call on BrowserContext / Page before goto.
 */
export async function seedDismissedFirstRunWizard(
  host: InitScriptHost,
): Promise<void> {
  await host.addInitScript(
    ({ key, value }) => {
      try {
        window.localStorage.setItem(key, value);
      } catch {
        // Best-effort only.
      }
    },
    {
      key: FIRST_RUN_WIZARD_E2E_STORAGE_KEY,
      value: DISMISSED_FIRST_RUN_WIZARD_JSON,
    },
  );
}

/**
 * Dismiss FirstRunWizard when e2e/journeys need WorkstationShell (M26.4).
 *
 * Prefers the real Skip UI (Let’s go → Skip setup). If the wizard is still
 * mounted, seeds dismissed persistence and reloads so App remounts the shell.
 * Awaits wizard unmount + persisted dismiss — never swallows click failures.
 */
export async function skipFirstRunWizard(page: Page): Promise<void> {
  const wizard = page.getByTestId("first-run-wizard");
  const shell = page.getByTestId("kbot-shell");

  // Cold open may still be choosing wizard vs shell.
  await Promise.race([
    wizard.waitFor({ state: "attached", timeout: 8_000 }).catch(() => undefined),
    shell.waitFor({ state: "attached", timeout: 8_000 }).catch(() => undefined),
  ]);

  if ((await wizard.count()) === 0) {
    return;
  }

  const skip = page.getByTestId("first-run-wizard-skip");
  const primary = page.getByTestId("first-run-wizard-primary");
  // Welcome has no Skip — advance once so Skip setup appears.
  if ((await skip.count()) === 0 && (await primary.count()) > 0) {
    await primary.click({ timeout: 5_000 });
    await expect(skip).toBeVisible({ timeout: 5_000 });
  }
  if ((await skip.count()) > 0) {
    await skip.click({ timeout: 5_000 });
  }

  // Fallback: force dismissed persistence + remount App gate.
  if ((await wizard.count()) > 0) {
    await page.evaluate(
      ({ key, value }) => {
        window.localStorage.setItem(key, value);
      },
      {
        key: FIRST_RUN_WIZARD_E2E_STORAGE_KEY,
        value: DISMISSED_FIRST_RUN_WIZARD_JSON,
      },
    );
    await page.reload({ waitUntil: "domcontentloaded" });
  }

  await expect(wizard).toHaveCount(0, { timeout: 15_000 });
  await page.waitForFunction(
    (key) => {
      try {
        const raw = window.localStorage.getItem(key);
        if (!raw) {
          return false;
        }
        const status = JSON.parse(raw).status as string;
        return status === "skipped" || status === "completed";
      } catch {
        return false;
      }
    },
    FIRST_RUN_WIZARD_E2E_STORAGE_KEY,
    { timeout: 5_000 },
  );
}

/**
 * Dismiss FirstRunCoach when tests need Advanced / demoted controls.
 * Welcome has no Skip — Start once, then Skip guide. No-op when absent.
 * Keeps product demotion; only clears the overlay that can intercept clicks.
 *
 * Race-safe with M25.8 first-win celebrate: a confirmed paper arm can
 * complete the coach while this helper runs — treat a detached coach as done.
 */
export async function skipFirstRunCoach(page: Page): Promise<void> {
  const coach = page.getByTestId("first-run-coach");
  if ((await coach.count()) === 0) {
    return;
  }
  const skip = page.getByTestId("first-run-coach-skip");
  if ((await skip.count()) === 0) {
    await page
      .getByTestId("first-run-coach-primary")
      .click({ timeout: 5_000 })
      .catch(() => undefined);
  }
  if ((await coach.count()) === 0) {
    return;
  }
  if ((await skip.count()) > 0) {
    await skip.click({ timeout: 5_000 }).catch(() => undefined);
  }
  await expect(coach).toHaveCount(0);
}

/** Open the technical JSON disclosure and return the textarea locator. */
export async function openTechnicalJson(page: Page): Promise<Locator> {
  const details = page.getByTestId("editor-technical-section");
  await details.waitFor({ state: "visible", timeout: 15_000 });
  const open = await details.evaluate((el: HTMLDetailsElement) => el.open);
  if (!open) {
    await details.locator("summary").click();
  }
  const textarea = page.getByLabel(/raw json/i);
  await expect(textarea).toBeVisible();
  return textarea;
}

/**
 * Pick the first starter example (the GUI affordance). The picker
 * lazy-loads through a one-shot IntersectionObserver, so it must be
 * scrolled into view first; a picker that already fired loads
 * directly and the items are present either way.
 */
export async function pickStarter(page: Page): Promise<void> {
  const picker = page.getByTestId("starter-picker");
  await picker.scrollIntoViewIfNeeded();
  await page
    .locator('[data-testid^="starter-picker-item-"]')
    .first()
    .waitFor({ state: "visible", timeout: 20_000 });
  await page
    .locator('[data-testid^="starter-picker-item-"]')
    .first()
    .locator("button")
    .click();
}

/**
 * Fill the raw JSON with `jsonText` and Save. Resolves with the new
 * revision id (the editor's revision paragraph).
 */
export async function saveJson(page: Page, jsonText: string): Promise<string> {
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

/**
 * Save (textarea already holds the desired bytes) and expect a given
 * outcome label; resolves with the revision id after the save settles.
 */
export async function saveJsonExpecting(
  page: Page,
  outcomeRe: RegExp,
): Promise<string> {
  await page.getByRole("button", { name: /^save$/i }).click();
  await expect(page.getByTestId("editor-save-outcome")).toContainText(outcomeRe, {
    timeout: 20_000,
  });
  return readRevisionId(page);
}

export async function readRevisionId(page: Page): Promise<string> {
  const text = await page.getByTestId("editor-revision-id").innerText();
  const match = text.match(/revision:\s*([^\s)]+)/);
  if (!match) {
    throw new Error(`could not parse revision id from ${JSON.stringify(text)}`);
  }
  return match[1];
}

/** Validate the current revision via the GUI and wait for state. */
export async function validateRevision(
  page: Page,
  state: "validated" | "invalid",
): Promise<string> {
  await page.getByRole("button", { name: /^validate$/i }).click();
  await page.waitForFunction(
    (expected) => {
      const node = document.querySelector('[data-testid="editor-revision-id"]');
      return new RegExp(`state:\\s*${expected}`, "i").test(node?.textContent ?? "");
    },
    state,
    { timeout: 30_000 },
  );
  return readRevisionId(page);
}

/** Open (or refresh) the saved-strategy library panel. */
export async function openLibrary(page: Page): Promise<void> {
  const present = await page.getByTestId("saved-strategy-library").count();
  if (present > 0) {
    // Force a fresh fetch: the library caches rows on mount.
    await page.getByTestId("library-toggle").click().catch(() => undefined);
    await page
      .waitForSelector('[data-testid="saved-strategy-library"]', {
        state: "detached",
        timeout: 5_000,
      })
      .catch(() => undefined);
  }
  await page.getByTestId("library-toggle").click();
  await page
    .getByTestId("saved-strategy-library")
    .waitFor({ state: "visible", timeout: 15_000 });
  await page.waitForFunction(
    () =>
      document.querySelectorAll('[data-testid="library-row"]').length > 0 ||
      document.querySelector('[data-testid="library-empty"]') !== null,
    undefined,
    { timeout: 15_000 },
  );
}

export function libraryRowFor(page: Page, revisionId: string): Locator {
  return page.locator(
    `li[data-testid="library-row"][data-revision-id="${revisionId}"]`,
  );
}

/** Fill the research form and click Run; resolves when the POST returns. */
export async function runResearch(
  page: Page,
  opts: { dataset: string; feeBps: string; from: string; to: string },
): Promise<{ jobId: string; postStatus: number }> {
  await page.getByLabel(/dataset path/i).fill(opts.dataset);
  await page.getByLabel(/fee basis points/i).fill(opts.feeBps);
  await page.locator("#kbot-research-from").fill(opts.from);
  await page.locator("#kbot-research-to").fill(opts.to);
  const [post] = await Promise.all([
    page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        new URL(r.url()).pathname === "/api/v1/research/jobs",
      { timeout: 30_000 },
    ),
    page.getByTestId("research-run").click(),
  ]);
  const body = (await post.json()) as { id?: string };
  return { jobId: body.id ?? "", postStatus: post.status() };
}

/** Read the research job id the view currently shows. */
export async function readResearchJobId(page: Page): Promise<string> {
  const text = await page.getByTestId("research-job-id").innerText();
  const match = text.match(/job\s+(\S+)/);
  return match ? match[1] : "";
}

/** Wait for the research result panel (auto-fetched by pollForResult). */
export async function waitForResearchResult(page: Page): Promise<void> {
  await expect(page.getByTestId("research-result")).toBeVisible({
    timeout: 90_000,
  });
}

/** Arm the current validated revision through the editor form. */
export async function armCurrentRevision(
  page: Page,
  venue: string,
  balance: string,
): Promise<void> {
  await page.locator("#kbot-strategy-editor-venue").fill(venue);
  await page.locator("#kbot-strategy-editor-balance").fill(balance);
  await page.getByRole("button", { name: /^arm$/i }).click();
}

/** Journal tick records from the temp home (independent evidence). */
export type TickRecord = {
  kind?: string;
  ts: number;
  venue: string;
  pack: string;
  bar_ts: number;
  detail: {
    pair?: string;
    reason?: string;
    entry_qty?: string;
    exit_qty?: string;
    stop_qty?: string;
    owned_qty_after?: string;
    entries_paused?: boolean;
    [key: string]: unknown;
  };
};

export function readJournalTicks(homeDir: string): TickRecord[] {
  const journalDir = join(homeDir, "journal");
  const records: TickRecord[] = [];
  let files: string[];
  try {
    files = readdirSync(journalDir);
  } catch {
    return [];
  }
  for (const name of files.filter((n) => n.endsWith(".jsonl")).sort()) {
    let text: string;
    try {
      text = readFileSync(join(journalDir, name), "utf8");
    } catch {
      continue;
    }
    for (const line of text.split("\n")) {
      if (!line.trim()) continue;
      try {
        const rec = JSON.parse(line) as TickRecord;
        if (rec.kind === "tick") {
          records.push(rec);
        }
      } catch {
        // skip malformed line
      }
    }
  }
  return records;
}

/**
 * Click Run for input the product may refuse BEFORE submitting (no
 * POST at all) or accept and then fail. Resolves which happened: the
 * jobId is empty on a pre-submit refusal (a visible alert is then
 * expected on the page).
 */
export async function runResearchMaybe(
  page: Page,
  opts: { dataset: string; feeBps: string; from: string; to: string },
): Promise<{ jobId: string; submitted: boolean }> {
  await page.getByLabel(/dataset path/i).fill(opts.dataset);
  await page.getByLabel(/fee basis points/i).fill(opts.feeBps);
  await page.locator("#kbot-research-from").fill(opts.from);
  await page.locator("#kbot-research-to").fill(opts.to);
  const postOrTimeout = page
    .waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        new URL(r.url()).pathname === "/api/v1/research/jobs",
      { timeout: 10_000 },
    )
    .then((post) => post)
    .catch(() => null);
  await page.getByTestId("research-run").click();
  const post = await postOrTimeout;
  if (post === null) {
    return { jobId: "", submitted: false };
  }
  const body = (await post.json().catch(() => ({}))) as { id?: string };
  return { jobId: body.id ?? "", submitted: true };
}
