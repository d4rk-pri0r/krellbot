#!/usr/bin/env python3
"""Qualify virtual trace access against the real loopback server and Chromium.

Artifacts contain private loopback session evidence; do not publish them.
"""
from __future__ import annotations

import argparse
import csv
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

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
ASSERTIONS = (
    "bootstrap_session_csrf", "empty_initial", "real_job_failure", "real_long_trace",
    "initially_unmounted", "native_tab_enter", "end_focus_alignment", "last_boundary",
    "last_inspector_space", "home_focus_alignment", "first_boundary", "first_inspector_enter",
    "arrows_cross_windows", "focus_retained", "unrelated_key", "mouse_scroll_click",
    "session_export_failure_preserves_result", "narrow_keyboard", "loopback_only", "no_trading_requests", "live_off",
)
BROWSER = r'''
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const { chromium, expect } = require('@playwright/test');
const [url, home, out, baseline] = process.argv.slice(2);
const results = {};
const requests = [];
const observed = {};
let browser, page, context;
const id = name => page.getByTestId(`research-${name}`);
const row = i => id('trace-scroll').getByRole('button', {name: String(i * 3600000), exact: true});
async function check(name, action) { await action(); results[name] = true; }
async function tabTo(target) {
  for (let i = 0; i < 180; i++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Tab target unreachable');
}
async function aligned(i) {
  await expect(row(i)).toBeFocused();
  expect(await row(i).evaluate(el => {
    const parent = el.closest('[data-testid="research-trace-scroll"]').getBoundingClientRect();
    const rect = el.getBoundingClientRect();
    return rect.top >= parent.top - 1 && rect.bottom <= parent.bottom + 1;
  })).toBe(true);
  (observed.navigation ??= []).push(await row(i).evaluate((el, index) => ({
    index, label: el.textContent, focused: el === document.activeElement,
    scrollTop: el.closest('[data-testid="research-trace-scroll"]').scrollTop,
  }), i));
}
try {
  browser = await chromium.launch({headless: true, timeout: 15000,
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {})});
  context = await browser.newContext({viewport: {width: 1100, height: 900}});
  await context.tracing.start({screenshots: true, snapshots: true, sources: false});
  page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.setDefaultNavigationTimeout(15000);
  page.on('request', r => requests.push({path: new URL(r.url()).pathname,
    origin: new URL(r.url()).origin, method: r.method(), csrf: !!r.headers()['x-krellbot-csrf']}));
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('bootstrap_session_csrf', async () => {
    const response = await bootstrap;
    expect(response.status()).toBe(200);
    expect((await response.json()).csrf_token.length).toBeGreaterThan(0);
    expect((await context.cookies()).some(c => c.httpOnly && c.name === 'krellbot_session')).toBe(true);
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
  });
  await tabTo(page.getByRole('navigation', {name: 'Workstation navigation'}).getByRole('button', {name: 'Research', exact: true}));
  await page.keyboard.press('Enter');
  await check('empty_initial', async () => {
    await expect(id('state-empty')).toBeVisible();
    await expect(id('trace-scroll')).toHaveCount(0);
    await expect(id('bar-detail')).toHaveCount(0);
  });
  await page.getByLabel(/pack path/i).fill(`${home}/LOCAL-KEYBOARD-FIXTURE.json`);
  await page.getByLabel(/dataset path/i).fill(`${home}/MISSING-TEST-DATA.csv`);
  await page.getByLabel(/fee basis points/i).fill('40');
  await page.getByLabel(/^from$/i).fill('0');
  await page.getByLabel(/^to$/i).fill(String(199 * 3600000));
  await tabTo(page.getByRole('button', {name: 'Run', exact: true}));
  await page.keyboard.press('Enter');
  await check('real_job_failure', async () => {
    await expect(id('job-error')).toBeVisible({timeout: 20000});
    await expect(id('result')).toHaveCount(0);
    await page.screenshot({path: `${out}/job-failure.png`, fullPage: true});
  });
  await page.getByLabel(/dataset path/i).fill(`${home}/LOCAL-KEYBOARD-FIXTURE.csv`);
  const resultResponse = page.waitForResponse(r => /\/api\/v1\/jobs\/[^/]+\/result$/.test(r.url()) && r.status() === 200);
  await tabTo(page.getByRole('button', {name: 'Run', exact: true}));
  await page.keyboard.press('Enter');
  const stored = await (await resultResponse).json();
  fs.writeFileSync(`${out}/real-result.json`, JSON.stringify(stored, null, 2));
  await check('real_long_trace', async () => {
    await expect(id('result')).toBeVisible();
    expect(stored.trace.length).toBe(200);
    expect(stored.trace[199].bar_ts).toBe(199 * 3600000);
    await expect(id('trace-count')).toHaveText('200');
  });
  await check('initially_unmounted', async () => {
    await expect(row(199)).toHaveCount(0);
    expect(await id('trace-scroll').getByRole('button').count()).toBeLessThan(200);
  });
  await tabTo(row(0));
  await check('native_tab_enter', async () => {
    await page.keyboard.press('Tab');
    await expect(row(1)).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(row(0)).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(id('bar-detail')).toContainText(`close: ${stored.trace[0].input.close}`);
  });
  if (baseline === 'true') {
    await page.keyboard.press('End');
    await page.waitForTimeout(150);
    observed.end = await page.evaluate(() => ({focus: document.activeElement?.tagName === 'BUTTON' ? document.activeElement.textContent : document.activeElement?.tagName,
      top: document.querySelector('[data-testid="research-trace-scroll"]').scrollTop}));
    observed.end_reached_last = await row(199).evaluateAll(els => els.some(el => el === document.activeElement));
    await id('trace-scroll').evaluate(el => { el.scrollTop = 0; });
    await expect(row(0)).toBeVisible();
    await tabTo(row(0));
    for (let i = 0; i < 205; i++) await page.keyboard.press('ArrowDown');
    observed.arrow_down = await page.evaluate(() => ({focus: document.activeElement?.tagName === 'BUTTON' ? document.activeElement.textContent : document.activeElement?.tagName,
      top: document.querySelector('[data-testid="research-trace-scroll"]').scrollTop}));
    observed.arrow_down_reached_last = await row(199).evaluateAll(els => els.some(el => el === document.activeElement));
    await page.screenshot({path: `${out}/baseline-unreachable.png`, fullPage: true});
    throw new Error('Baseline probe complete: ' + JSON.stringify(observed));
  }
  await check('end_focus_alignment', async () => { await page.keyboard.press('End'); await aligned(199); });
  await check('last_boundary', async () => { await page.keyboard.press('ArrowDown'); await aligned(199); });
  await check('last_inspector_space', async () => {
    await page.keyboard.press('Space');
    await expect(id('bar-detail')).toContainText(`close: ${stored.trace[199].input.close}`);
    for (const condition of stored.trace[199].conditions) await expect(id('bar-detail')).toContainText(condition.path);
    await expect(row(199)).toHaveAttribute('aria-pressed', 'true');
    await aligned(199);
    await page.screenshot({path: `${out}/last-selected.png`, fullPage: true});
  });
  await check('home_focus_alignment', async () => { await page.keyboard.press('Home'); await aligned(0); });
  await check('first_boundary', async () => { await page.keyboard.press('ArrowUp'); await aligned(0); });
  await check('first_inspector_enter', async () => {
    await page.keyboard.press('Enter');
    await expect(id('bar-detail')).toContainText(`close: ${stored.trace[0].input.close}`);
    await expect(row(0)).toHaveAttribute('aria-pressed', 'true');
    await page.screenshot({path: `${out}/first-selected.png`, fullPage: true});
  });
  await check('arrows_cross_windows', async () => {
    for (let i = 1; i < 200; i++) { await page.keyboard.press('ArrowDown'); await aligned(i); }
    await page.keyboard.press('Enter');
    await expect(id('bar-detail')).toContainText(`close: ${stored.trace[199].input.close}`);
    for (let i = 198; i >= 0; i--) { await page.keyboard.press('ArrowUp'); await aligned(i); }
  });
  await check('focus_retained', async () => {
    await aligned(0);
    await page.keyboard.press('End'); await aligned(199);
    await page.keyboard.press('Home'); await aligned(0);
  });
  await check('unrelated_key', async () => { await page.keyboard.press('Escape'); await aligned(0); });
  await check('narrow_keyboard', async () => {
    await page.setViewportSize({width: 390, height: 844});
    await page.keyboard.press('End'); await aligned(199);
    await page.keyboard.press('Space');
    await expect(id('bar-detail')).toContainText(`close: ${stored.trace[199].input.close}`);
    await page.keyboard.press('Home'); await aligned(0);
    await page.screenshot({path: `${out}/narrow-keyboard.png`, fullPage: true});
    await page.setViewportSize({width: 1100, height: 900});
  });
  await check('mouse_scroll_click', async () => {
    await id('trace-scroll').hover();
    await page.mouse.wheel(0, 4800);
    await expect(row(199)).toBeVisible();
    await row(199).click();
    await expect(id('bar-detail')).toContainText(`close: ${stored.trace[199].input.close}`);
  });
  await check('session_export_failure_preserves_result', async () => {
    await context.clearCookies();
    const denied = page.waitForResponse(r => /\/result\/download$/.test(r.url()) && r.status() === 403);
    await tabTo(page.getByRole('button', {name: 'Export result', exact: true}));
    await page.keyboard.press('Enter'); await denied;
    await expect(id('export-error')).toContainText('403');
    await expect(id('bar-detail')).toContainText(`close: ${stored.trace[199].input.close}`);
    await page.keyboard.press('Shift+Tab');
    await expect(id('trace-scroll').getByRole('button').last()).toBeFocused();
    await page.keyboard.press('Home'); await aligned(0);
    await page.screenshot({path: `${out}/session-failure.png`, fullPage: true});
  });
  await check('loopback_only', async () => { expect(requests.every(r => r.origin === new URL(url).origin)).toBe(true); });
  await check('no_trading_requests', async () => {
    expect(requests.filter(r => r.method !== 'GET').map(r => r.path)).toEqual([
      '/api/v1/session/bootstrap', '/api/v1/research/jobs', '/api/v1/research/jobs']);
    expect(requests.filter(r => r.path === '/api/v1/research/jobs').every(r => r.csrf)).toBe(true);
  });
} catch (error) {
  results.error = String(error.stack || error);
  if (page) await page.screenshot({path: `${out}/failure.png`, fullPage: true}).catch(() => {});
  process.exitCode = 1;
} finally {
  fs.writeFileSync(`${out}/browser.json`, JSON.stringify({results, observed, requests}, null, 2));
  if (context) await context.tracing.stop({path: `${out}/trace.zip`}).catch(() => {});
  if (browser) await browser.close();
}
'''


