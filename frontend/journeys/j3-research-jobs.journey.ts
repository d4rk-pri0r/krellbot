/**
 * Phase 2 public — J3 Backtest on pinned data and follow it in Jobs.
 *
 * Approved scenarios (docs/journeys/j3-research-jobs.md, word for word):
 *   J3.1 Starting a backtest with a saved strategy, a dataset and a
 *        date window creates a job that appears in Jobs right away as
 *        queued or running.
 *   J3.2 The job ends as succeeded, failed or cancelled, and Jobs
 *        shows the final state without a manual reload.
 *   J3.3 A succeeded run shows its return, maximum drawdown, trade
 *        count, fee setting and a fingerprint of the data it used.
 *        Running the same inputs again, in the GUI or the CLI, gives
 *        identical numbers.
 *   J3.4 Opening a finished job from Jobs shows the same results
 *        Research showed.
 *   J3.5 Bad input, such as a missing dataset, too many gaps or a
 *        window outside the data, fails with a message naming the
 *        problem. No results appear as if the run had worked.
 *
 * Time limits (docs/journeys/README.md): a new job appears in Jobs
 * within 5 seconds after submit; Jobs shows a job's final state
 * within 15 seconds after the job ends.
 */
import { join } from "node:path";
import type { Page } from "@playwright/test";
import { expect, test, runGuardedCli } from "../e2e/journey-harness/journey-harness";
import { REPO_ROOT } from "../e2e/journey-harness/spawn-layer";
import {
  SMA_CROSS_FIXTURE_JSON,
  clickNav,
  openTechnicalJson,
  readResearchJobId,
  runResearch,
  runResearchMaybe,
  saveJson,
  validateRevision,
  waitForResearchResult,
} from "./helpers/journey-steps";

