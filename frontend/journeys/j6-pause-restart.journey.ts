import {test, expect} from "../e2e/journey-harness/journey-harness";
import {readFileSync} from "node:fs";
import {join} from "node:path";
import {armPaper, tickPaper, paperRefresh, holdRehearsal, quantity, persistedState} from "./helpers/paper-steps";
import {clickNav, readJournalTicks, saveJson, validateRevision, SMA_CROSS_FIXTURE_JSON, runResearch, openLibrary} from "./helpers/journey-steps";

test.beforeEach(async ({journey})=>{await journey.page.goto(journey.workstation.baseURL); await journey.waitForSessionReady(journey.page);});

test("J6.1 Pausing entries stops new entries while stops and exits keep working, and the status shows entries as paused", async ({journey})=>{
  const page=journey.page; await armPaper(page);
  tickPaper(journey,[100,90,95]);
  expect(Number(readJournalTicks(journey.workstation.homeDir).at(-1)!.detail.owned_qty_after)).toBeGreaterThan(0);
  await page.getByTestId("editor-inline-stop-pause").click();
  await expect(page.getByTestId("editor-inline-stop-entries")).toContainText(/paused/i);
  await clickNav(page,"Workstation"); await expect(page.getByTestId("paper-status-entries")).toContainText(/paused/i);
  // First a profitable normal exit. A huge stop loss first would exhaust
  // the capital needed to seed the independent second position.
  tickPaper(journey,[100,90,95,110]);
  tickPaper(journey,[100,90,95,110,100]);
  const exited=readJournalTicks(journey.workstation.homeDir).at(-1)!;
  expect(Number(exited.detail.exit_qty)).toBeGreaterThan(0);
  expect(Number(exited.detail.owned_qty_after)).toBe(0);
  expect(exited.detail.entries_paused).toBe(true);
  tickPaper(journey,[100,90,95,110,100,105]);
  const suppressed=readJournalTicks(journey.workstation.homeDir).at(-1)!;
  expect(suppressed.detail.decision_reason).toBe("entry");
  expect(Number(suppressed.detail.entry_qty)).toBe(0);
  expect(Number(suppressed.detail.owned_qty_after)).toBe(0);
  expect(suppressed.detail.entries_paused).toBe(true);
  // Separately seed another real position, then pause and trigger its stop.
  const panel=page.getByTestId("paper-status-panel");
  await panel.getByRole("button",{name:"Resume entries",exact:true}).click();
  await expect(page.getByTestId("paper-status-entries")).toContainText(/active/i);
  tickPaper(journey,[100,90,95,110,100,105,100]);
  tickPaper(journey,[100,90,95,110,100,105,100,105]);
  expect(Number(readJournalTicks(journey.workstation.homeDir).at(-1)!.detail.entry_qty)).toBeGreaterThan(0);
  await panel.getByRole("button",{name:"Pause entries",exact:true}).click();
  await expect(page.getByTestId("paper-status-entries")).toContainText(/paused/i);
  tickPaper(journey,[100,90,95,110,100,105,100,105,10]);
  const stopped=readJournalTicks(journey.workstation.homeDir).at(-1)!;
  const venue=JSON.parse(readFileSync(join(journey.workstation.homeDir,"run/paper-kraken.json"),"utf8"));
  expect(venue.recent_fills.some((fill:{kind?:string;side:string;qty:string})=>fill.kind==="stop"&&fill.side==="sell"&&Number(fill.qty)>0)).toBe(true);
  expect(Number(stopped.detail.owned_qty_after)).toBe(0);
  expect(stopped.detail.entries_paused).toBe(true);
});

test("J6.2 Resuming entries lets the strategy enter again on its next signal", async ({journey})=>{
  const page=journey.page; await armPaper(page);
  await page.getByTestId("editor-inline-stop-pause").click();
  await expect(page.getByTestId("editor-inline-stop-entries")).toContainText(/paused/i);
  tickPaper(journey,[100,90,95]);
  const suppressed=readJournalTicks(journey.workstation.homeDir).at(-1)!;
  expect(Number(suppressed.detail.entry_qty)).toBe(0); expect(suppressed.detail.entries_paused).toBe(true);
  tickPaper(journey,[100,90,95,90]);
  await page.getByTestId("editor-inline-stop-resume").click();
  await expect(page.getByTestId("editor-inline-stop-entries")).toContainText(/active/i);
  tickPaper(journey,[100,90,95,90,95]); // ONE next signal, not repeated identical CSV ticks
  const entered=readJournalTicks(journey.workstation.homeDir).at(-1)!;
  expect(Number(entered.detail.entry_qty)).toBeGreaterThan(0);
  expect(Number(entered.detail.owned_qty_after)).toBeGreaterThan(0);
  expect(entered.detail.entries_paused).toBe(false);
  await clickNav(page,"Workstation"); await expect(page.getByTestId("paper-position")).toContainText(String(entered.detail.owned_qty_after));
});