def clean_env(home: Path) -> dict[str, str]:
    names = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "USERPROFILE", "LOCALAPPDATA", "PLAYWRIGHT_BROWSERS_PATH")
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update(KRELLBOT_HOME=str(home), KRELLBOT_ENABLE_LIVE="0", PYTHONUNBUFFERED="1",
               PYTHONPATH=str(ROOT / "src"), FRONTEND_PACKAGE=str(FRONTEND / "package.json"))
    executable = shutil.which("chromium") or shutil.which("chromium-browser")
    if executable:
        env["CHROMIUM_EXECUTABLE"] = executable
    return env


def seed(home: Path) -> None:
    pack = {
        "schema_version": 1, "id": "local-keyboard-fixture", "version": "1.0.0",
        "label": "LOCAL KEYBOARD FIXTURE ONLY", "author": "Krellbot runtime verifier",
        "timeframe": "1h", "origin": "Synthetic offline keyboard acceptance fixture, not investment evidence",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"], "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    (home / "LOCAL-KEYBOARD-FIXTURE.json").write_text(json.dumps(pack))
    with (home / "LOCAL-KEYBOARD-FIXTURE.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for i in range(200):
            close = 100 + i
            writer.writerow([i * 3600000, close, close + 1, close - 1, close, 100])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--baseline-probe", action="store_true")
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="research-trace-keyboard-"))
    out.mkdir(parents=True, exist_ok=True)
    summary = {"qualified": False, "required_assertions": {name: False for name in ASSERTIONS},
               "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip(),
               "source_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True, timeout=10),
               "commands": [], "baseline_probe": args.baseline_probe,
               "fixture": "200 synthetic hourly CSV bars; real engine, API and UI; no keys or orders"}

    def run(argv: list[str], cwd: Path, env: dict[str, str], log: Path, timeout: int = 180) -> int:
        record = {"argv": argv, "cwd": str(cwd), "log": str(log), "exit": None}
        summary["commands"].append(record)
        with log.open("w") as stream:
            child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                record["exit"] = child.wait(timeout=timeout)
            finally:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait(timeout=5)
                # A timed-out Node process cannot run its Chromium finally block.
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                record["exit"] = child.returncode
        return record["exit"]

    try:
        files = ["frontend/src/features/research/ResearchView.tsx", "frontend/src/features/research/ResearchView.traceVirtualKeyboard.test.tsx", "scripts/verify_research_trace_virtual_keyboard.py"]
        summary["source_hashes"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}
        browser_file = out / "journey.mjs"
        browser_file.write_text(BROWSER)
        with tempfile.TemporaryDirectory(prefix="krellbot-trace-isolated-") as temp:
            home = Path(temp)
            home.chmod(0o700)
            env = clean_env(home)
            seed(home)
            assert run(["npm", "run", "build"], FRONTEND, env, out / "build.log") == 0
            argv = [sys.executable, "-m", "krellbot.cli", "workstation", "--dist", str(FRONTEND / "dist")]
            record = {"argv": argv, "cwd": str(ROOT), "log": str(out / "backend.log"), "exit": None, "cleanup": "owned PID terminate/wait/kill"}
            summary["commands"].append(record)
            with (out / "backend.log").open("w") as stream:
                proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 25
                    url = None
                    while time.monotonic() < deadline:
                        match = re.search(r"Workstation running at (http://127\.0\.0\.1:\d+/)", (out / "backend.log").read_text())
                        if match:
                            url = match[1]
                            break
                        if proc.poll() is not None:
                            break
                        time.sleep(0.1)
                    assert url, "Real backend failed to start"
                    code = run(["node", str(browser_file), url, str(home), str(out), str(args.baseline_probe).lower()], ROOT, env, out / "browser.log")
                    data = json.loads((out / "browser.json").read_text())
                    summary["browser"] = data
                    for name in ASSERTIONS:
                        summary["required_assertions"][name] = data["results"].get(name) is True
                    from krellbot import config
                    summary["required_assertions"]["live_off"] = env["KRELLBOT_ENABLE_LIVE"] == "0" and not config.load_config(home).armed
                    assert code == 0, data["results"].get("error", "Browser failed")
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                    try:
                        record["exit"] = proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        record["exit"] = proc.wait(timeout=5)
            summary["qualified"] = all(summary["required_assertions"].values()) and all(c["exit"] == 0 for c in summary["commands"])
    except Exception:
        summary["error"] = traceback.format_exc()
    finally:
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps({"qualified": summary["qualified"], "artifact": str(out / "summary.json"), "error": summary.get("error")}, indent=2))
    return 0 if summary["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
