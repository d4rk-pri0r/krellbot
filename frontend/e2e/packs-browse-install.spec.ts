/**
 * M5.2 Packs browse + one-click install (KRELL-SIGNAL-20261010).
 *
 * Playwright route fakes for catalogue / install / library only — no
 * real signed envelopes, network catalogue fetch, or exchange calls.
 * Session/CSRF still come from the guarded workstation.
 */
import { test, expect } from "./journey-harness/journey-harness";
import { clickNav } from "../journeys/helpers/journey-steps";

const CATALOGUE = {
  schema_version: "1",
  catalogue_version: "1",
  updated: "2026-11-16T00:00:00Z",
  packs: [
    {
      id: "free-dual-ma",
      label: "Free Dual MA",
      description: "Educational free pack",
      version: "1.0.0",
      tier: "free",
      permissions: [],
    },
    {
      id: "paid-triple-stack",
      label: "Triple Stack",
      description: "Paid catalog pack",
      version: "2.1.0",
      tier: "paid",
      permissions: ["catalog"],
    },
  ],
};

async function stubPackApis(page: import("@playwright/test").Page): Promise<void> {
  let library: Array<Record<string, unknown>> = [];

  await page.route("**/api/v1/catalogue", async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(CATALOGUE),
    });
  });

  await page.route("**/api/v1/packs/install", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    const raw = route.request().postDataJSON() as { pack_id?: string };
    const packId = typeof raw?.pack_id === "string" ? raw.pack_id : "";
    if (packId === "paid-triple-stack") {
      await route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: "1",
          ok: false,
          code: "activation_required",
          message: "paid pack requires activation redeem before install",
        }),
      });
      return;
    }
    if (packId !== "free-dual-ma") {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: "1",
          ok: false,
          code: "pack_not_found",
          message: "catalogue entry not found",
        }),
      });
      return;
    }
    const pack = {
      bucket: "download_pending",
      pack_id: "free-dual-ma",
      version: "1.0.0",
      permissions: [],
      rollback_ref: null,
    };
    library = [pack];
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ schema_version: "1", ok: true, pack }),
    });
  });

  await page.route("**/api/v1/packs", async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    // Do not intercept /api/v1/packs/starters or /install.
    const url = route.request().url();
    if (url.includes("/packs/")) {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(library),
    });
  });
}

test("packs browse: first-class Packs nav shows signed catalogue rows", async ({
  journey,
}) => {
  const page = journey.page;
  await stubPackApis(page);
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await clickNav(page, "Packs");
  await expect(page.getByTestId("packs-view")).toBeVisible();
  await expect(page.getByTestId("pack-catalogue-list")).toBeVisible();
  await expect(page.getByTestId("pack-catalogue-id-free-dual-ma")).toHaveText(
    "free-dual-ma",
  );
  await expect(page.getByTestId("pack-catalogue-tier-free-dual-ma")).toHaveText(
    "free",
  );
  await expect(page.getByTestId("pack-catalogue-version-free-dual-ma")).toHaveText(
    "1.0.0",
  );
  await expect(page.getByTestId("pack-catalogue-tier-paid-triple-stack")).toHaveText(
    "paid",
  );
  journey.assertGuards();
});

test("packs one-click install: free pack lands in library with bucket and version", async ({
  journey,
}) => {
  const page = journey.page;
  await stubPackApis(page);
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await clickNav(page, "Packs");
  await expect(page.getByTestId("pack-catalogue-list")).toBeVisible();
  await expect(page.getByTestId("pack-library-empty")).toBeVisible();

  await page.getByTestId("pack-catalogue-install-free-dual-ma").click();
  await expect(
    page.getByTestId("pack-catalogue-install-status-free-dual-ma"),
  ).toContainText(/Installed · download_pending · 1\.0\.0/);

  await expect(page.getByTestId("pack-library-row-free-dual-ma")).toBeVisible();
  await expect(page.getByTestId("pack-library-bucket-free-dual-ma")).toContainText(
    "download_pending",
  );
  await expect(page.getByTestId("pack-library-version-free-dual-ma")).toHaveText(
    "1.0.0",
  );
  journey.assertGuards();
});
