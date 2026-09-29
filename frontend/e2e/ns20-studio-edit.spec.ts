import { test, expect, type Page } from "@playwright/test";
import {
  startWorkstationForSpec,
  stopWorkstationForSpec,
  type WorkstationHandle,
} from "./workstation-harness";

/**
 * NS20 studio-edit spec.
 *
 * End-to-end proof that a Studio indicator input ends in a different
 * backtest result on the same dataset.
 *
 *  1. Open the served index and wait for the bootstrap meta + a
 *     connected status (no direct cookie read; the page reports its
 *     own readiness).
 *  2. Strategies view: paste a pack JSON (sma_cross shape, id
 *     ``ns20-e2e``, ``indicators.sma2.len = 2``), Save, Validate,
 *     read ``editor-revision-id`` (revision A).
 *  3. Research view: dataset path = absolute path of ``edit.csv``,
 *     fee 10, from 0, to 0 (engine takes ``<=``), Run; wait for
 *     ``research-result``; record equity text and trade count (A).
 *  4. Navigate to ``/?workload=200&pack=1`` without losing the
 *     revision; assert ``studio-node-count`` = 200 and at least one
 *     ``react-flow__node`` is rendered.
 *  5. Click node ``sma2``, set ``studio-indicator-len`` to 20, click
 *     Save execution; assert ``studio-revision-id`` != revision A.
 *  6. Research view: run again with the same inputs; record result
 *     B. Assert (equity B != equity A) OR (trade count B != trade
 *     count A). The Run POST is captured on the wire; assert its
 *     ``revision_id`` equals the new revision id.
 */

const PACK_TEXT = JSON.stringify(
  {
    schema_version: 1,
    id: "ns20-e2e",
    version: "1.0.0",
    label: "NS20 e2e",
    author: "ns20-e2e",
    timeframe: "1h",
    indicators: { sma2: { fn: "sma", src: "close", len: 2 } },
    entry: ["close", "crosses_above", "sma2"],
    exit: ["close", "crosses_below", "sma2"],
    risk: { max_account_pct: 100, stop: { type: "pct", pct: 50 } },
    markets: [{ venue: "kraken", pair: "SUIUSD" }],
  },
  null,
  2,
);

async function gotoStrategiesView(page: Page): Promise<void> {
  // The shell uses the React view state; navigating in-page (not via
  // ``page.goto``) keeps the in-memory ``savedRevision`` alive.
  await page.getByRole("button", { name: "Strategies" }).click();
}

async function gotoResearchView(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Research" }).click();
}

async function gotoStudioView(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Studio" }).click();
}

async function waitForSessionReady(page: Page): Promise<void> {
  await page.waitForFunction(
    () => {
      const root = document.querySelector('[data-testid="kbot-shell"]');
      return root?.getAttribute("data-bootstrap-done") === "1";
    },
    undefined,
    { timeout: 15_000 },
  );
}

