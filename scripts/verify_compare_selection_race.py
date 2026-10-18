#!/usr/bin/env python3
"""Qualify comparison selection races against real loopback storage and Chromium.

Response-stage CDP pauses delay genuine HTTP responses without substituting data.
A labelled temporary draft is briefly hidden to obtain a genuine backend 404.
Every process has a deadline and only owned children are terminated in finally.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

from krellbot import config, paths
from krellbot.application.strategy import StrategyDraftService

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
REQUIRED = [
    "bootstrap_session_csrf", "initial_actual_diff", "completed_left_clears",
    "completed_right_clears", "delayed_success_left_ignored", "delayed_success_right_ignored",
    "delayed_failure_left_ignored", "delayed_failure_right_ignored", "fresh_compare_actual_results",
    "real_failure_visible_and_cleared", "explicit_compare_only", "empty_and_equal_disabled",
    "keyboard_mobile", "unmount_pending_ignored", "read_only_requests", "loopback_only",
    "no_browser_errors", "storage_unchanged", "live_off_unarmed",
]

BROWSER = r'''
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const { chromium, expect } = require('@playwright/test');
const {url, out, revisions, missingPath, executable} = JSON.parse(process.env.COMPARE_VERIFY_CONFIG);
const assertions = {}, requests = [], pauses = [], errors = [], diagnostics = {};
const [a, b, c] = revisions;
let browser, context, page, cdp, armed = null, held = null, hidden = false, version;
const id = name => page.getByTestId(`revision-compare-${name}`);
const prefix = '/api/v1/strategies/drafts/';
async function check(name, action) { await action(); assertions[name] = true; }
async function idle() {
  for (const name of ['loading', 'error', 'changes', 'summary', 'caption', 'identical'])
    await expect(id(name)).toHaveCount(0);
}
async function settle() {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
const reads = () => requests.filter(r => r.path.startsWith(prefix)).length;
async function select(left, right) {
  await id('left').selectOption(left);
  await id('right').selectOption(right);
}
async function actual(left, right) {
  await id('run').click();
  await expect(id('summary')).toContainText(left);
  await expect(id('summary')).toContainText(right);
  const row = id('change').filter({has: page.locator('code', {hasText: /^label$/})});
  await expect(row).toHaveCount(1);
  await expect(row.locator('td').nth(2)).toHaveText(`LOCAL TEST ONLY ${revisions.indexOf(left) + 1}`);
  await expect(row.locator('td').nth(3)).toHaveText(`LOCAL TEST ONLY ${revisions.indexOf(right) + 1}`);
  await expect(id('error')).toHaveCount(0);
}
async function hold(revision) {
  let arrived;
  const arrival = new Promise(resolve => { arrived = resolve; });
  armed = {path: prefix + revision, arrived};
  return async () => {
    let timer;
    try {
      await Promise.race([arrival, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('Response pause deadline')), 10000);
      })]);
    } finally { clearTimeout(timer); }
  };
}
async function release(status) {
  expect(held.responseStatusCode).toBe(status);
  const event = held;
  held = null;
  const finished = page.waitForResponse(r => new URL(r.url()).pathname === new URL(event.request.url).pathname);
  await cdp.send('Fetch.continueResponse', {requestId: event.requestId});
  const response = await finished;
  expect(response.status()).toBe(status);
  await response.finished();
  await settle();
}
async function tabTo(target) {
  for (let n = 0; n < 100; n++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Keyboard target not reachable');
}
async function keyboardSelect(target, value) {
  await target.focus();
  const index = await target.evaluate((el, v) => [...el.options].findIndex(o => o.value === v), value);
  expect(index).toBeGreaterThanOrEqual(0);
  await page.keyboard.press('Home');
  for (let n = 0; n < index; n++) await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Tab');
  await expect(target).toHaveValue(value);
}
try {
  browser = await chromium.launch({headless: true, timeout: 20000,
    ...(executable ? {executablePath: executable} : {})});
  version = browser.version();
  context = await browser.newContext({viewport: {width: 1280, height: 900}});
  await context.tracing.start({screenshots: true, snapshots: true, sources: false});
  page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.setDefaultNavigationTimeout(15000);
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => requests.push({path: new URL(request.url()).pathname,
    origin: new URL(request.url()).origin, method: request.method(),
    csrf: Boolean(request.headers()['x-krellbot-csrf'])}));
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('bootstrap_session_csrf', async () => {
    const response = await bootstrap;
    expect(response.status()).toBe(200);
    expect((await response.json()).csrf_token.length).toBeGreaterThan(0);
    expect((await context.cookies()).some(c => c.name === 'krellbot_session' && c.httpOnly)).toBe(true);
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
  });
  const nav = page.getByRole('navigation', {name: 'Workstation navigation'});
  await tabTo(nav.getByRole('button', {name: 'Strategies', exact: true}));
  await page.keyboard.press('Enter');
  await tabTo(page.getByTestId('library-toggle'));
  await page.keyboard.press('Enter');
  const opener = page.getByTestId('library-row').filter({hasText: b}).getByTestId('library-row-compare');
  await tabTo(opener);
  await page.keyboard.press('Enter');
  await expect(id('left')).toHaveValue(a);
  await expect(id('right')).toHaveValue(b);
  await check('initial_actual_diff', () => actual(a, b));
  await page.screenshot({path: `${out}/initial-difference.png`, fullPage: true});
  for (const side of ['left', 'right']) {
    await select(a, b);
    await actual(a, b);
    const before = reads();
    await id(side).selectOption(c);
    await check(`completed_${side}_clears`, idle);
    await settle();
    expect(reads()).toBe(before);
  }
  cdp = await context.newCDPSession(page);
  cdp.on('Fetch.requestPaused', async event => {
    if (armed && new URL(event.request.url).pathname === armed.path) {
      held = event;
      pauses.push({path: armed.path, status: event.responseStatusCode, stage: 'Response'});
      const arrival = armed.arrived;
      armed = null;
      arrival();
    } else {
      await cdp.send('Fetch.continueResponse', {requestId: event.requestId}).catch(error => errors.push(String(error)));
    }
  });
  await cdp.send('Fetch.enable', {patterns: [{urlPattern: `*${prefix}*`, requestStage: 'Response'}]});
  for (const outcome of ['success', 'failure']) {
    for (const side of ['left', 'right']) {
      await select(a, b);
      if (outcome === 'failure') {
        fs.renameSync(missingPath, `${missingPath}.held`);
        hidden = true;
      }
      const arrived = await hold(b);
      await id('run').click();
      await arrived();
      await expect(id('loading')).toBeVisible();
      const before = reads();
      await id(side).selectOption(c);
      await idle();
      await page.screenshot({path: `${out}/pending-${outcome}-${side}.png`, fullPage: true});
      await release(outcome === 'success' ? 200 : 404);
      await check(`delayed_${outcome}_${side}_ignored`, idle);
      expect(reads()).toBe(before);
      if (outcome === 'failure') {
        await id('right').selectOption(b);
        if (side === 'right') await id('left').selectOption(a);
        await id('run').click();
        await expect(id('error')).toContainText('library open failed: 404');
        await expect(id('changes')).toHaveCount(0);
        await id('right').selectOption(c);
        await check('real_failure_visible_and_cleared', idle);
        fs.renameSync(`${missingPath}.held`, missingPath);
        hidden = false;
      }
      const left = await id('left').inputValue(), right = await id('right').inputValue();
      // A new explicit Compare must fetch and render exact values for the new pair.
      if (left === right) await select(a, c);
      await actual(await id('left').inputValue(), await id('right').inputValue());
    }
  }
  await check('fresh_compare_actual_results', async () => {
    await select(a, c);
    const before = reads();
    await actual(a, c);
    expect(reads() - before).toBe(2);
    await expect(id('changes')).not.toContainText('LOCAL TEST ONLY 2');
  });
  await check('explicit_compare_only', async () => {
    const before = reads();
    await select(c, b);
    await settle();
    await idle();
    expect(reads()).toBe(before);
  });
  await check('empty_and_equal_disabled', async () => {
    const before = reads();
    await select('', b);
    await expect(id('run')).toBeDisabled();
    await idle();
    await select(b, b);
    await expect(id('run')).toBeDisabled();
    await expect(id('hint')).toBeVisible();
    expect(reads()).toBe(before);
  });
  await check('keyboard_mobile', async () => {
    await page.setViewportSize({width: 390, height: 844});
    await keyboardSelect(id('left'), a);
    await keyboardSelect(id('right'), c);
    await expect(id('run')).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(id('changes')).toContainText('LOCAL TEST ONLY 3');
    await keyboardSelect(id('left'), b);
    await idle();
    diagnostics.mobile_geometry = await page.evaluate(() => ({viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth}));
    await page.screenshot({path: `${out}/mobile-keyboard-cleared.png`, fullPage: true});
  });
  await check('unmount_pending_ignored', async () => {
    await select(a, b);
    const arrived = await hold(b);
    await id('run').click();
    await arrived();
    await id('close').click();
    await expect(page.getByTestId('revision-compare')).toHaveCount(0);
    await release(200);
    await opener.click();
    await idle();
    await actual(a, b);
  });
  await check('live_off_unarmed', async () => {
    const state = await page.evaluate(async () => (await fetch('/api/v1/operations')).json());
    expect(state.live.live_enabled).toBe(false);
    expect(state.deployments).toEqual([]);
  });
  await check('read_only_requests', async () => {
    expect(requests.filter(r => r.method !== 'GET').map(r => r.path)).toEqual(['/api/v1/session/bootstrap']);
    const drafts = requests.filter(r => r.path.startsWith(prefix));
    expect(drafts.length).toBeGreaterThan(10);
    expect(drafts.every(r => r.method === 'GET' && r.csrf)).toBe(true);
  });
  await check('loopback_only', async () => expect(requests.every(r => r.origin === new URL(url).origin)).toBe(true));
  await check('no_browser_errors', async () => expect(errors).toEqual([]));
  await page.screenshot({path: `${out}/final-fresh-difference.png`, fullPage: true});
} catch (error) {
  assertions.failure = String(error.stack || error);
  process.exitCode = 1;
  if (page) await page.screenshot({path: `${out}/failure.png`, fullPage: true}).catch(() => {});
} finally {
  if (hidden) fs.renameSync(`${missingPath}.held`, missingPath);
  if (held && cdp) await cdp.send('Fetch.continueResponse', {requestId: held.requestId}).catch(() => {});
  if (context) await context.tracing.stop({path: `${out}/trace.zip`}).catch(() => {});
  if (browser) await browser.close();
  fs.writeFileSync(`${out}/browser.json`, JSON.stringify({assertions, requests, pauses, errors, diagnostics, version}, null, 2));
}
'''


def clean_env(home: Path) -> dict[str, str]:
    names = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "USERPROFILE",
             "LOCALAPPDATA", "PLAYWRIGHT_BROWSERS_PATH")
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update(KRELLBOT_HOME=str(home), KRELLBOT_ENABLE_LIVE="0", PYTHONUNBUFFERED="1",
               PYTHONPATH=str(ROOT / "src"), FRONTEND_PACKAGE=str(FRONTEND / "package.json"))
    return env


def snapshot(home: Path) -> dict[str, str]:
    return {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
            for directory in ("drafts", "packs", "run", "journal")
            for p in sorted((home / directory).rglob("*")) if p.is_file()}


def main() -> int:
    out = Path(tempfile.mkdtemp(prefix="compare-selection-race-"))
    summary = {"qualified": False, "required_assertions": dict.fromkeys(REQUIRED, False),
               "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                                     text=True, timeout=10).strip(),
               "source_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT,
                                                        text=True, timeout=10),
               "commands": [], "output_dir": str(out),
               "delay_mechanism": "CDP Response-stage pause/continue of genuine backend HTTP; no substituted responses",
               "fixtures": "LOCAL TEST ONLY non-runnable draft revisions; one temporarily hidden for real 404"}

    def run(argv: list[str], cwd: Path, env: dict[str, str], name: str, timeout: int) -> int:
        record = {"argv": argv, "cwd": str(cwd), "log": str(out / name), "timeout_seconds": timeout}
        summary["commands"].append(record)
        with (out / name).open("w") as log:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            record["pid"] = proc.pid
            try:
                record["exit"] = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record["exit"] = 124
                log.write("\nFinite command deadline exceeded\n")
            finally:
                # The owned process group also contains Chromium if Node hits its deadline.
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)
                record["reaped"] = proc.poll() is not None
        return record["exit"]

    try:
        source = ["frontend/src/features/strategies/RevisionCompare.tsx",
                  "frontend/src/features/strategies/RevisionCompare.selectionRace.test.tsx",
                  "scripts/verify_compare_selection_race.py"]
        summary["source_hashes"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source}
        browser_file = out / "journey.mjs"
        browser_file.write_text(BROWSER)
        with tempfile.TemporaryDirectory(prefix="krellbot-compare-home-") as temp:
            home = Path(temp)
            env = clean_env(home)
            prior = dict(os.environ)
            try:
                os.environ.clear()
                os.environ.update(env)
                paths.ensure_layout()
                service = StrategyDraftService(home)
                pack = {"id": "LOCAL-TEST-COMPARE", "label": "LOCAL TEST ONLY 1", "timeframe": "1h"}
                first = service.create(pack)["revision_id"]
                second = service.edit(first, {**pack, "label": "LOCAL TEST ONLY 2"})["revision_id"]
                third = service.edit(second, {**pack, "label": "LOCAL TEST ONLY 3"})["revision_id"]
                missing_path = service.revision_path(second)
                assert not config.load_config(home).armed
                assert all(not item["runnable"] for item in service.list_owned_summaries())
            finally:
                os.environ.clear()
                os.environ.update(prior)
            before = snapshot(home)
            assert run(["npm", "run", "build"], FRONTEND, env, "build.log", 120) == 0
            argv = [sys.executable, "-m", "krellbot.cli", "workstation", "--dist", str(FRONTEND / "dist")]
            record = {"argv": argv, "cwd": str(ROOT), "log": str(out / "backend.log"),
                      "timeout_seconds": 215, "cleanup": "terminate owned PID in finally, wait 10s, kill then wait 5s"}
            summary["commands"].append(record)
            with (out / "backend.log").open("w") as log:
                proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                record["pid"] = proc.pid
                try:
                    deadline = time.monotonic() + 20
                    url = None
                    while time.monotonic() < deadline:
                        match = re.search(r"Workstation running at (http://127\.0\.0\.1:\d+/)",
                                          (out / "backend.log").read_text())
                        if match:
                            url = match[1]
                            break
                        if proc.poll() is not None:
                            break
                        time.sleep(0.1)
                    assert url, "Backend startup deadline failed; see backend.log"
                    env["COMPARE_VERIFY_CONFIG"] = json.dumps({
                        "url": url, "out": str(out), "revisions": [first, second, third],
                        "missingPath": str(missing_path),
                        "executable": shutil.which("chromium") or shutil.which("chromium-browser"),
                    })
                    browser_exit = run(["node", str(browser_file)], ROOT, env, "browser.log", 180)
                    browser = json.loads((out / "browser.json").read_text())
                    for name in REQUIRED:
                        if name in browser["assertions"]:
                            summary["required_assertions"][name] = browser["assertions"][name] is True
                    summary["browser_version"] = browser["version"]
                    summary["diagnostics"] = browser["diagnostics"]
                    assert browser_exit == 0, browser["assertions"].get("failure", "Browser failed")
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                    try:
                        record["exit"] = proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        record["exit"] = proc.wait(timeout=5)
                    record["reaped"] = proc.poll() is not None
            after = snapshot(home)
            (out / "storage-hashes.json").write_text(json.dumps({"before": before, "after": after}, indent=2))
            summary["required_assertions"]["storage_unchanged"] = before == after
            summary["qualified"] = all(summary["required_assertions"].values()) and all(
                command.get("exit") == 0 and command.get("reaped") is True
                for command in summary["commands"]
            )
    except Exception:
        summary["failure"] = traceback.format_exc()
    finally:
        summary["exit_code"] = 0 if summary["qualified"] else 1
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
