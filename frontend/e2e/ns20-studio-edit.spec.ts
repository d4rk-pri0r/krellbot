import {
  test,
  expect,
  type Page,
  type Response,
  type Download,
} from "@playwright/test";
import { createHash } from "node:crypto";
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
 * M2-CE: this spec also enforces the console guard — zero console
 * errors and zero responses with status >= 400 across the whole run,
 * and runs the real-browser Export result proof: the bytes the page
 * downloads match the bytes the backend download endpoint serves,
 * and a second export is byte-equal to the first.
 */

type ConsoleGuard = {
  errors: string[];
  badResponses: { method: string; path: string; status: number }[];
};

function attachConsoleGuard(page: Page): ConsoleGuard {
  const guard: ConsoleGuard = { errors: [], badResponses: [] };
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      guard.errors.push(msg.text());
      console.log(`[ns20-studio-console] error: ${msg.text()}`);
    } else {
      console.log(`[ns20-studio-console] ${msg.type()}: ${msg.text()}`);
    }
  });
  page.on("pageerror", (err) => {
    guard.errors.push(err.message);
    console.log(`[ns20-studio-pageerror] ${err.message}`);
  });
  page.on("response", (response: Response) => {
    const status = response.status();
    if (status >= 400) {
      const req = response.request();
      const path = new URL(response.url()).pathname;
      const method = req.method();
      guard.badResponses.push({ method, path, status });
      console.log(`[ns20-studio-bad-response] ${method} ${path} ${status}`);
    }
  });
  return guard;
}

async function downloadExportBytes(
  page: Page,
): Promise<{ bytes: Uint8Array; download: Download }> {
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: /export result/i }).click();
  const download = await downloadPromise;
  const stream = await download.createReadStream();
  if (!stream) {
    throw new Error("download stream missing");
  }
  const chunks: Buffer[] = [];
  await new Promise<void>((resolve, reject) => {
    stream.on("data", (chunk: Buffer | string) => {
      chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
    });
    stream.on("end", () => resolve());
    stream.on("error", (err: Error) => reject(err));
  });
  return { bytes: new Uint8Array(Buffer.concat(chunks)), download };
}

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
  const guard = attachConsoleGuard(page);
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
  // pollForResult auto-fetches the result on succeeded; wait for
  // the rendered testid instead of clicking "Load result".
  await expect(page.getByTestId("research-result")).toBeVisible({ timeout: 60_000 });
  const equityA = (await page.getByTestId("research-result-equity").innerText()).trim();
  const tradesA = (await page.getByTestId("research-result-trade-count").innerText()).trim();

  // Verify the job actually ran against the saved revision.
  const jobAInfo = await page.request.get(`${baseURL}/api/v1/jobs/${encodeURIComponent(jobA)}`);
  expect(jobAInfo.status()).toBe(200);

  // Real-browser Export result proof for revision A. Click the
  // "Export result" button, capture the download bytes, and compare
  // them to the backend download endpoint. Then run the same
  // revision/dataset/fee a second time and export again to prove
  // byte-equal determinism.
  const backendA = await page.request.get(
    `${baseURL}/api/v1/jobs/${encodeURIComponent(jobA)}/result/download`,
  );
  expect(backendA.status()).toBe(200);
  const backendBytesA = new Uint8Array(await backendA.body());
  const firstDownload = await downloadExportBytes(page);
  const firstSha = createHash("sha256").update(Buffer.from(firstDownload.bytes)).digest("hex");
  console.log(`[m2-export] sha256(revA first download)=${firstSha}`);
  expect(firstDownload.bytes).toEqual(backendBytesA);
  expect(firstDownload.download.suggestedFilename()).toBe(`research-receipt-${jobA}.json`);

  // Run the same revision/dataset/fee a second time. The receipt
  // bytes must be byte-identical to the first run.
  await page.getByLabel(/dataset path/i).fill(editCsv);
  await page.getByLabel(/fee basis points/i).fill("10");
  await page.getByLabel(/^from$/i).fill("0");
  await page.getByLabel(/^to$/i).fill("9999999999999");
  const reqA2 = page.waitForRequest(
    (r) => r.method() === "POST" && new URL(r.url()).pathname === "/api/v1/research/jobs",
  );
  await page.getByRole("button", { name: /^run$/i }).click();
  const requestA2 = await reqA2;
  const bodyA2 = JSON.parse(requestA2.postData() ?? "{}") as Record<string, unknown>;
  expect(bodyA2.revision_id).toBe(bodyA.revision_id);
  await expect(page.getByTestId("research-result")).toBeVisible({ timeout: 60_000 });
  const secondDownload = await downloadExportBytes(page);
  const secondSha = createHash("sha256").update(Buffer.from(secondDownload.bytes)).digest("hex");
  console.log(`[m2-export] sha256(revA second download)=${secondSha}`);
  expect(secondDownload.bytes).toEqual(firstDownload.bytes);

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

  // M2-WRITE: an unchanged save is a typed no-op. Click Save execution
  // before editing anything and capture the wire response. The outcome
  // element must render the "No change" message and the response body
  // must carry outcome: "unchanged" with revision_id == A.
  const unchangedReq = page.waitForRequest(
    (r) =>
      r.method() === "PUT" &&
      new URL(r.url()).pathname === `/api/v1/strategies/drafts/${revisionA}`,
  );
  await page.getByRole("button", { name: /save execution/i }).click();
  const unchangedRequest = await unchangedReq;
  const unchangedResponse = await unchangedRequest.response();
  const unchangedBody = (await unchangedResponse!.json()) as {
    revision_id?: string;
    outcome?: string;
    state?: string;
  };
  expect(unchangedBody.outcome).toBe("unchanged");
  expect(unchangedBody.revision_id).toBe(revisionA);
  await expect(page.getByTestId("studio-save-outcome")).toContainText(
    `No change: revision ${revisionA} kept`,
  );

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
  const createdReq = page.waitForRequest(
    (r) =>
      r.method() === "PUT" &&
      new URL(r.url()).pathname === `/api/v1/strategies/drafts/${revisionA}`,
  );
  await page.getByRole("button", { name: /save execution/i }).click();
  const createdRequest = await createdReq;
  const createdResponse = await createdRequest.response();
  const createdBody = (await createdResponse!.json()) as {
    revision_id?: string;
    outcome?: string;
  };
  expect(createdBody.outcome).toBe("created");
  await expect(page.getByTestId("studio-save-outcome")).toContainText(
    "Saved new revision ",
  );
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
  // pollForResult auto-fetches on succeeded.
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

  // Console guard: zero errors and zero >=400 responses across the
  // whole spec run.
  expect(guard.errors).toEqual([]);
  expect(guard.badResponses).toEqual([]);
  console.log(
    `[ns20-studio-guard] errors=${guard.errors.length} ` +
      `badResponses=${guard.badResponses.length}`,
  );

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