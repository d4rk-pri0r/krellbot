/**
 * M3.2 Kraken keys onboarding happy path (KRELL-SIGNAL-20261010).
 *
 * Uses Playwright route fakes for `/api/v1/keys/kraken` only — no real
 * credentials, keyring writes, or exchange network. Session/CSRF still
 * come from the guarded workstation.
 */
import { test, expect } from "./journey-harness/journey-harness";
import { clickNav } from "../journeys/helpers/journey-steps";

const FAKE_PUBLIC = "fake-kraken-public-key";
const FAKE_PRIVATE = "fake-kraken-private-secret";

test("keys onboarding: probe-store, show holdings, then remove with fakes", async ({
  journey,
}) => {
  const page = journey.page;
  let present = false;

  await page.route("**/api/v1/keys/kraken", async (route) => {
    const method = route.request().method();
    if (method === "GET") {
      if (!present) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            schema_version: "1",
            venue: "kraken",
            present: false,
            corrupt: false,
            message: "no key stored",
            backend_label: null,
            balances: null,
            balances_available: false,
          }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: "1",
          venue: "kraken",
          present: true,
          corrupt: false,
          message: "key present",
          backend_label: "FakeKeyring",
          balances: [
            { asset: "ZUSD", free: "100.5" },
            { asset: "XXBT", free: "0.01" },
          ],
          balances_available: true,
        }),
      });
      return;
    }
    if (method === "POST") {
      const body = route.request().postDataJSON() as {
        key?: string;
        secret?: string;
      };
      expect(body.key).toBe(FAKE_PUBLIC);
      expect(body.secret).toBe(FAKE_PRIVATE);
      present = true;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: "1",
          venue: "kraken",
          status: "stored",
          ok: true,
          message: "stored in native OS keychain",
          effect: "changed",
          backend_label: "FakeKeyring",
        }),
      });
      return;
    }
    if (method === "DELETE") {
      present = false;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: "1",
          venue: "kraken",
          status: "removed",
          ok: true,
          message: "removed from keychain",
          effect: "changed",
          backend_label: "FakeKeyring",
        }),
      });
      return;
    }
    await route.continue();
  });

  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await clickNav(page, "Workspace");

  const panel = page.getByTestId("keys-onboarding");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("keys-form")).toBeVisible();
  await expect(page.getByTestId("keys-status")).toContainText(/no key stored/i);
  await expect(page.getByTestId("keys-paper-only")).toContainText(/paper-only/i);

  await page.getByTestId("keys-public").fill(FAKE_PUBLIC);
  await page.getByTestId("keys-private").fill(FAKE_PRIVATE);
  await page.getByTestId("keys-store").click();

  await expect(page.getByTestId("keys-feedback")).toContainText(
    /stored in native OS keychain/i,
  );
  await expect(page.getByTestId("keys-connected")).toBeVisible();
  await expect(page.getByTestId("keys-balance-ZUSD")).toContainText("100.5");
  await expect(page.getByTestId("keys-balance-XXBT")).toContainText("0.01");
  await expect(page.getByTestId("keys-public")).toHaveCount(0);

  await page.getByTestId("keys-remove").click();
  await expect(page.getByTestId("keys-feedback")).toContainText(/removed from keychain/i);
  await expect(page.getByTestId("keys-form")).toBeVisible();
  await expect(page.getByTestId("keys-status")).toContainText(/no key stored/i);

  journey.assertGuards();
});

test("keys onboarding: honest unsupported keyring backend from probe-and-store", async ({
  journey,
}) => {
  const page = journey.page;

  await page.route("**/api/v1/keys/kraken", async (route) => {
    const method = route.request().method();
    if (method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: "1",
          venue: "kraken",
          present: false,
          corrupt: false,
          message: "no key stored",
          backend_label: null,
          balances: null,
          balances_available: false,
        }),
      });
      return;
    }
    if (method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: "1",
          venue: "kraken",
          status: "unsupported_backend",
          ok: false,
          message: "keyring backend is not a native OS keychain; refused",
          effect: "refused",
          backend_label: null,
        }),
      });
      return;
    }
    await route.continue();
  });

  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await clickNav(page, "Workspace");

  await page.getByTestId("keys-public").fill(FAKE_PUBLIC);
  await page.getByTestId("keys-private").fill(FAKE_PRIVATE);
  await page.getByTestId("keys-store").click();

  await expect(page.getByTestId("keys-feedback")).toContainText(
    /keyring backend is not a native OS keychain/i,
  );
  await expect(page.getByTestId("keys-form")).toBeVisible();
  journey.assertGuards();
});
