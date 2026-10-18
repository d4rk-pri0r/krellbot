import type {Page, Locator} from "@playwright/test";
import {readFileSync} from "node:fs";
import {join} from "node:path";
import {test, expect} from "../e2e/journey-harness/journey-harness";
import {armPaper, holdRehearsal} from "./helpers/paper-steps";
import {clickNav, saveJson, validateRevision, SMA_CROSS_FIXTURE_JSON, COMMITTED_CANDLE_CSV, runResearch, waitForResearchResult, readJournalTicks} from "./helpers/journey-steps";

test.beforeEach(async ({journey})=>{await journey.page.goto(journey.workstation.baseURL);await journey.waitForSessionReady(journey.page);});
const windowInput={from:"0",to:String(Date.parse("1970-01-02T00:00:00Z"))};
async function research(page: Page,feeBps="10",window=windowInput) {
  await clickNav(page,"Strategies");await saveJson(page,SMA_CROSS_FIXTURE_JSON);await validateRevision(page,"validated");
  await clickNav(page,"Research");const run=await runResearch(page,{dataset:COMMITTED_CANDLE_CSV,feeBps,...window});await waitForResearchResult(page);return run.jobId;
}
async function download(page: Page,button: Locator) {
  const pending=page.waitForEvent("download",{timeout:15_000});await button.click();const item=await pending;
  expect(await item.failure()).toBeNull();const path=await item.path();if(!path)throw new Error("download path missing");
  const text=readFileSync(path,"utf8");
  await test.info().attach(item.suggestedFilename(),{body:Buffer.from(text),contentType:"text/plain"});
  return {text,name:item.suggestedFilename()};
}
function csv(text: string): string[][] {
  const rows:string[][]=[];let row:string[]=[],cell="",quoted=false;
  for(let i=0;i<text.length;i++){
    const c=text[i];
    if(c==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}
    else if(c===","&&!quoted){row.push(cell);cell="";}
    else if(c==="\n"&&!quoted){row.push(cell.replace(/\r$/,""));rows.push(row);row=[];cell="";}
    else cell+=c;
  }
  if(cell||row.length){row.push(cell);rows.push(row);}expect(quoted,"CSV quotes must balance").toBe(false);return rows;
}
async function visibleResult(page:Page){
  const details=page.getByTestId("research-receipt-detail");
  if(!await details.evaluate((el:HTMLDetailsElement)=>el.open))await details.locator("summary").click();
  return JSON.parse(await page.getByTestId("research-export").innerText());
}

test("J7.1 I can export a backtest's results and its bar-by-bar trace, and the files match the screen: same numbers, same rows",async({journey})=>{
  const page=journey.page;const id=await research(page);const visible=await visibleResult(page);
  const receipt=await download(page,page.getByTestId("research-export-result"));
  expect(receipt.name).toBe(`research-receipt-${id}.json`);const result=JSON.parse(receipt.text);
  expect(result).toEqual(visible.legacy_receipt);
  await expect(page.getByTestId("research-result-total-return-pct")).toHaveText(String(result.metrics.total_return_pct));
  await expect(page.getByTestId("research-result-max-drawdown")).toHaveText(`${result.metrics.max_drawdown_pct}%`);
  await expect(page.getByTestId("research-result-trade-count")).toHaveText(String(result.metrics.trade_count));
  const trace=await download(page,page.getByTestId("research-trace-csv-export"));const [columns,...rows]=csv(trace.text);
  const expected=visible.trace as Array<Record<string,unknown>>;
  expect(rows.length).toBe(expected.length);expect(expected.length).toBeGreaterThan(0);
  await expect(page.getByTestId("research-trace-count")).toHaveText(String(rows.length));
  expect(new Set(columns)).toEqual(new Set(expected.flatMap(row=>Object.keys(row))));
  for(let i=0;i<rows.length;i++)for(let j=0;j<columns.length;j++){
    const value=expected[i][columns[j]];
    if(value!==null&&typeof value==="object")expect(JSON.parse(rows[i][j])).toEqual(value);
    else expect(rows[i][j]).toBe(value===null||value===undefined?"":String(value));
  }
});

