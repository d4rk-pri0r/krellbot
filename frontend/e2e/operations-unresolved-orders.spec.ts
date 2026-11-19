import {
  test,
  expect,
  type Page,
  type Response,
} from "@playwright/test";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import {
  startWorkstationForSpec,
  stopWorkstationForSpec,
  type WorkstationHandle,
} from "./workstation-harness";
import {
  clickNav,
  seedDismissedFirstRunWizard,
  skipFirstRunWizard,
} from "../journeys/helpers/journey-steps";

/**
 * M1.9 — Operations shows every unresolved order.
 *
 * Proves the empty list says so plainly, then seeds awaiting-reconcile
 * ledger rows and refreshes so each order shows client order ID, age,
 * and last lookup result. KRELL-SIGNAL-20261010.
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
    }
  });
  page.on("pageerror", (err) => {
    guard.errors.push(err.message);
  });
  page.on("response", (response: Response) => {
    const status = response.status();
    if (status >= 400) {
      const req = response.request();
      const path = new URL(response.url()).pathname;
      guard.badResponses.push({ method: req.method(), path, status });
    }
  });
  return guard;
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const REPO_ROOT = resolve(__dirname, "..", "..");

function seedUnresolved(home: string): void {
  const result = spawnSync(
    "uv",
    [
      "run",
      "--project",
      REPO_ROOT,
      "python",
      "frontend/e2e/unresolved_orders_seed.py",
      home,
    ],
    { cwd: REPO_ROOT, encoding: "utf8" },
  );
  if (result.status !== 0) {
    throw new Error(
      `unresolved_orders_seed.py failed (${result.status}): ${result.stderr ?? ""}`,
    );
  }
}

async function waitForSessionReady(page: Page): Promise<void> {
  await skipFirstRunWizard(page);
  await page.waitForFunction(
    () => {
      const root = document.querySelector('[data-testid="kbot-shell"]');
      return root?.getAttribute("data-bootstrap-done") === "1";
    },
    undefined,
    { timeout: 15_000 },
  );
}

test("Operations shows unresolved orders with client order ID, age, and last lookup", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const guard = attachConsoleGuard(page);
  const baseURL = workstation!.baseURL.replace(/\/$/, "");
  await seedDismissedFirstRunWizard(page);
  await page.goto(baseURL + "/");
  await waitForSessionReady(page);
  await clickNav(page, "Operations");
  await expect(page.getByTestId("operations-view")).toBeVisible();

  // M18.4: Unresolved orders lives under Advanced — expand before asserting.
  const unresolvedToggle = page.getByTestId("ops-unresolved-orders-panel-toggle");
  await expect(unresolvedToggle).toBeVisible();
  if ((await unresolvedToggle.getAttribute("aria-expanded")) !== "true") {
    await unresolvedToggle.click();
  }
  await expect(unresolvedToggle).toHaveAttribute("aria-expanded", "true");

  const panel = page.getByTestId("ops-unresolved-orders");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("ops-unresolved-empty")).toHaveText("No unresolved orders.");

  seedUnresolved(workstation!.homeDir);
  await page.getByTestId("ops-unresolved-refresh").click();

  await expect(page.getByTestId("ops-unresolved-empty")).toHaveCount(0);

  const absent = page.getByTestId("ops-unresolved-row-coid-e2e-absent");
  await expect(absent).toBeVisible();
  await expect(absent).toContainText("coid-e2e-absent");
  await expect(absent).toContainText("absent");
  await expect(absent.locator(".kbot-ops__unresolved-age")).not.toHaveText("—");

  const none = page.getByTestId("ops-unresolved-row-coid-e2e-none");
  await expect(none).toBeVisible();
  await expect(none).toContainText("coid-e2e-none");
  await expect(none).toContainText("none");
  await expect(none.locator(".kbot-ops__unresolved-age")).not.toHaveText("—");

  expect(guard.errors).toEqual([]);
  expect(
    guard.badResponses.filter((r) => r.path.includes("/operations/unresolved-orders")),
  ).toEqual([]);
});

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
