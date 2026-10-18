/** Fresh guarded workstation and browser per scenario: no order-dependent state. */
import {test as base, expect, chromium, type Page} from "@playwright/test";
import {attachNetworkGuard, assertNoOffLoopback, type NetworkGuard} from "./network-guard";
import {attachCommandLog, assertNoLiveOrderCommands, type CommandLog} from "./command-log";
import {startJourneyWorkstation, runGuardedCli, spawnGuardedPython, sanitizedJourneyEnv, type JourneyWorkstationHandle} from "./spawn-layer";

export {runGuardedCli, spawnGuardedPython};
export type {JourneyWorkstationHandle};
export type JourneyScope = {
  workstation: JourneyWorkstationHandle;
  page: Page;
  waitForSessionReady(page: Page): Promise<void>;
  guards: {network: NetworkGuard; commands: CommandLog};
  assertGuards(): void;
};

export async function waitForSessionReady(page: Page): Promise<void> {
  await page.waitForFunction(() => document.querySelector('[data-testid="kbot-shell"]')?.getAttribute("data-bootstrap-done") === "1", undefined, {timeout: 20_000});
}

export const jTest = base.extend<{journey: JourneyScope}>({
  journey: [async ({}, use, testInfo) => {
    const workstation = await startJourneyWorkstation();
    const browserEnv = Object.fromEntries(Object.entries(sanitizedJourneyEnv(workstation.homeDir)).filter((entry): entry is [string, string] => entry[1] !== undefined));
    const context = await chromium.launchPersistentContext(`${workstation.homeDir}/.chromium-profile`, {headless: true, serviceWorkers: "block", acceptDownloads: true, env: browserEnv});
    const page = context.pages()[0] ?? await context.newPage();
    // Install BOTH guards while the page is still about:blank. Scenario
    // beforeEach performs the first real navigation only after fixture yield.
    const network = await attachNetworkGuard(page);
    const commands = await attachCommandLog(page);
    const assertGuards = () => {
      assertNoOffLoopback(network);
      assertNoLiveOrderCommands(commands);
      workstation.commandLog.assertAll();
      if (!workstation.intentionallyStopped() && (workstation.child().exitCode !== null || workstation.child().signalCode !== null)) throw new Error("guarded workstation exited unexpectedly");
    };
    try {
      await use({workstation, page, waitForSessionReady, guards: {network, commands}, assertGuards});
    } finally {
      const evidence = {home: workstation.homeDir, network: network.offLoopback, http: commands.records,
        subprocesses: workstation.commandLog.commands, pythonRefusals: workstation.commandLog.netGuardRefusals()};
      await testInfo.attach("journey-safety-audit", {body: Buffer.from(JSON.stringify(evidence, null, 2)), contentType: "application/json"});
      try {
        assertGuards();
      } catch (error) {
        // An unrelated test.fail annotation must never hide a safety failure.
        testInfo.expectedStatus = "passed";
        throw error;
      } finally {
        await context.close();
        await workstation.stop();
      }
    }
  }, {auto: true}],
});
export {expect};
export {jTest as test};
