/**
 * Approved scenarios (docs/journeys/j8-live-authorization.md, word for word):
 *
 * J8.1 While this build is paper-only, the Live authorization panel is
 *      visible on Operations, every control is disabled, and the panel
 *      says why live authorization cannot be granted.
 *
 * J8.2–J8.5 are covered by pytest in tests/test_live_authorization_api.py
 * (grant, expiry, revoke, wrong-pair refusal against the fake transport).
 */
import { test, expect } from "../e2e/journey-harness/journey-harness";
import { clickNav } from "./helpers/journey-steps";

test.beforeEach(async ({ journey }) => {
  await journey.page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(journey.page);
});

test("J8.1 While this build is paper-only, the Live authorization panel is visible on Operations, every control is disabled, and the panel says why live authorization cannot be granted", async ({
  journey,
}) => {
  const page = journey.page;
  await clickNav(page, "Operations");

  const panel = page.getByTestId("ops-live-authorization");
  await expect(panel).toBeVisible();

  const paperOnly = page.getByTestId("ops-live-auth-paper-only");
  await expect(paperOnly).toBeVisible();
  await expect(paperOnly).toContainText(/paper-only/i);
  await expect(page.getByTestId("ops-live-auth-paper-only-reason")).toContainText(
    /live order send is disabled/i,
  );

  await expect(page.getByTestId("ops-live-auth-venue")).toBeDisabled();
  await expect(page.getByTestId("ops-live-auth-pair")).toBeDisabled();
  await expect(page.getByTestId("ops-live-auth-hours")).toBeDisabled();
  await expect(page.getByTestId("ops-live-auth-confirm")).toBeDisabled();
  await expect(page.getByTestId("ops-live-auth-grant")).toBeDisabled();
  await expect(page.getByTestId("ops-live-auth-revoke")).toBeDisabled();
});
