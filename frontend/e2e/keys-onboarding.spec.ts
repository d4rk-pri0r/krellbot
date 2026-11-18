/**
 * M3.2 / M11.1 exchange keys onboarding happy paths (KRELL-SIGNAL-20261010).
 *
 * Uses Playwright route fakes for `/api/v1/keys/{venue}` only — no real
 * credentials, keyring writes, or exchange network. Session/CSRF still
 * come from the guarded workstation.
 */
import { test, expect } from "./journey-harness/journey-harness";
import { clickNav } from "../journeys/helpers/journey-steps";

const FAKE_KRAKEN_PUBLIC = "fake-kraken-public-key";
const FAKE_KRAKEN_PRIVATE = "fake-kraken-private-secret";
const FAKE_COINBASE_PUBLIC = "organizations/fake-org/apiKeys/fake-coinbase-key";
const FAKE_COINBASE_PRIVATE =
  "-----BEGIN PRIVATE KEY-----\nfake-coinbase-pem\n-----END PRIVATE KEY-----";

/**
 * M18.2 collapses Exchange keys under Advanced on Workspace home.
 * Expand before interacting so probe/store controls are visible.
 */
async function expandHomeKeysAdvanced(
  page: import("@playwright/test").Page,
): Promise<void> {
  const toggle = page.getByTestId("app-home-keys-rail-toggle");
  await expect(toggle).toBeVisible();
  if ((await toggle.getAttribute("aria-expanded")) !== "true") {
    await toggle.click();
  }
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
}

async function stubVenue(
  page: import("@playwright/test").Page,
  venue: "kraken" | "coinbase",
  holdings: ReadonlyArray<{ asset: string; free: string }>,
): Promise<{ setPresent: (value: boolean) => void }> {
  let present = false;
  await page.route(`**/api/v1/keys/${venue}`, async (route) => {
    const method = route.request().method();
    if (method === "GET") {
      if (!present) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            schema_version: "1",
            venue,
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
          venue,
          present: true,
          corrupt: false,
          message: "key present",
          backend_label: "FakeKeyring",
          balances: holdings,
          balances_available: true,
        }),
      });
      return;
    }
    if (method === "POST") {
      present = true;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: "1",
          venue,
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
          venue,
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
  return {
    setPresent(value: boolean) {
      present = value;
    },
  };
}

test("keys onboarding: Kraken probe-store, show holdings, then remove with fakes", async ({
  journey,
}) => {
  const page = journey.page;
  await stubVenue(page, "kraken", [
    { asset: "ZUSD", free: "100.5" },
    { asset: "XXBT", free: "0.01" },
  ]);
  await stubVenue(page, "coinbase", [
    { asset: "USD", free: "1" },
    { asset: "BTC", free: "0.001" },
  ]);

  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await clickNav(page, "Workspace");
  await expandHomeKeysAdvanced(page);

  const panel = page.getByTestId("keys-onboarding-kraken");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("keys-form-kraken")).toBeVisible();
  await expect(page.getByTestId("keys-status-kraken")).toContainText(/no key stored/i);
  await expect(page.getByTestId("keys-paper-only-kraken")).toContainText(/paper-only/i);

  await page.getByTestId("keys-public-kraken").fill(FAKE_KRAKEN_PUBLIC);
  await page.getByTestId("keys-private-kraken").fill(FAKE_KRAKEN_PRIVATE);
  await page.getByTestId("keys-store-kraken").click();

  await expect(page.getByTestId("keys-feedback-kraken")).toContainText(
    /stored in native OS keychain/i,
  );
  await expect(page.getByTestId("keys-stored-kraken")).toBeVisible();
  await expect(page.getByTestId("keys-balance-kraken-ZUSD")).toContainText("100.5");
  await expect(page.getByTestId("keys-balance-kraken-XXBT")).toContainText("0.01");
  await expect(page.getByTestId("keys-public-kraken")).toHaveCount(0);

  await page.getByTestId("keys-remove-kraken").click();
  await expect(page.getByTestId("keys-feedback-kraken")).toContainText(/removed from keychain/i);
  await expect(page.getByTestId("keys-form-kraken")).toBeVisible();
  await expect(page.getByTestId("keys-status-kraken")).toContainText(/no key stored/i);

  journey.assertGuards();
});

test("keys onboarding: Coinbase probe-store, show holdings, then remove with fakes", async ({
  journey,
}) => {
  const page = journey.page;
  await stubVenue(page, "kraken", [
    { asset: "ZUSD", free: "1" },
    { asset: "XXBT", free: "0.001" },
  ]);
  await stubVenue(page, "coinbase", [
    { asset: "USD", free: "250.75" },
    { asset: "BTC", free: "0.002" },
  ]);

  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await clickNav(page, "Workspace");
  await expandHomeKeysAdvanced(page);

  const panel = page.getByTestId("keys-onboarding-coinbase");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("keys-form-coinbase")).toBeVisible();
  await expect(page.getByTestId("keys-status-coinbase")).toContainText(/no key stored/i);

  await page.getByTestId("keys-public-coinbase").fill(FAKE_COINBASE_PUBLIC);
  await page.getByTestId("keys-private-coinbase").fill(FAKE_COINBASE_PRIVATE);
  await page.getByTestId("keys-store-coinbase").click();

  await expect(page.getByTestId("keys-feedback-coinbase")).toContainText(
    /stored in native OS keychain/i,
  );
  await expect(page.getByTestId("keys-stored-coinbase")).toBeVisible();
  await expect(page.getByTestId("keys-balance-coinbase-USD")).toContainText("250.75");
  await expect(page.getByTestId("keys-balance-coinbase-BTC")).toContainText("0.002");
  await expect(page.getByTestId("keys-public-coinbase")).toHaveCount(0);

  await page.getByTestId("keys-remove-coinbase").click();
  await expect(page.getByTestId("keys-feedback-coinbase")).toContainText(
    /removed from keychain/i,
  );
  await expect(page.getByTestId("keys-form-coinbase")).toBeVisible();

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
  await page.route("**/api/v1/keys/coinbase", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "1",
        venue: "coinbase",
        present: false,
        corrupt: false,
        message: "no key stored",
        backend_label: null,
        balances: null,
        balances_available: false,
      }),
    });
  });

  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);
  await clickNav(page, "Workspace");
  await expandHomeKeysAdvanced(page);

  await page.getByTestId("keys-public-kraken").fill(FAKE_KRAKEN_PUBLIC);
  await page.getByTestId("keys-private-kraken").fill(FAKE_KRAKEN_PRIVATE);
  await page.getByTestId("keys-store-kraken").click();

  await expect(page.getByTestId("keys-feedback-kraken")).toContainText(
    /keyring backend is not a native OS keychain/i,
  );
  await expect(page.getByTestId("keys-form-kraken")).toBeVisible();
  journey.assertGuards();
});
