import {
  test,
  expect,
  type Page,
  type Response,
} from "@playwright/test";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";
import {
  startWorkstationForSpec,
  stopWorkstationForSpec,
  type WorkstationHandle,
} from "./workstation-harness";

/**
 * M3-GUI operations spec.
 *
 * End-to-end proof that the live-operations surface renders the disabled
 * banner, refuses promotion with the typed refusal code, drives
 * pause/resume on a paper row, engages the kill switch, observes the
 * kill_switch alert, refuses a second promotion with the kill-engaged
 * code, acknowledges an alert, and survives a page reload (ack
 * persists, and operator commands still work through CSRF
 * recovery). The console guard mirrors ``ns20-studio-edit.spec.ts``.
 *
 * The spec depends on the per-spec workstation harness, which already
 * sets ``KRELLBOT_ENABLE_LIVE=0`` and a fake keyring. The spec runs
 * ``m3_seed.py`` through ``spawnSync`` against the per-spec home to
 * plant a paper pack and two live_refused tick records.
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
      console.log(`[m3-operations-console] error: ${msg.text()}`);
    } else {
      console.log(`[m3-operations-console] ${msg.type()}: ${msg.text()}`);
    }
  });
  page.on("pageerror", (err) => {
    guard.errors.push(err.message);
    console.log(`[m3-operations-pageerror] ${err.message}`);
  });
  page.on("response", (response: Response) => {
    const status = response.status();
    if (status >= 400) {
      const req = response.request();
      const path = new URL(response.url()).pathname;
      const method = req.method();
      guard.badResponses.push({ method, path, status });
      console.log(`[m3-operations-bad-response] ${method} ${path} ${status}`);
    }
  });
  return guard;
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const REPO_ROOT = resolve(__dirname, "..", "..");

function seedHome(home: string): void {
  const result = spawnSync(
    "uv",
    [
      "run",
      "--project",
      REPO_ROOT,
      "python",
      "frontend/e2e/m3_seed.py",
      home,
    ],
    { cwd: REPO_ROOT, encoding: "utf8" },
  );
  if (result.status !== 0) {
    throw new Error(
      `m3_seed.py failed (${result.status}): ${result.stderr ?? ""}`,
    );
  }
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

test("M3-GUI operations surface refuses promotion, drives pause/resume, and engages kill", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const guard = attachConsoleGuard(page);
  const baseURL = workstation!.baseURL.replace(/\/$/, "");
  await page.goto(baseURL + "/");
  await expect(page.locator('meta[name="krellbot-bootstrap"]')).toHaveCount(0, {
    timeout: 5_000,
  });
  await waitForSessionReady(page);

  await page.getByRole("button", { name: "Operations" }).click();
  const opsView = page.getByTestId("operations-view");
  await expect(opsView).toBeVisible();

  const liveStatus = page.getByTestId("ops-live-status");
  await expect(liveStatus).toContainText(
    "Live trading is disabled in this build (KRELLBOT_ENABLE_LIVE is not 1).",
  );
  await expect(liveStatus).toContainText("Promotion to live is owner-deferred.");

  const promoteCodes: string[] = [];
  page.on("response", async (resp) => {
    if (
      resp.request().method() === "POST" &&
      new URL(resp.url()).pathname === "/api/v1/commands"
    ) {
      try {
        const req = resp.request();
        const body = req.postData() ?? "";
        if (body.includes('"live.promote"')) {
          const text = await resp.text();
          const parsed = JSON.parse(text) as { code?: string; ok?: boolean };
          if (parsed.code) {
            promoteCodes.push(parsed.code);
          }
        }
      } catch {
        // ignore
      }
    }
  });

  const promote = page.getByTestId("ops-promote-kraken-SUIUSD");
  await expect(promote).toBeVisible();
  const promoteRespPromise = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      new URL(r.url()).pathname === "/api/v1/commands" &&
      (r.request().postData() ?? "").includes('"live.promote"'),
  );
  await promote.click();
  const promoteResp = await promoteRespPromise;
  expect(promoteResp.status()).toBe(200);
  const promoteBody = (await promoteResp.json()) as { ok: boolean; code: string };
  expect(promoteBody.ok).toBe(false);
  const promoteResult = page.getByTestId("ops-promote-result-kraken-SUIUSD");
  await expect(promoteResult).toContainText(/Refused: live_disabled/);

  await page.getByTestId("ops-pause-kraken-SUIUSD").click();
  await expect(
    page.getByTestId("ops-deployment-kraken-SUIUSD"),
  ).toContainText(/paused/);

  await page.getByTestId("ops-resume-kraken-SUIUSD").click();
  await expect(
    page.getByTestId("ops-deployment-kraken-SUIUSD"),
  ).toContainText(/active/);

  const configPath = join(workstation!.homeDir, "config.json");
  expect(existsSync(configPath)).toBe(true);
  const cfgBefore = readFileSync(configPath);

  const reason = page.getByTestId("ops-kill-reason");
  await reason.fill("playwright-engage");
  await page.getByTestId("ops-kill-engage").click();
  await expect(page.getByTestId("ops-kill")).toContainText(
    "Kill switch: engaged — playwright-engage",
  );

  const killSwitchAlert = page
    .locator('[data-testid="ops-alerts"]')
    .locator('[data-testid^="ops-alert-"]')
    .filter({ hasText: "kill_switch" });
  await expect(killSwitchAlert.first()).toBeVisible();

  const promoteResp2 = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      new URL(r.url()).pathname === "/api/v1/commands" &&
      (r.request().postData() ?? "").includes('"live.promote"'),
  );
  await page.getByTestId("ops-promote-kraken-SUIUSD").click();
  const promoteResp2Body = await promoteResp2;
  expect(promoteResp2Body.status()).toBe(200);
  const promoteBody2 = (await promoteResp2Body.json()) as {
    ok: boolean;
    code: string;
  };
  expect(promoteBody2.ok).toBe(false);
  await expect(
    page.getByTestId("ops-promote-result-kraken-SUIUSD"),
  ).toContainText(/Refused: kill_switch_engaged/);

  expect(readFileSync(configPath)).toEqual(cfgBefore);

  await page.getByTestId("ops-kill-release").click();
  await expect(page.getByTestId("ops-kill")).toContainText("Kill switch: released");

  // Acknowledge the live_refused alert (×2).
  const liveRefusedAlert = page
    .locator('[data-testid="ops-alerts"]')
    .locator('[data-testid^="ops-alert-"]')
    .filter({ hasText: "live_refused" })
    .first();
  const liveRefusedId = await liveRefusedAlert.getAttribute("data-testid");
  expect(liveRefusedId).toBeTruthy();
  const ackId = liveRefusedId?.replace("ops-alert-", "");
  expect(ackId).toBeTruthy();
  await page.getByTestId(`ops-alert-ack-${ackId}`).click();
  await expect(
    page.getByTestId(`ops-alert-${ackId}`),
  ).toContainText(/acknowledged/);

  // Reload the page; the ack persists.
  await page.reload();
  await waitForSessionReady(page);
  await page.getByRole("button", { name: "Operations" }).click();
  await expect(
    page.getByTestId(`ops-alert-${ackId}`),
  ).toContainText(/acknowledged/);

  // After the reload the bootstrap meta tag is gone (one-time token),
  // so the shell must have recovered the CSRF over
  // GET /api/v1/session/csrf for these state changes to succeed.
  await page.getByTestId("ops-pause-kraken-SUIUSD").click();
  await expect(
    page.getByTestId("ops-deployment-kraken-SUIUSD"),
  ).toContainText(/paused/);

  await page.getByTestId("ops-kill-reason").fill("after-reload");
  await page.getByTestId("ops-kill-engage").click();
  await expect(page.getByTestId("ops-kill")).toContainText(
    "Kill switch: engaged — after-reload",
  );

  await page.getByTestId("ops-kill-release").click();
  await expect(page.getByTestId("ops-kill")).toContainText("Kill switch: released");

  expect(guard.errors).toEqual([]);
  expect(guard.badResponses).toEqual([]);
  console.log(
    `[m3-operations] errors=${guard.errors.length} badResponses=${guard.badResponses.length} ` +
      `promoteCodes=${JSON.stringify(promoteCodes)}`,
  );
});

let workstation: WorkstationHandle | null = null;

test.beforeAll(async () => {
  workstation = await startWorkstationForSpec();
  seedHome(workstation.homeDir);
});

test.afterAll(async () => {
  if (workstation) {
    await stopWorkstationForSpec(workstation);
    workstation = null;
  }
});