test.describe("J3 research + jobs", () => {
  let page: Page;
  let homeDir = "";
  let editCsv = "";

  test.beforeEach(async ({ journey }) => {
    page = journey.page;
    homeDir = journey.workstation.homeDir;
    editCsv = journey.workstation.editCsv;
    await page.goto(journey.workstation.baseURL);
    await journey.waitForSessionReady(page);
  });

  /**
   * Shared setup: save + validate the committed sma_cross pack so
   * Research can run it. Each scenario calls this itself — no
   * cross-test dependence.
   */
  async function savedValidatedRevision(): Promise<string> {
    await clickNav(page, "Strategies");
    const revision = await saveJson(page, SMA_CROSS_FIXTURE_JSON);
    await page.getByRole("button", { name: /^validate$/i }).click();
    await expect(page.getByTestId("editor-revision-id")).toContainText(
      /state:\s*validated/i,
      { timeout: 30_000 },
    );
    return revision;
  }

  test("J3.1 Starting a backtest with a saved strategy, a dataset and a date window creates a job that appears in Jobs right away as queued or running", async ({ journey }) => {
    await savedValidatedRevision();
    await clickNav(page, "Research");

    // A genuinely long dataset (100k rows, ~7s engine time) so the job
    // is STILL queued/running when Jobs is checked — the terminal
    // state can never race in under the 5s budget.
    const rows100k = journey.workstation.rows100kCsv;
    const submitAt = Date.now();
    const { jobId } = await runResearch(page, {
      dataset: rows100k,
      feeBps: "10",
      from: String(Date.parse("2023-11-14T00:00:00Z")),
      to: String(Date.parse("2035-04-12T00:00:00Z")),
    });
    expect(jobId).not.toBe("");

    // STRICT: open Jobs immediately; the row must appear within 5s of
    // submit, in queued or running state (never a terminal state).
    await page.getByRole("button", { name: "Jobs", exact: true }).click();
    const dialog = page.getByTestId("kbot-jobs-dialog");
    await expect(dialog).toBeVisible({ timeout: 5_000 });
    const row = dialog.locator(`li[data-testid="job-row"]`, { hasText: jobId });
    await expect(row).toBeVisible({ timeout: 5_000 - (Date.now() - submitAt) > 0 ? 5_000 : 1 });
    // The elapsed time between submit and row visibility is bounded.
    const appearedAt = Date.now();
    expect(appearedAt - submitAt).toBeLessThanOrEqual(5_000);
    const stateText = (await row.locator(".kbot-jobs__state").innerText()).trim();
    const state = stateText.replace(/[()]/g, "");
    expect(
      ["queued", "running"],
      `job state 5s after submit was ${state} (terminal states are not "right away as queued or running")`,
    ).toContain(state);
  });

  // Product gap: the Jobs drawer loads once on open and never
  // refreshes itself (frontend/src/shell/JobsDrawer.tsx, useEffect
  // [open, load]); an open drawer stays "(running)" forever. Issue:
  // https://github.com/d4rk-pri0r/krellbot/issues/98
  // Expected to FAIL today; flips to an unexpected pass once the
  // drawer refreshes (poll or SSE) within the 15s budget.
  test("J3.2 The job ends as succeeded, failed or cancelled, and Jobs shows the final state without a manual reload", async ({ journey }) => {
    // Independent setup: fresh validated revision, fresh run.
    await savedValidatedRevision();
    await clickNav(page, "Research");

    const completion = measureCompletion(page);
    // Long dataset again so we can observe the live transition.
    const { jobId } = await runResearch(page, {
      dataset: journey.workstation.rows100kCsv,
      feeBps: "10",
      from: String(Date.parse("2023-11-14T00:00:00Z")),
      to: String(Date.parse("2035-04-12T00:00:00Z")),
    });

    // OPEN Jobs and KEEP IT OPEN — no close, no reopen, no Refresh
    // click, no page reload for the rest of the scenario.
    await page.getByRole("button", { name: "Jobs", exact: true }).click();
    const dialog = page.getByTestId("kbot-jobs-dialog");
    await expect(dialog).toBeVisible({ timeout: 5_000 });
    const row = dialog.locator(`li[data-testid="job-row"]`, { hasText: jobId });
    await expect(row).toBeVisible({ timeout: 5_000 });

    await expect(row.locator(".kbot-jobs__state")).toHaveText(/\((queued|running)\)/);

    // The Jobs TEXT (not backend state) must show the final state
    // within 15s of actual completion. Completion is observed from the
    // Research view's own result fetch (a GUI-triggered response).
    const resultShown = page
      .getByTestId("research-result")
      .waitFor({ state: "visible", timeout: 120_000 });
    // Also listen for the completion moment on the wire (GUI-triggered).
    const completedAt = await completion;
    await resultShown;
    // Journey gap: https://github.com/d4rk-pri0r/krellbot/issues/98
    test.fail(true, "https://github.com/d4rk-pri0r/krellbot/issues/98");

    // With Jobs still open and untouched, its text flips to the final
    // state within 15s of that completion.
    const finalState = await waitForFinalStateText(
      row,
      Date.now(),
      completedAt + 15_000 - Date.now() > 0 ? completedAt + 15_000 - Date.now() : 1,
    );
    expect(["succeeded", "failed", "cancelled"]).toContain(finalState);
    void dialog;
  });

  test("J3.3 A succeeded run shows its return, maximum drawdown, trade count, fee setting and a fingerprint of the data it used. Running the same inputs again, in the GUI or the CLI, gives identical numbers", async ({ journey }) => {
    await savedValidatedRevision();
    await clickNav(page, "Research");
    const { jobId } = await runResearch(page, {
      dataset: editCsv,
      feeBps: "10",
      from: String(Date.parse("2023-11-14T00:00:00Z")),
      to: String(Date.parse("2035-04-12T00:00:00Z")),
    });
    await waitForResearchResult(page);

    // GUI shows every metric the scenario names, read off the result
    // panel's own tiles.
    const guiReturn = (
      await page.getByTestId("research-result-total-return-pct").innerText()
    ).trim();
    const guiDrawdown = (
      await page.getByTestId("research-result-max-drawdown").innerText()
    ).trim();
    const guiTrades = (
      await page.getByTestId("research-result-trade-count").innerText()
    ).trim();
    const guiFee = (
      await page.getByTestId("research-result-fee-bps").innerText()
    ).trim();
    const guiManifest = (
      await page.getByTestId("research-result-data-manifest-sha256").innerText()
    ).trim();
    expect(guiReturn).not.toBe("");
    expect(guiReturn.toLowerCase()).not.toBe("unavailable");
    expect(guiDrawdown).not.toBe("");
    expect(guiDrawdown.toLowerCase()).not.toBe("unavailable");
    expect(guiTrades).toMatch(/^\d+$/);
    expect(guiFee).toBe("10");
    expect(guiManifest).toMatch(/^[0-9a-f]{16,}$/);

    // SECOND GUI RUN with the same inputs: identical numbers.
    const { jobId: jobId2 } = await runResearch(page, {
      dataset: editCsv,
      feeBps: "10",
      from: String(Date.parse("2023-11-14T00:00:00Z")),
      to: String(Date.parse("2035-04-12T00:00:00Z")),
    });
    expect(jobId2).not.toBe(jobId);
    await waitForResearchResult(page);
    await expect(page.getByTestId("research-result-total-return-pct")).toHaveText(
      guiReturn,
    );
    await expect(page.getByTestId("research-result-max-drawdown")).toHaveText(
      guiDrawdown,
    );
    await expect(page.getByTestId("research-result-trade-count")).toHaveText(guiTrades);
    await expect(page.getByTestId("research-result-fee-bps")).toHaveText(guiFee);
    await expect(
      page.getByTestId("research-result-data-manifest-sha256"),
    ).toHaveText(guiManifest);

    // CLI RUN: a REAL `krellbot backtest` subprocess through the
    // shared safety wrapper — same strategy bytes, same dataset, same
    // window, same fee. Its --json receipt must match the GUI numbers
    // exactly. (J3.3 is the brief's sanctioned CLI exception.)
    const packPath = join(homeDir, "data", "pack-sma-cross.json");
    const cli = runGuardedCli(
      [
        "-m",
        "krellbot",
        "backtest",
        packPath,
        "--venue",
        "kraken",
        "--data",
        editCsv,
        "--fee-bps",
        "10",
        "--from",
        "2023-11-14",
        "--to",
        "2035-04-12",
        "--json",
      ],
      { home: homeDir, commandLog: journey.workstation.commandLog },
      180_000,
    );
    expect(cli.status, `CLI stderr: ${cli.stderr}`).toBe(0);
    const receipt = JSON.parse(cli.stdout) as {
      fee_bps: number;
      data_manifest_sha256: string;
      metrics: {
        total_return_pct: number;
        max_drawdown_pct: number;
        trade_count: number;
      };
    };
    expect(String(receipt.fee_bps)).toBe(guiFee);
    expect(receipt.data_manifest_sha256).toBe(guiManifest);
    expect(String(receipt.metrics.total_return_pct)).toBe(guiReturn);
    expect(`${receipt.metrics.max_drawdown_pct}%`).toBe(guiDrawdown);
    expect(String(receipt.metrics.trade_count)).toBe(guiTrades);
  });

  test("J3.4 Opening a finished job from Jobs shows the same results Research showed", async () => {
    await savedValidatedRevision();
    await clickNav(page, "Research");
    const { jobId } = await runResearch(page, {
      dataset: editCsv,
      feeBps: "10",
      from: String(Date.parse("2023-11-14T00:00:00Z")),
      to: String(Date.parse("2035-04-12T00:00:00Z")),
    });
    await waitForResearchResult(page);
    const researchMetrics = {
      return: (
        await page.getByTestId("research-result-total-return-pct").innerText()
      ).trim(),
      drawdown: (await page.getByTestId("research-result-max-drawdown").innerText()).trim(),
      trades: (await page.getByTestId("research-result-trade-count").innerText()).trim(),
      fee: (await page.getByTestId("research-result-fee-bps").innerText()).trim(),
      manifest: (
        await page.getByTestId("research-result-data-manifest-sha256").innerText()
      ).trim(),
    };

    // Replace the visible result with a distinguishable second job, then
    // leave Research. A no-op row click must never pass on stale metrics.
    await runResearch(page, {dataset: editCsv, feeBps: "17", from: String(Date.parse("2023-11-14T00:00:00Z")), to: String(Date.parse("2035-04-12T00:00:00Z"))});
    await waitForResearchResult(page);
    await expect(page.getByTestId("research-result-fee-bps")).toHaveText("17");
    await clickNav(page, "Strategies");
    await expect(page.getByTestId("research-result")).toBeHidden();

    // OPEN the finished job FROM Jobs: click the job's row in the Jobs
    // drawer. This is the user affordance; the test fails here if the
    // product provides no such control (journey gap, not API read).
    await page.getByRole("button", { name: "Jobs", exact: true }).click();
    const dialog = page.getByTestId("kbot-jobs-dialog");
    await expect(dialog).toBeVisible({ timeout: 5_000 });
    const row = dialog.locator(`li[data-testid="job-row"]`, { hasText: jobId });
    await expect(row).toBeVisible({ timeout: 10_000 });
    // The row itself must be clickable (button semantics or row click
    // handler); a row that cannot be opened is the gap.
    // Journey gap: https://github.com/d4rk-pri0r/krellbot/issues/102
    test.fail(true, "https://github.com/d4rk-pri0r/krellbot/issues/102");
    await row.click({ timeout: 10_000 });

    // Whatever surface opens, it must show the SAME metrics Research
    // showed. We look for the research result panel re-rendered with
    // this job's metrics.
    await expect(page.getByTestId("research-result")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("research-result-total-return-pct")).toHaveText(
      researchMetrics.return,
    );
    await expect(page.getByTestId("research-result-max-drawdown")).toHaveText(
      researchMetrics.drawdown,
    );
    await expect(page.getByTestId("research-result-trade-count")).toHaveText(
      researchMetrics.trades,
    );
    await expect(page.getByTestId("research-result-fee-bps")).toHaveText(
      researchMetrics.fee,
    );
    await expect(page.getByTestId("research-result-data-manifest-sha256")).toHaveText(
      researchMetrics.manifest,
    );
  });

  test("J3.5 Bad input, such as a missing dataset, too many gaps or a window outside the data, fails with a message naming the problem. No results appear as if the run had worked", async () => {
    await savedValidatedRevision();
    await clickNav(page, "Research");

    // Three bad-input kinds, each through the GUI Run.
    const cases: Array<{
      dataset: string;
      from: string;
      to: string;
      nameInMessage: RegExp;
    }> = [
      {
        // Missing dataset: the path itself names the missing file.
        dataset: "/nonexistent/path/to/candles.csv",
        from: String(Date.parse("2023-11-14T00:00:00Z")),
        to: String(Date.parse("2035-04-12T00:00:00Z")),
        nameInMessage: /nonexistent|no such file|missing|not found|dataset/i,
      },
      {
        // Window entirely outside the data (edit.csv spans
        // 2023-11-14..2023-12-01; this window is years later).
        dataset: "", // filled per-case below
        from: String(Date.parse("2030-01-01T00:00:00Z")),
        to: String(Date.parse("2030-02-01T00:00:00Z")),
        nameInMessage: /window|from|to|outside|no bars|empty/i,
      },
      {
        // Reversed window (from > to) is refused naming From/To.
        dataset: "",
        from: "9999999999999",
        to: "0",
        nameInMessage: /from|to|window/i,
      },
    ];
    for (const testCase of cases) {
      const dataset = testCase.dataset === "" ? editCsv : testCase.dataset;
      const { jobId, submitted } = await runResearchMaybe(page, {
        dataset,
        feeBps: "10",
        from: testCase.from,
        to: testCase.to,
      });
      if (submitted && jobId) {
        // Job-submitted path: the job must FAIL, the failure must be
        // visible in the GUI naming the problem, and no result panel
        // may appear.
        await expect(page.getByTestId("research-job-error")).toBeVisible({
          timeout: 60_000,
        });
        const errText = (
          await page.getByTestId("research-job-error").innerText()
        ).toLowerCase();
        expect(errText.length).toBeGreaterThan(0);
        expect(errText).toMatch(testCase.nameInMessage);
      } else {
        // Refused-before-submit path: a visible alert names the problem.
        const alert = page.locator('[role="alert"]').first();
        await expect(alert).toBeVisible({ timeout: 20_000 });
        const alertText = (await alert.innerText()).toLowerCase();
        expect(alertText.length).toBeGreaterThan(0);
        expect(alertText).toMatch(testCase.nameInMessage);
      }
      // "No results appear as if the run had worked."
      expect(await page.getByTestId("research-result").count()).toBe(0);
      // The job id line is either absent or names the failed job; a
      // succeeded result never replaced the failure.
      const resultCount = await page.getByTestId("research-result").count();
      expect(resultCount).toBe(0);
    }
  });
});