test("J6.3 After a restart, armed strategies, positions, pause state, saved strategies and paper history are exactly as they were", async ({journey})=>{
  const page=journey.page;
  await armPaper(page,"1800");
  await page.getByTestId("editor-inline-stop-pause").click();
  await expect(page.getByTestId("editor-inline-stop-entries")).toContainText(/paused/i);
  // Only the GUI runs here: the shipped rehearsal creates a genuine open
  // paper position and nonempty journal, then pauses at that position.
  await holdRehearsal(page);
  expect(quantity(await page.getByTestId("rehearsal-position").innerText())).toBeGreaterThan(0);
  expect(readJournalTicks(journey.workstation.homeDir+"/rehearsal").length).toBeGreaterThan(0);
  const beforeFiles=persistedState(journey.workstation.homeDir);
  const before={entries:await page.getByTestId("paper-status-entries").innerText(),
    armed:await page.getByTestId("paper-armed-table").innerText(),
    position:await page.getByTestId("rehearsal-holdings-panel").innerText(),
    fills:await page.getByTestId("rehearsal-fills-panel").innerText()};
  await clickNav(page,"Strategies"); await openLibrary(page);
  const revisions=await page.getByTestId("library-row").allInnerTexts(); expect(revisions.length).toBeGreaterThan(0);
  await journey.workstation.restartSameHome();
  await page.goto(journey.workstation.baseURL); await journey.waitForSessionReady(page);
  await clickNav(page,"Workstation");
  await expect(page.getByTestId("paper-status-entries")).toHaveText(before.entries);
  await expect(page.getByTestId("paper-armed-table")).toHaveText(before.armed,{useInnerText:true});
  await expect(page.getByTestId("rehearsal-state-chip")).toContainText(/paused/i);
  await expect(page.getByTestId("rehearsal-holdings-panel")).toHaveText(before.position,{useInnerText:true});
  await expect(page.getByTestId("rehearsal-fills-panel")).toHaveText(before.fills,{useInnerText:true});
  await clickNav(page,"Strategies"); await openLibrary(page);
  expect(await page.getByTestId("library-row").allInnerTexts()).toEqual(revisions);
  expect(persistedState(journey.workstation.homeDir)).toEqual(beforeFiles);
});

test("J6.4 A backtest that was running when the workstation stopped shows as interrupted after restart. It never shows as running, and it never silently disappears", async ({journey})=>{
  const page=journey.page; await clickNav(page,"Strategies");
  await saveJson(page,SMA_CROSS_FIXTURE_JSON); await validateRevision(page,"validated");
  await clickNav(page,"Research");
  const {jobId}=await runResearch(page,{dataset:journey.workstation.rows100kCsv,feeBps:"10",from:"0",to:"9999999999999"});
  expect(jobId).not.toBe(""); await page.getByRole("button",{name:"Jobs",exact:true}).click();
  const row=page.getByTestId("kbot-jobs-dialog").getByTestId("job-row").filter({hasText:jobId});
  await expect(row.locator(".kbot-jobs__state")).toHaveText(/\(running\)/,{timeout:5_000});
  await journey.workstation.stop(); await journey.workstation.restartSameHome();
  await page.goto(journey.workstation.baseURL); await journey.waitForSessionReady(page);
  await page.getByRole("button",{name:"Jobs",exact:true}).click();
  const retained=page.getByTestId("kbot-jobs-dialog").getByTestId("job-row").filter({hasText:jobId});
  // Journey gap: https://github.com/d4rk-pri0r/krellbot/issues/104
  test.fail(true, "https://github.com/d4rk-pri0r/krellbot/issues/104");
  await expect(retained,"interrupted job must not disappear").toBeVisible({timeout:10_000});
  await expect(retained.locator(".kbot-jobs__state")).toHaveText(/interrupted/i);
});

test("J6.5 If the workstation stops while the GUI is open, the GUI says it can't reach it. When the workstation is back, one Retry recovers without a page reload", async ({journey})=>{
  const page=journey.page; await armPaper(page); await clickNav(page,"Workstation");
  await expect(page.getByTestId("paper-status-entries")).toContainText(/active/i);
  const documentId=await page.evaluate(()=>{const w=window as unknown as {journeyDocument:string}; w.journeyDocument=crypto.randomUUID();return w.journeyDocument;});
  let navigations=0;page.on("framenavigated",frame=>{if(frame===page.mainFrame())navigations++;});
  await journey.workstation.stop(); await paperRefresh(page).click();
  const error=page.getByRole("alert").filter({hasText:/status refresh failed/i});
  await expect(error).toContainText(/failed|unavailable/i);
  await journey.workstation.restartSameHome();
  // The existing Refresh status action is the panel's retry affordance.
  // Correlate its own response so stale retained Entries active cannot pass.
  const start=Date.now();
  // Journey gap: https://github.com/d4rk-pri0r/krellbot/issues/105
  test.fail(true, "https://github.com/d4rk-pri0r/krellbot/issues/105");
  const success=page.waitForResponse(r=>r.request().method()==="GET"&&new URL(r.url()).pathname==="/api/v1/paper/status"&&r.status()===200,{timeout:10_000});
  await paperRefresh(page).click();
  await success;
  await expect(error).toHaveCount(0,{timeout:Math.max(1,10_000-(Date.now()-start))});
  await expect(page.getByTestId("paper-status-entries")).toContainText(/active/i,{timeout:Math.max(1,10_000-(Date.now()-start))});
  expect(Date.now()-start).toBeLessThanOrEqual(10_000);
  expect(await page.evaluate(()=>(window as unknown as {journeyDocument:string}).journeyDocument)).toBe(documentId);
  expect(navigations).toBe(0);
});