test("J7.2 I can export paper status and history, and the file matches the paper journal",async({journey})=>{
  const page=journey.page;await holdRehearsal(page);await armPaper(page,"1200");await clickNav(page,"Workstation");
  const file=await download(page,page.getByTestId("paper-status-csv-export"));const [header,values]=csv(file.text);
  const record=Object.fromEntries(header.map((name,i)=>[name,values[i]]));
  const config=JSON.parse(readFileSync(join(journey.workstation.homeDir,"config.json"),"utf8"));
  expect(record.armed).toBe("true");expect(record.venue).toBe(config.armed[0].venue);expect(record.pair).toBe(config.armed[0].pair);
  expect(record.mode).toBe("paper");expect(record.pack_id).toBe(config.armed[0].pack_id);
  // Use genuine GUI-driven simulated history, not an unauthorized tick CLI.
  const journal=readJournalTicks(join(journey.workstation.homeDir,"rehearsal"));expect(journal.length).toBeGreaterThan(0);
  const panel=page.getByTestId("rehearsal-fills-panel");
  const historyButton=panel.getByRole("button",{name:/export/i});
  // Journey gap: https://github.com/d4rk-pri0r/krellbot/issues/106
  test.fail(true, "https://github.com/d4rk-pri0r/krellbot/issues/106");
  await expect(historyButton,"visible paper history needs an export affordance").toBeVisible({timeout:5_000});
  const history=await download(page,historyButton);const table=csv(history.text);
  const fills=JSON.parse(readFileSync(join(journey.workstation.homeDir,"rehearsal/run/paper-kraken.json"),"utf8")).recent_fills;
  expect(table.length-1).toBe(fills.length);
  for(const fill of fills)expect(history.text).toContain(String(fill.coid));
});

test("J7.3 An exported backtest carries what it takes to reproduce it: the strategy fingerprint, the data fingerprint, the window and the cost settings",async({journey})=>{
  // Use exact intraday bar boundaries, not an oversized requested range.
  // Rounding both ends to YYYY-MM-DD cannot reproduce this selected subset.
  const selectedWindow={from:"3600000",to:"14400000"};
  const page=journey.page;await research(page,"12",selectedWindow);const screen=await visibleResult(page);
  const {text}=await download(page,page.getByTestId("research-export-result"));const result=JSON.parse(text);
  expect(result).toEqual(screen.legacy_receipt);
  expect(result.pack_sha256).toMatch(/^[a-f0-9]{64}$/);expect(result.data_manifest_sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(screen.trace[0].bar_ts).toBe(Number(selectedWindow.from));
  expect(screen.trace.at(-1).bar_ts).toBe(Number(selectedWindow.to));
  // Journey gap: https://github.com/d4rk-pri0r/krellbot/issues/107
  test.fail(true, "https://github.com/d4rk-pri0r/krellbot/issues/107");
  expect.soft(Number(result.from_ms??Date.parse(result.from)),"export needs reproducible intraday start").toBe(Number(selectedWindow.from));
  expect.soft(Number(result.to_ms??Date.parse(result.to)),"export needs reproducible intraday end").toBe(Number(selectedWindow.to));
  expect(result.fee_bps).toBe(12);
  expect(Number.isFinite(result.slippage_bps)).toBe(true);
  expect(Number.isFinite(result.slippage_mult)).toBe(true);
  await expect(page.getByTestId("research-result-fee-bps")).toHaveText("12");
  await expect(page.getByTestId("research-result-data-manifest-sha256")).toHaveText(result.data_manifest_sha256);
});

test("J7.4 Export works offline and without an account, even when billing or the website is down",async({journey})=>{
  const page=journey.page;await research(page);
  // Egress has been denied since BEFORE the first navigation, not merely
  // while exporting. The fresh home has never received account/key input.
  const {text}=await download(page,page.getByTestId("research-export-result"));
  expect(JSON.parse(text).data_manifest_sha256).toMatch(/^[a-f0-9]{64}$/);
  journey.assertGuards();
});

test("J7.5 If an export can't finish, the screen says so, and no partial file is offered as complete",async({journey})=>{
  const page=journey.page;await research(page);
  await page.route("**/api/v1/jobs/*/result/download",route=>route.abort("connectionreset"));
  const downloads:string[]=[];page.on("download",item=>downloads.push(item.suggestedFilename()));
  await page.getByTestId("research-export-result").click();
  await expect(page.getByTestId("research-export-error")).toContainText(/failed|error|fetch/i);
  await expect(page.getByTestId("research-export-result")).not.toHaveAttribute("aria-busy","true");
  const announcement=await page.getByTestId("research-export-result-busy-status").textContent();
  await test.info().attach("failed-export-surface",{body:Buffer.from(JSON.stringify({announcement,error:await page.getByTestId("research-export-error").innerText(),downloads})),contentType:"application/json"});
  expect.soft(announcement,"failure must not be announced as Export complete").not.toMatch(/export complete/i);
  await page.waitForTimeout(500);expect(downloads).toEqual([]);
});