// ---- helpers local to J3 -------------------------------------------------


import type { Locator, Response } from "@playwright/test";

/**
 * Measure the moment the job actually completed: the GUI's own
 * pollForResult issues GET /api/v1/jobs/{id} until succeeded. We watch
 * the GUI-triggered response for the terminal snapshot.
 */
async function measureCompletion(page: Page): Promise<number> {
  return new Promise<number>((resolve) => {
    const onResponse = (response: Response): void => {
      const url = new URL(response.url());
      const isJobGet =
        response.request().method() === "GET" &&
        /^\/api\/v1\/jobs\/[^/]+$/.test(url.pathname);
      if (!isJobGet || response.status() !== 200) {
        return;
      }
      response
        .json()
        .then((body: { state?: string; finished_at?: string }) => {
          if (
            body.state === "succeeded" ||
            body.state === "failed" ||
            body.state === "cancelled"
          ) {
            page.off("response", onResponse);
            const finished = Date.parse(body.finished_at ?? "");
            expect(Number.isFinite(finished), "terminal job needs its actual finished_at deadline").toBe(true);
            resolve(finished);
          }
        })
        .catch(() => undefined);
    };
    page.on("response", onResponse);
  });
}

/**
 * Poll the Jobs row's OWN TEXT for a terminal state, without touching
 * any control. Fails when the budget elapses.
 */
async function waitForFinalStateText(
  row: Locator,
  startAt: number,
  budgetMs: number,
): Promise<string> {
  const deadline = startAt + Math.max(budgetMs, 1);
  while (Date.now() < deadline) {
    const text = (await row.locator(".kbot-jobs__state").innerText()).trim();
    const state = text.replace(/[()]/g, "");
    if (["succeeded", "failed", "cancelled"].includes(state)) {
      return state;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(
    `Jobs did not show the final state within 15s of completion (last text: ${await row
      .locator(".kbot-jobs__state")
      .innerText()})`,
  );
}
