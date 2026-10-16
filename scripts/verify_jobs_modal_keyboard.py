#!/usr/bin/env python3
"""Qualify the mounted Jobs modal using a real loopback backend and Chromium.

Run with uv run --frozen python scripts/verify_jobs_modal_keyboard.py.
Artifacts default to a fresh directory in the system temp directory. No platform
qualification beyond the actual recorded host is implied. The labelled fixture is
a deliberately missing local research pack submitted through the real API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

from krellbot import config

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
ASSERTIONS = [
    "bootstrap_session_csrf", "keyboard_open_focus", "empty_tab_cycle",
    "loading_tab_cycle", "populated_tab_cycle", "error_tab_cycle",
    "retry_focus_recovery", "escape_restores", "close_restores", "reopen_focus",
    "background_keyboard_blocked", "refresh_snapshot", "csv_export",
    "session_failure_visible", "retry_recovers", "mobile_tab_cycle",
    "listeners_removed_after_close", "loopback_only", "no_trading_requests",
    "live_disabled_no_armed_records", "history_unchanged",
]

BROWSER = r'''
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const { chromium, expect } = require('@playwright/test');
const [url, out] = process.argv.slice(2);
const results = {};
const requests = [];
const focusLog = [];
const runtime = {};
let browser;
let page;
let context;
async function check(name, action) {
  await action();
  results[name] = true;
}
async function tabTo(locator) {
  for (let i = 0; i < 100; i++) {
    if (await locator.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Keyboard target unreachable');
}
const id = name => page.getByTestId(name);
const dialog = () => page.getByRole('dialog', {name:'Jobs', exact:true});
const close = () => page.getByRole('button', {name:'Close jobs drawer'});
const trigger = () => page.getByRole('button', {name:'Jobs', exact:true});
async function cycle(state, targets) {
  await tabTo(close());
  for (const direction of ['Tab', 'Shift+Tab']) {
    let index = 0;
    for (let i = 0; i < targets.length * 2; i++) {
      await page.keyboard.press(direction);
      index = (index + (direction === 'Tab' ? 1 : targets.length - 1)) % targets.length;
      await expect(targets[index]).toBeFocused();
      expect(await dialog().evaluate(el => el.contains(document.activeElement))).toBe(true);
      focusLog.push({state, direction, target: await page.evaluate(() => ({
        tag:document.activeElement.tagName, text:document.activeElement.textContent,
        testid:document.activeElement.getAttribute('data-testid'),
      }))});
    }
  }
}
try {
  browser = await chromium.launch({headless:true,
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath:process.env.CHROMIUM_EXECUTABLE} : {})});
  runtime.browser_version = browser.version();
  runtime.chromium_executable = process.env.CHROMIUM_EXECUTABLE || "Playwright bundled Chromium";
  context = await browser.newContext({viewport:{width:1100,height:760}, acceptDownloads:true});
  page = await context.newPage();
  page.setDefaultTimeout(8000);
  page.setDefaultNavigationTimeout(15000);
  await context.tracing.start({screenshots:true, snapshots:true});
  page.on('request', request => requests.push({path:new URL(request.url()).pathname,
    origin:new URL(request.url()).origin, method:request.method(),
    csrf_present:!!request.headers()['x-krellbot-csrf']}));
  page.on('response', response => {
    const entry = [...requests].reverse().find(r => r.path === new URL(response.url()).pathname && r.status === undefined);
    if (entry) entry.status = response.status();
  });
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  const response = await bootstrap;
  const session = await response.json();
  await check('bootstrap_session_csrf', async () => {
    expect(response.status()).toBe(200);
    expect(typeof session.csrf_token).toBe('string');
    expect(session.csrf_token.length).toBeGreaterThan(0);
    expect((await context.cookies()).some(c => c.httpOnly && c.value.length > 0)).toBe(true);
    await expect(id('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
  });
  await tabTo(trigger());
  await check('keyboard_open_focus', async () => {
    await page.keyboard.press('Enter');
    await expect(dialog()).toBeVisible();
    await expect(close()).toBeFocused();
  });
  await expect(id('jobs-empty')).toBeVisible();
  await check('empty_tab_cycle', async () => {
    await expect(id('jobs-drawer-csv-export')).toBeDisabled();
    await cycle('empty', [close(), id('jobs-refresh')]);
  });
  await page.screenshot({path:`${out}/empty.png`, fullPage:true});
  await check('background_keyboard_blocked', async () => {
    const nav = page.getByRole('navigation', {name:'Workstation navigation'});
    const before = await nav.innerText();
    await page.evaluate(() => {
      window.jobsKeyboardBackgroundClicks = [];
      document.addEventListener('click', event => {
        if (!event.target.closest('#kbot-jobs-drawer')) {
          window.jobsKeyboardBackgroundClicks.push(event.target.textContent);
        }
      }, {capture:true});
    });
    await page.keyboard.press('Control+k');
    await page.keyboard.press('Meta+k');
    await expect(id('command-palette')).toHaveCount(0);
    await id('kbot-shell-brand').evaluate(el => el.focus());
    await expect(close()).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(id('jobs-refresh')).toBeFocused();
    await page.keyboard.press('Space');
    await expect(id('jobs-empty')).toBeVisible();
    expect(await nav.innerText()).toBe(before);
    expect(await page.evaluate(() => window.jobsKeyboardBackgroundClicks)).toEqual([]);
    await expect(dialog()).toBeVisible();
  });
  await check('escape_restores', async () => {
    await page.keyboard.press('Escape');
    await expect(dialog()).toHaveCount(0);
    await expect(trigger()).toBeFocused();
  });
  await check('reopen_focus', async () => {
    await page.keyboard.press('Space');
    await expect(close()).toBeFocused();
    await expect(id('jobs-empty')).toBeVisible();
  });
  // CDP delays real HTTP traffic; no responses or production clients are replaced.
  const cdp = await context.newCDPSession(page);
  await cdp.send('Network.enable');
  const latency = ms => cdp.send('Network.emulateNetworkConditions', {
    offline:false, latency:ms, downloadThroughput:-1, uploadThroughput:-1,
  });
  await latency(1800);
  await tabTo(id('jobs-refresh'));
  await page.keyboard.press('Enter');
  await check('loading_tab_cycle', async () => {
    await expect(id('jobs-loading')).toBeVisible();
    await expect(id('jobs-drawer-csv-export')).toBeDisabled();
    await cycle('loading', [close(), id('jobs-refresh')]);
    await expect(id('jobs-loading')).toBeVisible();
  });
  await expect(id('jobs-empty')).toBeVisible();
  await latency(0);
  const fixture = await page.evaluate(async csrf => {
    const response = await fetch('/api/v1/research/jobs', {method:'POST', credentials:'include',
      headers:{'Content-Type':'application/json', 'X-Krellbot-CSRF':csrf},
      body:JSON.stringify({kind:'research.backtest', correlation_id:'LOCAL-JOBS-KEYBOARD-FIXTURE',
        pack_path:'LOCAL-JOBS-KEYBOARD-FIXTURE-missing.json'})});
    return {status:response.status, body:await response.json()};
  }, session.csrf_token);
  expect(fixture.status).toBe(200);
  expect(typeof fixture.body.id).toBe('string');
  fs.writeFileSync(`${out}/fixture.json`, JSON.stringify(fixture, null, 2));
  await tabTo(id('jobs-refresh'));
  await page.keyboard.press('Enter');
  await check('refresh_snapshot', async () => {
    await expect(id('job-row')).toHaveCount(1);
    await expect(id('job-row')).toContainText(fixture.body.id);
    await expect(id('jobs-empty')).toHaveCount(0);
    expect(requests.some(r => r.path === '/api/v1/jobs' && r.status === 200 && r.csrf_present)).toBe(true);
  });
  await check('populated_tab_cycle', async () => {
    await expect(id('jobs-drawer-csv-export')).toBeEnabled();
    await cycle('populated', [close(), id('jobs-refresh'), id('jobs-drawer-csv-export'), id('job-row')]);
  });
  await check('csv_export', async () => {
    await tabTo(id('jobs-drawer-csv-export'));
    const downloaded = page.waitForEvent('download');
    await page.keyboard.press('Enter');
    const download = await downloaded;
    await download.saveAs(`${out}/jobs.csv`);
    expect(fs.readFileSync(`${out}/jobs.csv`, 'utf8')).toContain(fixture.body.id);
  });
  await page.screenshot({path:`${out}/populated.png`, fullPage:true});
  const cookies = await context.cookies();
  await context.clearCookies();
  await tabTo(id('jobs-refresh'));
  await page.keyboard.press('Enter');
  await check('session_failure_visible', async () => {
    await expect(id('jobs-error')).toContainText('Jobs blocked — local-only preview.');
    await expect(id('job-row')).toHaveCount(0);
    await expect(id('jobs-empty')).toHaveCount(0);
    expect(requests.some(r => r.path === '/api/v1/jobs' && r.status === 403)).toBe(true);
  });
  const retry = page.getByRole('button', {name:'Retry', exact:true});
  await check('error_tab_cycle', async () => {
    await expect(id('jobs-drawer-csv-export')).toBeDisabled();
    await cycle('error', [close(), id('jobs-refresh'), retry]);
  });
  await page.screenshot({path:`${out}/session-failure.png`, fullPage:true});
  await context.addCookies(cookies);
  await latency(1800);
  await tabTo(retry);
  await check('retry_focus_recovery', async () => {
    await page.keyboard.press('Enter');
    await expect(id('jobs-loading')).toBeVisible();
    await expect(retry).toHaveCount(0);
    await page.keyboard.press('Tab');
    await expect(close()).toBeFocused();
  });
  await check('retry_recovers', async () => {
    await expect(id('job-row')).toContainText(fixture.body.id);
    await expect(id('jobs-error')).toHaveCount(0);
  });
  await latency(0);
  await check('close_restores', async () => {
    await tabTo(close());
    await page.keyboard.press('Enter');
    await expect(dialog()).toHaveCount(0);
    await expect(trigger()).toBeFocused();
  });
  await check('listeners_removed_after_close', async () => {
    await page.keyboard.press('Control+k');
    await expect(id('command-palette')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(id('command-palette')).toHaveCount(0);
    await expect(trigger()).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(trigger()).not.toBeFocused();
  });
  await page.setViewportSize({width:390, height:844});
  await tabTo(trigger());
  await page.keyboard.press('Enter');
  await expect(id('job-row')).toBeVisible();
  await check('mobile_tab_cycle', async () => {
    await cycle('mobile', [close(), id('jobs-refresh'), id('jobs-drawer-csv-export'), id('job-row')]);
    await page.screenshot({path:`${out}/mobile.png`, fullPage:true});
    await page.keyboard.press('Escape');
    await expect(trigger()).toBeFocused();
    await expect(dialog()).toHaveCount(0);
  });
  await check('loopback_only', async () => {
    expect(requests.every(r => r.origin === new URL(url).origin)).toBe(true);
  });
  await check('no_trading_requests', async () => {
    expect(requests.filter(r => r.method !== 'GET').map(r => r.path)).toEqual([
      '/api/v1/session/bootstrap', '/api/v1/research/jobs',
    ]);
  });
} catch (error) {
  results.error = String(error.stack || error);
  if (page) await page.screenshot({path:`${out}/failure.png`,fullPage:true,timeout:5000}).catch(() => {});
  process.exitCode = 1;
} finally {
  fs.writeFileSync(`${out}/browser.json`, JSON.stringify({results, requests, focusLog, runtime}, null, 2));
  if (context) await context.tracing.stop({path:`${out}/trace.zip`}).catch(() => {});
  if (browser) await browser.close();
}
'''


def clean_env(home: Path) -> dict[str, str]:
    names = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "USERPROFILE",
             "LOCALAPPDATA", "PLAYWRIGHT_BROWSERS_PATH")
    env = {key: os.environ[key] for key in names if key in os.environ}
    env.update(KRELLBOT_HOME=str(home), KRELLBOT_ENABLE_LIVE="0",
               PYTHONUNBUFFERED="1", PYTHONPATH=str(ROOT / "src"),
               FRONTEND_PACKAGE=str(FRONTEND / "package.json"))
    chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    if chromium:
        env["CHROMIUM_EXECUTABLE"] = chromium
    return env


def stop_owned(proc: subprocess.Popen) -> int:
    # Each child owns a new process group, including any Chromium descendants.
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        return proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        return proc.wait(timeout=5)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def snapshot(home: Path) -> dict[str, str]:
    return {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ("journal", "run") for p in sorted((home / folder).rglob("*")) if p.is_file()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="jobs-modal-keyboard-"))
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip(),
        "source_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True, timeout=10),
        "platform": platform.platform(), "qualified": False,
        "required_assertions": {name: False for name in ASSERTIONS}, "commands": [],
        "fixtures": "LOCAL-JOBS-KEYBOARD-FIXTURE: missing local pack submitted through real research API",
    }

    def run(argv: list[str], cwd: Path, env: dict[str, str], log: Path) -> int:
        record = {"argv": argv, "cwd": str(cwd), "log": str(log), "exit": None, "timeout_seconds": 180}
        summary["commands"].append(record)
        with log.open("w") as stream:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            record["pid"] = proc.pid
            try:
                record["exit"] = proc.wait(timeout=180)
            finally:
                record["cleanup_exit"] = stop_owned(proc)
        return record["exit"]

    try:
        files = ["frontend/src/shell/JobsDrawer.tsx", "frontend/src/shell/JobsDrawer.keyboardModal.test.tsx",
                 "scripts/verify_jobs_modal_keyboard.py"]
        summary["source_hashes"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files}
        browser_file = out / "journey.mjs"
        browser_file.write_text(BROWSER)
        with tempfile.TemporaryDirectory(prefix="krellbot-jobs-keyboard-") as temp:
            home = Path(temp)
            env = clean_env(home)
            before = snapshot(home)
            live_off_before = env["KRELLBOT_ENABLE_LIVE"] == "0" and not config.load_config(home).armed
            assert live_off_before
            assert run(["npm", "run", "build"], FRONTEND, env, out / "build.log") == 0
            argv = [sys.executable, "-m", "krellbot.cli", "workstation", "--dist", str(FRONTEND / "dist")]
            record = {"argv": argv, "cwd": str(ROOT), "exit": None, "log": str(out / "backend.log"),
                      "timeout_seconds": 220, "cleanup": "owned process group SIGTERM; bounded wait then SIGKILL"}
            summary["commands"].append(record)
            with (out / "backend.log").open("w") as stream:
                proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stream,
                                        stderr=subprocess.STDOUT, start_new_session=True)
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
                    assert url, "Real backend failed to start; see backend.log"
                    summary["loopback_url"] = url
                    code = run(["node", str(browser_file), url, str(out)], ROOT, env, out / "browser.log")
                    data = json.loads((out / "browser.json").read_text())
                    summary["browser_results"] = data["results"]
                    summary["runtime"] = data["runtime"]
                    for name in ASSERTIONS:
                        if name in data["results"]:
                            summary["required_assertions"][name] = data["results"][name] is True
                    assert code == 0, data["results"].get("error", "Browser failed")
                finally:
                    record["exit"] = stop_owned(proc)
            after = snapshot(home)
            (out / "storage-hashes.json").write_text(json.dumps({"before": before, "after": after}, indent=2))
            summary["required_assertions"]["history_unchanged"] = before == after
            summary["required_assertions"]["live_disabled_no_armed_records"] = (
                live_off_before and not config.load_config(home).armed and env["KRELLBOT_ENABLE_LIVE"] == "0")
        summary["qualified"] = all(summary["required_assertions"].values()) and all(
            item["exit"] == 0 for item in summary["commands"])
    except Exception:
        summary["error"] = traceback.format_exc()
    finally:
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps({"qualified": summary["qualified"], "artifact": str(out / "summary.json"),
                          "error": summary.get("error")}, indent=2))
    return 0 if summary["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
