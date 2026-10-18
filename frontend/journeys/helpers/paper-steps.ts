import {expect, test, type Page} from "@playwright/test";
import {readFileSync, writeFileSync, readdirSync, statSync, existsSync} from "node:fs";
import {join} from "node:path";
import {runGuardedCli, type JourneyScope} from "../../e2e/journey-harness/journey-harness";
import {clickNav, saveJson, validateRevision, SMA_CROSS_FIXTURE_JSON} from "./journey-steps";

export async function armPaper(page: Page, balance = "1000") {
  await clickNav(page, "Strategies");
  const revision = await saveJson(page, SMA_CROSS_FIXTURE_JSON);
  await validateRevision(page, "validated");
  const editor = page.getByRole("region", {name: "Strategy editor"});
  await editor.getByLabel(/^venue$/i).fill("kraken");
  await editor.getByLabel(/balance/i).fill(balance);
  await editor.getByRole("button", {name: /^arm$/i}).click();
  await expect(page.getByTestId("editor-inline-stop-entries")).toContainText(/active|armed/i);
  return revision;
}

export function tickPaper(journey: JourneyScope, closes: number[]) {
  if (!/^(J5\.3|J6\.1|J6\.2)\b/.test(test.info().title)) throw new Error("Offline CLI ticks are authorized only in J5.3/J6.1/J6.2");
  const path = join(journey.workstation.homeDir, "data", `progressive-${closes.length}.csv`);
  const rows = closes.map((close, i) => `${1700000000000+i*3600000},${close},${close+0.01},${close-0.01},${close},100`);
  writeFileSync(path, "ts_ms,open,high,low,close,volume\n"+rows.join("\n")+"\n");
  const result = runGuardedCli(["-m","krellbot","tick","--venue","kraken","--offline-candles",path], {home: journey.workstation.homeDir, commandLog: journey.workstation.commandLog});
  expect(result.status, result.stderr+result.stdout).toBe(0);
  return result;
}

export function paperRefresh(page: Page) {
  return page.getByTestId("paper-status-panel").locator(":scope > .kbot-paper-status__body > .kbot-paper-status__actions").getByRole("button", {name:"Refresh status", exact:true});
}
export function quantity(text: string): number {
  const found = text.match(/(?:Position\s*)?(-?\d+(?:\.\d+)?)/i);
  if (!found) throw new Error(`No quantity in ${JSON.stringify(text)}`);
  return Number(found[1]);
}
export async function holdRehearsal(page: Page) {
  await clickNav(page, "Workstation");
  await expect(page.getByTestId("rehearsal-label")).toContainText(/simulated data, not market/i);
  await page.getByTestId("rehearsal-command-start").click();
  await expect.poll(async () => {
    await page.getByTestId("rehearsal-command-refresh").click();
    return quantity(await page.getByTestId("rehearsal-position").innerText());
  }, {timeout: 90_000, intervals:[500,1000]}).toBeGreaterThan(0);
  await page.getByTestId("rehearsal-command-pause").click();
  await expect(page.getByTestId("rehearsal-state-chip")).toContainText("paused");
  await expect(page.getByTestId("rehearsal-label")).toContainText(/simulated/i);
}

export function persistedState(home: string): Record<string,string> {
  const result: Record<string,string> = {};
  function walk(path: string, key: string) {
    if (!existsSync(path)) return;
    if (statSync(path).isDirectory()) for (const child of readdirSync(path).sort()) walk(join(path,child),`${key}/${child}`);
    else if (/\.(json|jsonl)$/.test(path)) result[key] = readFileSync(path,"utf8");
  }
  for (const name of ["config.json","drafts","run","journal","rehearsal/state.json","rehearsal/config.json","rehearsal/run","rehearsal/journal"]) walk(join(home,name),name);
  return result;
}
