import { test, expect } from "./journey-harness/journey-harness";
import { clickNav } from "../journeys/helpers/journey-steps";

// KRELL-SIGNAL-20261010: real guarded backend, fresh synthetic home, no owner state.
for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
  test(`kill refusal and lost-response reconciliation at ${viewport.width}px`, async ({ journey }) => {
    const { page } = journey;
    await page.setViewportSize(viewport);
    await page.goto(journey.workstation.baseURL);
    await journey.waitForSessionReady(page);
    await clickNav(page, "Operations");
    const reason = page.getByTestId("ops-kill-reason");
    const engage = page.getByTestId("ops-kill-engage");
    const state = page.getByTestId("ops-kill-state");
    const feedback = page.getByTestId("ops-kill-command-feedback");
    await expect(state).toHaveText("Kill switch: released");
    const invalidReason = "x".repeat(201);
    await reason.fill(invalidReason);
    const refusalResponse = page.waitForResponse((r) =>
      r.url().endsWith("/api/v1/commands") && r.request().postDataJSON()?.command === "operations.kill",
    );
    await engage.click();
    const response = await refusalResponse;
    expect(response.status()).toBe(200);
    expect(await response.json()).toMatchObject({ ok: false, code: "bad_input" });
    await expect(feedback).toContainText("refused");
    await expect(feedback).toContainText("reason must be 1..200 characters");
    await expect(reason).toHaveValue(invalidReason);
    await expect(state).toHaveText("Kill switch: released");

    // Let the real backend apply each command, then lose only its response.
    // This proves unknown != refused and that a read, not an automatic retry,
    // reconciles the actual state. No fabricated backend success.
    const applied: string[] = [];
    await page.route("**/api/v1/commands", async (route) => {
      const command = route.request().postDataJSON()?.command;
      if (command === "operations.kill" || command === "operations.release_kill") {
        applied.push(command);
        const realResponse = await route.fetch({ maxRetries: 0 });
        expect((await realResponse.json()).ok).toBe(true);
        await route.abort("failed");
      } else {
        await route.continue();
      }
    });
    await reason.fill("synthetic guarded smoke");
    await engage.click();
    await expect(feedback).toContainText("outcome unknown");
    await expect(feedback).toContainText("check state before retrying");
    await expect(reason).toHaveValue("synthetic guarded smoke");
    await page.getByTestId("ops-refresh").click();
    await expect(state).toContainText("Kill switch: engaged");
    expect(applied).toEqual(["operations.kill"]);

    await page.getByTestId("ops-kill-release").click();
    await expect(feedback).toContainText("release failed");
    await expect(feedback).toContainText("outcome unknown");
    await expect(reason).toHaveValue("synthetic guarded smoke");
    await page.getByTestId("ops-refresh").click();
    await expect(state).toHaveText("Kill switch: released");
    expect(applied).toEqual(["operations.kill", "operations.release_kill"]);
    await expect(page.getByTestId("ops-live-status")).toContainText("Live trading is disabled");
    const bounds = await engage.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width);
    if (viewport.width <= 640) expect(bounds!.height).toBeGreaterThanOrEqual(44);
    journey.assertGuards();
  });
}
