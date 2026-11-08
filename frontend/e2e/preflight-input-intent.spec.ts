import { test, expect, chromium } from "@playwright/test";
import { startJourneyWorkstation, sanitizedJourneyEnv } from "./journey-harness/spawn-layer";
import { attachNetworkGuard, assertNoOffLoopback } from "./journey-harness/network-guard";
import { waitForSessionReady } from "./journey-harness/journey-harness";
import { clickNav } from "../journeys/helpers/journey-steps";

// The ordinary journey command guard rejects every live.* name, including this
// dry-run. This test uses an explicit sandbox-preflight-only command allowlist;
// no live-mode payload or other state-changing command can leave the browser.
for (const width of [1280, 390]) {
  test(`sandbox preflight edits invalidate old backend verdicts at ${width}px`, async () => {
    const workstation = await startJourneyWorkstation();
    const env = Object.fromEntries(Object.entries(sanitizedJourneyEnv(workstation.homeDir)).filter((entry): entry is [string, string] => entry[1] !== undefined));
    const browser = await chromium.launch({ headless: true, env });
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const network = await attachNetworkGuard(page);
    const refused: string[] = [];
    const submitted: Array<{ account_id: string; revision_id: string; mode: string }> = [];
    let delay = false;
    let ready!: () => void;
    let release!: () => void;
    const prepared = new Promise<void>((resolve) => { ready = resolve; });
    const gate = new Promise<void>((resolve) => { release = resolve; });
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      if (!["POST", "PUT", "PATCH", "DELETE"].includes(request.method())) return route.fallback();
      if (new URL(request.url()).pathname === "/api/v1/session/bootstrap") return route.fallback();
      const body = request.postDataJSON();
      if (new URL(request.url()).pathname !== "/api/v1/commands" || body?.command !== "live.preflight" || body.payload?.mode !== "sandbox") {
        refused.push(body?.command ?? "unknown mutation");
        return route.abort("blockedbyclient");
      }
      submitted.push(body.payload);
      const response = await route.fetch({ maxRetries: 0 });
      expect(response.status()).toBe(200);
      if (delay) {
        delay = false;
        ready();
        await gate;
      }
      await route.fulfill({ response });
    });
    try {
      await page.goto(workstation.baseURL);
      await waitForSessionReady(page);
      await clickNav(page, "Deploy");
      const account = page.getByTestId("live-preflight-account");
      const revision = page.getByTestId("live-preflight-revision");
      const submit = page.getByTestId("live-preflight-submit");
      const result = page.getByTestId("live-preflight-result");
      await account.fill("synthetic-account-A");
      await revision.fill("synthetic-revision-one");
      await submit.click();
      await expect(result).toBeVisible();
      await account.fill("synthetic-account-B");
      await expect(result).toHaveCount(0);
      expect(submitted).toHaveLength(1);
      delay = true;
      await submit.click();
      await prepared;
      await revision.fill("synthetic-revision-two");
      await expect(submit).toBeEnabled();
      const delivered = page.waitForResponse((r) => r.url().endsWith("/api/v1/commands"));
      release();
      await delivered;
      await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      await expect(result).toHaveCount(0);
      await expect(page.getByTestId("live-preflight-error")).toHaveCount(0);
      expect(submitted).toHaveLength(2);
      await submit.click();
      await expect(result).toBeVisible();
      expect(submitted).toHaveLength(3);
      expect(submitted[2]).toEqual({ account_id: "synthetic-account-B", revision_id: "synthetic-revision-two", mode: "sandbox" });
      expect(refused).toEqual([]);
      assertNoOffLoopback(network);
      workstation.commandLog.assertAll();
    } finally {
      release();
      await browser.close();
      await workstation.stop();
    }
  });
}
