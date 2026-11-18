import {
  test,
  expect,
  type Page,
  type Route,
  type Response,
} from "@playwright/test";
import {
  startWorkstationForSpec,
  stopWorkstationForSpec,
  type WorkstationHandle,
} from "./workstation-harness";
import { clickNav } from "../journeys/helpers/journey-steps";

/**
 * M2.8 — Scheduler UI install / enable / status happy path with fakes.
 *
 * The loopback API's real install writes unit files under the process
 * user home; this spec therefore fakes GET/POST /api/v1/scheduler* so
 * the Operations panel proves install → enable → status without
 * touching the host scheduler. One workstation per file (bootstrap
 * token is one-shot), so happy path and unavailable copy share a
 * single test. KRELL-SIGNAL-20261010.
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
      if (path.startsWith("/api/v1/scheduler")) {
        return;
      }
      guard.badResponses.push({ method: req.method(), path, status });
    }
  });
  return guard;
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

type FakeState = {
  installed: boolean;
  enabled: boolean;
  last_error: string | null;
};

function body(state: FakeState) {
  return {
    schema_version: "1",
    installed: state.installed,
    enabled: state.enabled,
    last_error: state.last_error,
  };
}

async function installSchedulerFakes(page: Page, state: FakeState): Promise<void> {
  await page.route("**/api/v1/scheduler/**", async (route: Route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (req.method() === "POST" && path.endsWith("/scheduler/install")) {
      state.installed = true;
      state.enabled = false;
      state.last_error = null;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body(state)),
      });
      return;
    }
    if (req.method() === "POST" && path.endsWith("/scheduler/enable")) {
      if (!state.installed) {
        state.last_error = "not_installed";
      } else {
        state.enabled = true;
        state.last_error = null;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body(state)),
      });
      return;
    }
    await route.fallback();
  });

  await page.route("**/api/v1/scheduler", async (route: Route) => {
    const req = route.request();
    if (req.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body(state)),
      });
      return;
    }
    await route.fallback();
  });
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

test("Operations scheduler panel install/enable happy path and unavailable copy with faked API", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const guard = attachConsoleGuard(page);
  const state: FakeState = { installed: false, enabled: false, last_error: null };
  await installSchedulerFakes(page, state);

  const baseURL = workstation!.baseURL.replace(/\/$/, "");
  await page.goto(baseURL + "/");
  await waitForSessionReady(page);
  await clickNav(page, "Operations");

  // M18.4: Scheduler lives under Advanced — expand before asserting.
  const schedulerToggle = page.getByTestId("ops-scheduler-panel-toggle");
  await expect(schedulerToggle).toBeVisible();
  if ((await schedulerToggle.getAttribute("aria-expanded")) !== "true") {
    await schedulerToggle.click();
  }
  await expect(schedulerToggle).toHaveAttribute("aria-expanded", "true");

  const panel = page.getByTestId("ops-scheduler");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("ops-scheduler-status")).toHaveText("Not installed.");
  await expect(page.getByTestId("ops-scheduler-installed")).toHaveText("no");
  await expect(page.getByTestId("ops-scheduler-enabled")).toHaveText("no");
  await expect(page.getByTestId("ops-scheduler-enable")).toBeDisabled();

  await page.getByTestId("ops-scheduler-install").click();
  await expect(page.getByTestId("ops-scheduler-status")).toHaveText("Installed, not enabled.");
  await expect(page.getByTestId("ops-scheduler-installed")).toHaveText("yes");
  await expect(page.getByTestId("ops-scheduler-enabled")).toHaveText("no");
  await expect(page.getByTestId("ops-scheduler-feedback")).toContainText(/installed/i);
  await expect(page.getByTestId("ops-scheduler-enable")).toBeEnabled();

  await page.getByTestId("ops-scheduler-enable").click();
  await expect(page.getByTestId("ops-scheduler-status")).toHaveText("Installed and enabled.");
  await expect(page.getByTestId("ops-scheduler-enabled")).toHaveText("yes");
  await expect(page.getByTestId("ops-scheduler-feedback")).toContainText(/enabled/i);
  await expect(page.getByTestId("ops-scheduler-install")).toBeDisabled();
  await expect(page.getByTestId("ops-scheduler-enable")).toBeDisabled();

  // Honest copy when platform enable is unavailable (same session —
  // bootstrap token is one-shot per workstation).
  state.installed = true;
  state.enabled = false;
  state.last_error = "unsupported platform: aix";
  await page.getByTestId("ops-scheduler-refresh").click();
  await expect(page.getByTestId("ops-scheduler-unavailable")).toContainText(
    /Platform enable is unavailable/i,
  );
  await expect(page.getByTestId("ops-scheduler-unavailable-reason")).toHaveText(
    "unsupported platform: aix",
  );
  await expect(page.getByTestId("ops-scheduler-enable")).toBeDisabled();

  expect(guard.errors).toEqual([]);
});