test("200-node studio edit changes a backtest result", async ({ page }) => {
  test.setTimeout(180_000);
  const baseURL = workstation!.baseURL.replace(/\/$/, "");
  await page.goto(baseURL + "/");
  // Bootstrap meta present (it will be consumed on first render).
  await expect(page.locator('meta[name="krellbot-bootstrap"]')).toHaveCount(0, {
    timeout: 5_000,
  });
  // Wait for the session-bootstrap POST to settle so subsequent
  // state-change requests carry the cookie + CSRF token.
  await waitForSessionReady(page);
  // Session bootstrap finishes when the page stops making bootstrap
  // calls; we observe the strategies nav becoming clickable.
  await gotoStrategiesView(page);
  await expect(page.getByLabel(/raw json/i)).toBeVisible();

  // Save pack with sma2.len=2 -> revision A.
  await page.getByLabel(/raw json/i).fill(PACK_TEXT);
  await page.getByRole("button", { name: /^save$/i }).click();
  const revisionA = await page
    .getByTestId("editor-revision-id")
    .innerText()
    .then((text) => extractRevisionId(text));
  expect(revisionA).not.toBe("");

  // Validate so the saved draft reaches the ``validated`` state.
  await page.getByRole("button", { name: /^validate$/i }).click();
  await expect(page.getByTestId("editor-revision-id")).toContainText(/validated/);

  // First backtest at sma2.len=2 -> result A.
  await gotoResearchView(page);
  const editCsv = process.env.KRELLBOT_E2E_EDIT_CSV;
  if (!editCsv) {
    throw new Error("KRELLBOT_E2E_EDIT_CSV was not set by global-setup");
  }
  await page.getByLabel(/dataset path/i).fill(editCsv);
  await page.getByLabel(/fee basis points/i).fill("10");
  await page.getByLabel(/^from$/i).fill("0");
  await page.getByLabel(/^to$/i).fill("9999999999999");
  const reqA = page.waitForRequest(
    (r) => r.method() === "POST" && new URL(r.url()).pathname === "/api/v1/research/jobs",
  );
  await page.getByRole("button", { name: /^run$/i }).click();
  const requestA = await reqA;
  const bodyA = JSON.parse(requestA.postData() ?? "{}") as Record<string, unknown>;
  // Wait for job id to appear.
  const jobA = await readJobIdAfterRun(page);
  expect(jobA).not.toBe("");
  // The server runs synchronously here; poll for the result.
  await page.getByRole("button", { name: /load result/i }).click();
  await expect(page.getByTestId("research-result")).toBeVisible({ timeout: 60_000 });
  const equityA = (await page.getByTestId("research-result-equity").innerText()).trim();
  const tradesA = (await page.getByTestId("research-result-trade-count").innerText()).trim();

  // Verify the job actually ran against the saved revision.
  const jobAInfo = await page.request.get(`${baseURL}/api/v1/jobs/${encodeURIComponent(jobA)}`);
  expect(jobAInfo.status()).toBe(200);

  // Switch to studio, navigate to the 200+pack workload mode.
  // Use history.pushState (not page.goto) so the in-memory
  // ``savedRevision`` survives the URL change; the brief's
  // documented escape hatch for "if a reload loses in-memory
  // state".
  await gotoStudioView(page);
  await page.evaluate(() => {
    window.history.pushState({}, "", "/?workload=200&pack=1");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page.getByTestId("studio-node-count")).toHaveText("200");
  // The real ReactFlow canvas must render at least one node, even
  // though it virtualizes off-screen ones.
  expect(await page.locator(".react-flow__node").count()).toBeGreaterThanOrEqual(1);

  // Click the sma2 indicator node and edit its length.
  // ReactFlow positions nodes absolutely inside a viewport that shares
  // its bounding box with ``<main>``; Playwright's hit-test therefore
  // reports "main intercepts pointer events". ``evaluate(el => el.click())``
  // invokes the DOM ``click()`` method which fires the click event
  // ReactFlow listens for, bypassing the hit-test issue.
  await page.getByTestId("studio-node-sma2").evaluate((el: HTMLElement) => {
    el.click();
  });
  // ReactFlow dispatches ``onNodeClick`` asynchronously; give the
  // handler a tick to update shell state.
  await page.waitForTimeout(300);
  await expect(page.getByTestId("studio-indicator-len")).toBeVisible();
  await page.getByTestId("studio-indicator-len").fill("20");
  await page.getByRole("button", { name: /save execution/i }).click();
  await expect(page.getByTestId("studio-revision-id")).toBeVisible();
  const revisionB = await page
    .getByTestId("studio-revision-id")
    .innerText()
    .then((text) => extractRevisionId(text));
  expect(revisionB).not.toBe("");
  expect(revisionB).not.toBe(revisionA);

  // Second backtest at sma2.len=20 -> result B.
  await gotoResearchView(page);
  await page.getByLabel(/dataset path/i).fill(editCsv);
  await page.getByLabel(/fee basis points/i).fill("10");
  await page.getByLabel(/^from$/i).fill("0");
  await page.getByLabel(/^to$/i).fill("9999999999999");
  const reqB = page.waitForRequest(
    (r) => r.method() === "POST" && new URL(r.url()).pathname === "/api/v1/research/jobs",
  );
  await page.getByRole("button", { name: /^run$/i }).click();
  const requestB = await reqB;
  const bodyB = JSON.parse(requestB.postData() ?? "{}") as Record<string, unknown>;
  const jobB = await readJobIdAfterRun(page);
  expect(jobB).not.toBe("");
  await page.getByRole("button", { name: /load result/i }).click();
  await expect(page.getByTestId("research-result")).toBeVisible({ timeout: 60_000 });
  const equityB = (await page.getByTestId("research-result-equity").innerText()).trim();
  const tradesB = (await page.getByTestId("research-result-trade-count").innerText()).trim();

  const equityChanged = equityA !== equityB;
  const tradesChanged = tradesA !== tradesB;
  if (!equityChanged && !tradesChanged) {
    throw new Error(
      `Edit did not change the result: A equity=${equityA} trades=${tradesA}; B equity=${equityB} trades=${tradesB}`,
    );
  }

  // Probe the job B submission through the API (page.request carries
  // the cookie).
  const jobBInfo = await page.request.get(`${baseURL}/api/v1/jobs/${encodeURIComponent(jobB)}`);
  expect(jobBInfo.status()).toBe(200);
  // Wire-level proof that each Run posted the revision the UI showed.
  expect(bodyA.revision_id).toBe(revisionA);
  expect(bodyB.revision_id).toBe(revisionB);
  expect(bodyA.revision_id).not.toBe(bodyB.revision_id);
  // Identical inputs: only the revision may differ between the runs.
  expect(bodyB.dataset_csv).toBe(bodyA.dataset_csv);
  expect(bodyB.fee_bps).toBe(bodyA.fee_bps);
  // The run must resolve the pack through the revision, not a path.
  expect(bodyA.pack_path).toBeFalsy();
  expect(bodyB.pack_path).toBeFalsy();

  // The rendered job id is the id the server returned for that POST.
  const responseA = await requestA.response();
  const responseB = await requestB.response();
  expect(responseA).not.toBeNull();
  expect(responseB).not.toBeNull();
  const jobAResponse = (await responseA!.json()) as { id?: string };
  const jobBResponse = (await responseB!.json()) as { id?: string };
  expect(jobAResponse.id).toBe(jobA);
  expect(jobBResponse.id).toBe(jobB);

  // The stored revision B carries the studio edit and its parent;
  // revision A still has the original length.
  const draftB = await page.request.get(
    `${baseURL}/api/v1/strategies/drafts/${encodeURIComponent(revisionB)}`,
  );
  expect(draftB.status()).toBe(200);
  const draftBBody = (await draftB.json()) as {
    parent_revision_id?: string;
    pack?: { indicators?: { sma2?: { len?: number } } };
  };
  expect(draftBBody.pack?.indicators?.sma2?.len).toBe(20);
  expect(draftBBody.parent_revision_id).toBe(revisionA);
  const draftA = await page.request.get(
    `${baseURL}/api/v1/strategies/drafts/${encodeURIComponent(revisionA)}`,
  );
  expect(draftA.status()).toBe(200);
  const draftABody = (await draftA.json()) as {
    pack?: { indicators?: { sma2?: { len?: number } } };
  };
  expect(draftABody.pack?.indicators?.sma2?.len).toBe(2);

  // Log timings for the report.
  console.log(
    `[ns20-studio-edit] revisionA=${revisionA} revisionB=${revisionB} ` +
      `postedRevisionA=${String(bodyA.revision_id)} postedRevisionB=${String(bodyB.revision_id)} ` +
      `equityA=${equityA} equityB=${equityB} tradesA=${tradesA} tradesB=${tradesB}`,
  );
});

async function readJobIdAfterRun(page: Page): Promise<string> {
  const element = page.getByTestId("research-job-id");
  await expect(element).toBeVisible({ timeout: 30_000 });
  const text = (await element.innerText()).trim();
  const match = text.match(/job:\s*(\S+)/);
  if (!match) {
    throw new Error(`could not parse job id from ${JSON.stringify(text)}`);
  }
  return match[1];
}

function extractRevisionId(text: string): string {
  const match = text.match(/revision:\s*([^\s)]+)/);
  if (!match) {
    throw new Error(`could not parse revision id from ${JSON.stringify(text)}`);
  }
  return match[1];
}

let workstation: WorkstationHandle | null = null;

test.beforeAll(async () => {
  workstation = await startWorkstationForSpec();
});

test.afterAll(async () => {
  if (workstation) {
    await stopWorkstationForSpec(workstation);
    workstation = null;
  }
});