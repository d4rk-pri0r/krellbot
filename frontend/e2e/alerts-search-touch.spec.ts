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

/**
 * Alerts Search touch-target geometry regression (issue179).
 *
 * Real production app against the per-spec workstation harness (real
 * session/CSRF, ``KRELLBOT_ENABLE_LIVE=0``, fake keyring). No CSS
 * mocks, no backend/HTTP mocks, no ``getBoundingClientRect`` stubs:
 * geometry is read from the rendered production bundle in Chromium at
 * five real viewport sizes.
 *
 * Contract (docs/design-system.md, KRELL-SIGNAL-20261010): narrow
 * layouts (<=640px) keep ordinary controls at >=44px touch targets,
 * while wider viewports keep the compact desktop density (34px band,
 * explicitly NOT forced to 44px).
 *
 * The seeded journal records come from ``m3_seed.py`` (persisted
 * refusal records only; no orders are executed).
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
      console.log(`[alerts-touch-console] error: ${msg.text()}`);
    }
  });
  page.on("pageerror", (err) => {
    guard.errors.push(err.message);
    console.log(`[alerts-touch-pageerror] ${err.message}`);
  });
  page.on("response", (response: Response) => {
    const status = response.status();
    if (status >= 400) {
      const req = response.request();
      const path = new URL(response.url()).pathname;
      const method = req.method();
      guard.badResponses.push({ method, path, status });
      console.log(`[alerts-touch-bad-response] ${method} ${path} ${status}`);
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

type QueryGeometry = {
  viewportWidth: number;
  viewportHeight: number;
  rect: { left: number; right: number; top: number; width: number; height: number };
  scrollWidth: number;
  innerWidth: number;
};

async function measureQuery(page: Page): Promise<QueryGeometry> {
  return page.getByTestId("ops-alerts-filter-query").evaluate((el) => {
    const r = el.getBoundingClientRect();
    return {
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      rect: {
        left: r.left,
        right: r.right,
        top: r.top,
        width: r.width,
        height: r.height,
      },
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    };
  });
}

async function settle(page: Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      }),
  );
}

const VIEWPORTS: { width: number; height: number }[] = [
  { width: 320, height: 740 },
  { width: 390, height: 844 },
  { width: 640, height: 900 },
  { width: 768, height: 1024 },
  { width: 1440, height: 900 },
];

test("Operations Alerts Search keeps >=44px touch targets <=640px and compact density above", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const guard = attachConsoleGuard(page);
  const baseURL = workstation!.baseURL.replace(/\/$/, "");
  await page.goto(baseURL + "/");
  await waitForSessionReady(page);

  await page.getByRole("navigation", { name: "Workstation navigation" })
    .getByRole("button", { name: "Operations", exact: true }).click();
  await expect(page.getByTestId("operations-view")).toBeVisible();

  const query = page.getByTestId("ops-alerts-filter-query");
  const severity = page.getByTestId("ops-alerts-filter-severity");
  await expect(query).toBeVisible();
  await expect(severity).toBeVisible();
  await expect(page.getByTestId("ops-refresh")).toBeEnabled();

  // Native production controls only.
  expect(await query.evaluate((el) => el.tagName)).toBe("INPUT");
  expect(await severity.evaluate((el) => el.tagName)).toBe("SELECT");

  // The seeded refusal alert gives the filters real rows to filter.
  const alertRow = page
    .locator('[data-testid="ops-alerts"]')
    .locator('[data-testid^="ops-alert-"]')
    .filter({ hasText: "Live refused" })
    .first();
  await expect(alertRow).toBeVisible();

  for (const { width, height } of VIEWPORTS) {
    await page.setViewportSize({ width, height });
    await settle(page);
    const geometry = await measureQuery(page);

    // Containment: the input stays inside the page at every width and
    // never widens the document past the viewport.
    expect(geometry.rect.left).toBeGreaterThanOrEqual(0);
    expect(geometry.rect.right).toBeLessThanOrEqual(geometry.innerWidth);
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.innerWidth);

    console.log(
      `[alerts-touch] ${width}x${height}: search height=${geometry.rect.height}px`,
    );
    if (width <= 640) {
      // Approved mobile minimum: a real >=44px touch target.
      expect(
        geometry.rect.height,
        `search height at ${width}px must be >=44px`,
      ).toBeGreaterThanOrEqual(44);
    } else {
      // Desktop/tablet keeps the compact density; do not impose 44px.
      expect(
        geometry.rect.height,
        `search height at ${width}px must stay compact (<44px)`,
      ).toBeGreaterThanOrEqual(34);
      expect(geometry.rect.height).toBeLessThan(44);
    }
  }

  // ---- ordinary interaction with the production native controls ----

  // Reset to the mobile width where the fix matters, then type a query.
  await page.setViewportSize({ width: 390, height: 844 });
  await settle(page);
  await query.click();
  await query.pressSequentially("live");
  await expect(query).toHaveValue("live");
  await expect(alertRow).toBeVisible();

  // A query that matches nothing shows the scoped empty state.
  await query.fill("no-such-code");
  await expect(page.getByTestId("ops-alerts-empty")).toBeVisible();

  // Severity selection through the native select.
  await expect(alertRow).toBeHidden();
  await severity.selectOption("warning");
  await expect(severity).toHaveValue("warning");
  await expect(page.getByTestId("ops-alerts-empty")).toBeVisible();

  // Clear restores the unfiltered rows.
  const clear = page.getByTestId("ops-alerts-filter-clear");
  await expect(clear).toBeVisible();
  await clear.click();
  await expect(query).toHaveValue("");
  await expect(severity).toHaveValue("all");
  await expect(alertRow).toBeVisible();

  // Keyboard focus reaches the Search input with the visible seafoam
  // focus ring from the Signal focus rules. The final Tab back is a
  // keyboard-initiated focus move, so :focus-visible must apply.
  await query.click();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  const focusedQuery = await page.evaluate(() => {
    const el = document.activeElement;
    return el instanceof HTMLElement
      ? {
          testid: el.getAttribute("data-testid"),
          focusVisible: el.matches(":focus-visible"),
          outlineWidth: getComputedStyle(el).outlineWidth,
          outlineStyle: getComputedStyle(el).outlineStyle,
          outlineColor: getComputedStyle(el).outlineColor,
        }
      : null;
  });
  expect(focusedQuery?.testid).toBe("ops-alerts-filter-query");
  expect(focusedQuery?.focusVisible).toBe(true);
  expect(focusedQuery?.outlineStyle).toBe("solid");
  expect(focusedQuery?.outlineWidth).toBe("2px");
  expect(focusedQuery?.outlineColor).toBe("rgb(168, 216, 209)");

  // Desktop density is preserved while typing at 1440px too.
  await page.setViewportSize({ width: 1440, height: 900 });
  await settle(page);
  await query.click();
  await query.pressSequentially("kraken");
  await expect(query).toHaveValue("kraken");
  await expect(alertRow).toBeVisible();
  const desktopGeometry = await measureQuery(page);
  expect(desktopGeometry.rect.height).toBeGreaterThanOrEqual(34);
  expect(desktopGeometry.rect.height).toBeLessThan(44);
  await clear.click();
  await expect(query).toHaveValue("");

  expect(guard.errors).toEqual([]);
  expect(guard.badResponses).toEqual([]);
  console.log(
    `[alerts-touch] errors=${guard.errors.length} badResponses=${guard.badResponses.length}`,
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
