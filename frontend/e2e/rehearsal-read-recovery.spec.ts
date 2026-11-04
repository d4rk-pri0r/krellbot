import { test, expect } from "./journey-harness/journey-harness";
import { clickNav } from "../journeys/helpers/journey-steps";

for (const width of [1440, 390]) {
  test(`rehearsal refresh recovers from a stalled read at width ${width}`, async ({ journey }) => {
    const page = journey.page;
    await page.setViewportSize({ width, height: 900 });
    await page.goto(journey.workstation.baseURL);
    await journey.waitForSessionReady(page);
    await clickNav(page, "Workstation");
    await expect(page.getByTestId("rehearsal-state-chip")).toHaveText("idle");
    let release!: () => void;
    const stalled = new Promise<void>(resolve => { release = resolve; });
    let reads = 0;
    let commands = 0;
    page.on("request", request => {
      if (request.method() === "POST" && new URL(request.url()).pathname === "/api/v1/commands") commands++;
    });
    await page.route("**/api/v1/rehearsal/status", async route => {
      reads++;
      if (reads === 1) {
        await stalled;
        await route.abort().catch(() => undefined);
      } else await route.continue();
    });
    const refresh = page.getByTestId("rehearsal-command-refresh");
    await refresh.focus();
    await page.keyboard.press("Enter");
    await expect(refresh).toBeDisabled();
    await expect(page.getByTestId("rehearsal-panel")).toContainText("read timed out after 15000ms", { timeout: 20000 });
    await expect(refresh).toBeEnabled();
    expect(reads).toBe(1);
    expect(commands).toBe(0);
    release();
    await refresh.click();
    await expect(page.getByTestId("rehearsal-panel")).not.toContainText("last confirmed state");
    await expect(refresh).toBeEnabled();
    await expect(page.getByTestId("rehearsal-state-chip")).toHaveText("idle");
    expect(reads).toBe(2);
    expect(commands).toBe(0);
  });
}
