/**
 * M7.2 — client routing: URL reflects view, reload restores route,
 * browser back restores the previous view.
 *
 * Draft/selection policy (see frontend/src/shell/route.ts): a full
 * reload restores the view from ``?view=`` only; unsaved drafts and
 * transient selections are not URL-encoded and are not restored.
 */
import { test, expect } from "./journey-harness/journey-harness";
import { clickNav } from "../journeys/helpers/journey-steps";

test("route reload survival and back navigation", async ({ journey }) => {
  const page = journey.page;
  await page.goto(journey.workstation.baseURL);
  await journey.waitForSessionReady(page);

  await clickNav(page, "Strategies");
  await expect(page).toHaveURL(/[?&]view=strategies(?:&|$)/);
  await expect(page.getByTestId("library-toggle")).toBeVisible();

  await page.reload();
  await journey.waitForSessionReady(page);
  await expect(page).toHaveURL(/[?&]view=strategies(?:&|$)/);
  await expect(
    page
      .getByRole("navigation", { name: "Workstation navigation" })
      .getByRole("button", { name: "Strategies", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("library-toggle")).toBeVisible();

  await clickNav(page, "Research");
  await expect(page).toHaveURL(/[?&]view=research(?:&|$)/);
  await expect(page.getByTestId("research-host")).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL(/[?&]view=strategies(?:&|$)/);
  await expect(
    page
      .getByRole("navigation", { name: "Workstation navigation" })
      .getByRole("button", { name: "Strategies", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("library-toggle")).toBeVisible();
});
