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
  const reason = page.getByTestId("ops-live-auth-paper-only-reason");
  await expect(reason).toContainText(/live order send is disabled/i);
  // Honesty: paper_only_message must track package version (not a stale v0.9.6).
  await expect(reason).toContainText(/v0\.9\.\d+ is a paper-only release/i);
  await expect(reason).not.toContainText("v0.9.6");

  await expect(page.getByTestId("ops-live-auth-venue")).toBeDisabled();
  await expect(page.getByTestId("ops-live-auth-pair")).toBeDisabled();
  await expect(page.getByTestId("ops-live-auth-hours")).toBeDisabled();
  await expect(page.getByTestId("ops-live-auth-confirm")).toBeDisabled();
  await expect(page.getByTestId("ops-live-auth-grant")).toBeDisabled();
  await expect(page.getByTestId("ops-live-auth-revoke")).toBeDisabled();
});
