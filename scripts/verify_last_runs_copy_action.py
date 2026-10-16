#!/usr/bin/env python3
"""Qualify Last runs copy actions on an isolated loopback workstation and Chromium."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

from krellbot import config, paths
from verify_paper_runs_keyboard import FRONTEND, ROOT, clean_env, seed_local_history, snapshot

ASSERTIONS = [
    "bootstrap_session_csrf", "seed_history", "copy_button_keyboard_enter",
    "copy_button_keyboard_space", "copy_button_mouse_click", "copied_label_visible_2s",
    "copy_failure_label_visible_2s", "label_restored_to_copy",
    "fill_coid_copy_button_writes_coid_only", "keyboard_row_focus_preserved",
    "clipboard_state_isolated_per_row", "no_trading_requests", "loopback_only",
    "history_bytes_unchanged", "legacy_fallback_exact_bytes_focus_restored",
    "live_disabled_no_armed_records",
]
VIEWPORTS = [(1440, 1000), (1100, 760), (390, 844)]

BROWSER = r'''
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const { chromium, expect } = require('@playwright/test');
const [url, width, height, out] = process.argv.slice(2);
const results = {}, requests = [], errors = [], timings = {};
let browser, page;
const id = name => page.getByTestId(`paper-last-runs-${name}`);
async function check(name, action) { await action(); results[name] = true; }
async function tabTo(target) {
  for (let i = 0; i < 180; i++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Keyboard target unreachable');
}
async function readClipboard() { return page.evaluate(() => navigator.clipboard.readText()); }
async function watchFeedback(button) {
  await button.evaluate(el => {
    window.__copyLabels = [];
    window.__copyObserver?.disconnect();
    window.__copyObserver = new MutationObserver(() => {
      window.__copyLabels.push({text: el.textContent.trim(), time: performance.now()});
    });
    window.__copyObserver.observe(el, {childList: true, characterData: true, subtree: true});
  });
}
async function feedbackWindow(button, label) {
  await expect(button).toHaveText(label);
  await page.waitForTimeout(1750);
  await expect(button).toHaveText(label);
  await expect(button).toHaveText('Copy');
  const events = await page.evaluate(() => window.__copyLabels);
  const start = events.find(e => e.text === label);
  const end = events.find(e => e.text === 'Copy' && e.time > start?.time);
  expect(start).toBeTruthy();
  expect(end).toBeTruthy();
  const duration = end.time - start.time;
  // DOM mutation delivery and the render frame can differ by a few milliseconds.
  expect(duration).toBeGreaterThanOrEqual(1950);
  expect(duration).toBeLessThan(3000);
  timings[label] = duration;
}
try {
  browser = await chromium.launch({headless: true, timeout: 15000,
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {})});
  const context = await browser.newContext({viewport: {width: Number(width), height: Number(height)}});
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], {origin: new URL(url).origin});
  await context.tracing.start({screenshots: true, snapshots: true});
  // Refuse any non-loopback traffic before it can leave the browser.
  await context.route('**/*', route => {
    if (new URL(route.request().url()).origin !== new URL(url).origin) return route.abort();
    return route.continue();
  });
  page = await context.newPage();
  page.setDefaultTimeout(8000);
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => requests.push({url: request.url(), method: request.method(),
    csrf_present: !!request.headers()['x-krellbot-csrf']}));
  page.on('response', response => {
    const request = [...requests].reverse().find(r => r.url === response.url());
    if (request) request.status = response.status();
  });
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  const response = await bootstrap;
  await check('bootstrap_session_csrf', async () => {
    expect(response.status()).toBe(200);
    expect((await response.json()).csrf_token.length).toBeGreaterThan(0);
    expect((await context.cookies()).some(c => c.httpOnly && c.value.length > 0)).toBe(true);
  });
  const nav = page.getByRole('navigation', {name: 'Workstation navigation'});
  await tabTo(nav.getByRole('button', {name: 'Home', exact: true}));
  await page.keyboard.press('ArrowRight');
  await expect(nav.getByRole('button', {name: 'Workstation', exact: true})).toBeFocused();
  const row = id('row-kraken-SUIUSD'), other = id('row-kraken-DOTUSD');
  const copy = id('copy-kraken-SUIUSD'), otherCopy = id('copy-kraken-DOTUSD');
  await check('seed_history', async () => {
    await expect(row).toBeVisible();
    await expect(other).toBeVisible();
    await expect(id('count')).toHaveText('2 runs');
    await expect(row.locator('.kbot-paper-runs__result')).toHaveText('1 tick, 1 fill, no refusal, closed');
    expect(requests.some(r => new URL(r.url).pathname === '/api/v1/paper/history' &&
      r.status === 200 && r.csrf_present)).toBe(true);
  });
  const summary = await row.locator('.kbot-paper-runs__result').textContent();
  const otherSummary = await other.locator('.kbot-paper-runs__result').textContent();
  await check('keyboard_row_focus_preserved', async () => {
    await tabTo(row);
    await page.keyboard.press('Enter');
    await expect(row).toBeFocused();
    await expect(row).toHaveAttribute('aria-expanded', 'true');
    await expect(id('detail')).toHaveAttribute('id', await row.getAttribute('aria-controls'));
    await expect(id('fills-table').getByRole('columnheader')).toHaveCount(4);
    await id('detail-close').click();
    await tabTo(row);
    await page.keyboard.press('Tab');
    await expect(copy).toBeFocused();
    await expect(copy).toHaveAccessibleName('Copy summary for kraken SUIUSD');
    await expect(row).toHaveAttribute('aria-expanded', 'false');
  });
  await watchFeedback(copy);
  await check('copy_button_keyboard_enter', async () => {
    await page.keyboard.press('Enter');
    await expect(copy).toHaveText('Copied');
    expect(await readClipboard()).toBe(summary);
    await expect(copy).toBeFocused();
    await expect(id('detail')).toHaveCount(0);
  });
  await check('copied_label_visible_2s', () => feedbackWindow(copy, 'Copied'));
  await check('label_restored_to_copy', async () => { await expect(copy).toHaveText('Copy'); });
  await check('copy_button_keyboard_space', async () => {
    await page.keyboard.press('Space');
    await expect(copy).toHaveText('Copied');
    expect(await readClipboard()).toBe(summary);
    await expect(copy).toBeFocused();
    await expect(row).toHaveAttribute('aria-expanded', 'false');
    await expect(id('detail')).toHaveCount(0);
    await expect(copy).toHaveText('Copy');
  });
  await check('copy_button_mouse_click', async () => {
    await copy.click();
    await expect(copy).toHaveText('Copied');
    expect(await readClipboard()).toBe(summary);
    await expect(id('detail')).toHaveCount(0);
  });
  await check('clipboard_state_isolated_per_row', async () => {
    await page.waitForTimeout(600);
    await otherCopy.click();
    await expect(otherCopy).toHaveText('Copied');
    expect(await readClipboard()).toBe(otherSummary);
    await expect(copy).toHaveText('Copied');
    await expect(copy).toHaveText('Copy');
    await expect(otherCopy).toHaveText('Copied');
    await expect(otherCopy).toHaveText('Copy');
  });
  const cdp = await context.newCDPSession(page);
  const {targetInfo} = await cdp.send('Target.getTargetInfo');
  await cdp.send('Browser.setPermission', {permission: {name: 'clipboard-write'},
    browserContextId: targetInfo.browserContextId, setting: 'denied', origin: new URL(url).origin});
  expect(await page.evaluate(async () => (await navigator.permissions.query({name: 'clipboard-write'})).state))
    .toBe('denied');
  await tabTo(copy);
  await watchFeedback(copy);
  await page.keyboard.press('Enter');
  await check('copy_failure_label_visible_2s', () => feedbackWindow(copy, 'Copy failed'));
  await expect(copy).toBeFocused();
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], {origin: new URL(url).origin});
  await check('fill_coid_copy_button_writes_coid_only', async () => {
    await tabTo(row);
    await page.keyboard.press('Space');
    await expect(row).toBeFocused();
    const fillCopy = id('fills-table').getByRole('button', {name: 'Copy coid', exact: true});
    await tabTo(fillCopy);
    await page.keyboard.press('Enter');
    await expect(fillCopy).toHaveText('Copied');
    expect(await readClipboard()).toBe('LOCAL-KEYBOARD-FIXTURE-fill');
    await expect(fillCopy).toHaveText('Copy coid');
    await expect(id('fills-table').getByRole('columnheader')).toHaveCount(4);
  });
  await id('detail-close').click();
  await tabTo(copy);
  await check('legacy_fallback_exact_bytes_focus_restored', async () => {
    // Unsupported API is simulated; execCommand and the system clipboard are real.
    await page.evaluate(() => Object.defineProperty(navigator, 'clipboard', {configurable: true, value: undefined}));
    try {
      await page.keyboard.press('Space');
      await expect(copy).toHaveText('Copied');
      await expect(copy).toBeFocused();
      await expect(page.locator('textarea')).toHaveCount(0);
    } finally {
      await page.evaluate(() => { delete navigator.clipboard; });
    }
    expect(await readClipboard()).toBe(summary);
    await expect(id('detail')).toHaveCount(0);
    await expect(copy).toHaveText('Copy');
  });
  if (Number(width) <= 640) {
    const box = await copy.boundingBox();
    expect(box.height).toBeGreaterThanOrEqual(44);
    expect(box.width).toBeGreaterThanOrEqual(44);
  }
  await copy.scrollIntoViewIfNeeded();
  await page.screenshot({path: `${out}/copy-controls.png`, fullPage: true});
  fs.writeFileSync(`${out}/panel-aria.yml`, await id('panel').ariaSnapshot());
  await check('no_trading_requests', async () => {
    expect(requests.filter(r => r.method !== 'GET').map(r => new URL(r.url).pathname))
      .toEqual(['/api/v1/session/bootstrap']);
    expect(requests.some(r => /commands|orders|exchange/.test(new URL(r.url).pathname))).toBe(false);
  });
  await check('loopback_only', async () => {
    expect(requests.every(r => new URL(r.url).origin === new URL(url).origin)).toBe(true);
  });
  expect(errors).toEqual([]);
} catch (error) {
  results.error = String(error.stack || error);
  if (page) await page.screenshot({path: `${out}/failure.png`, fullPage: true}).catch(() => {});
  process.exitCode = 1;
} finally {
  fs.writeFileSync(`${out}/browser.json`, JSON.stringify({results, requests, errors, timings,
    browser: browser?.version(), viewport: {width: Number(width), height: Number(height)}}, null, 2));
  if (page) await page.context().tracing.stop({path: `${out}/trace.zip`}).catch(() => {});
  if (browser) await browser.close();
}
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="last-runs-copy-"))
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "qualified": False, "required_assertions": {name: False for name in ASSERTIONS},
        "commands": [], "viewports": {}, "platform": platform.platform(),
        "fixtures": "Isolated LOCAL-KEYBOARD-FIXTURE paper history; no exchange keys or live orders",
    }

    def run(argv: list[str], env: dict[str, str], log: Path, cwd: Path = ROOT) -> int:
        record = {"argv": argv, "cwd": str(cwd), "log": str(log), "exit": None}
        summary["commands"].append(record)
        with log.open("w") as stream:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            try:
                record["exit"] = proc.wait(timeout=180)
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)
        return record["exit"]

    try:
        summary["source_sha"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        summary["source_status"] = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
        sources = ["frontend/src/features/paper/LastRunsPanel.tsx",
                   "frontend/src/features/paper/LastRunsPanel.signal.css",
                   "frontend/src/features/paper/LastRunsPanel.copyAction.test.tsx",
                   "scripts/verify_last_runs_copy_action.py", "scripts/verify_paper_runs_keyboard.py"]
        summary["source_hashes"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources}
        browser_file = out / "journey.mjs"
        browser_file.write_text(BROWSER)
        with tempfile.TemporaryDirectory(prefix="last-runs-copy-home-") as temp:
            home = Path(temp)
            env = clean_env(home)
            old_env = dict(os.environ)
            try:
                os.environ.clear()
                os.environ.update(env)
                paths.ensure_layout()
                seed_local_history(home)
                assert not config.load_config(home).armed
                assert env["KRELLBOT_ENABLE_LIVE"] == "0"
            finally:
                os.environ.clear()
                os.environ.update(old_env)
            before = snapshot(home)
            assert before, "History seeding produced no stored records"
            assert run(["npm", "run", "build"], env, out / "build.log", FRONTEND) == 0
            for width, height in VIEWPORTS:
                key = f"{width}x{height}"
                evidence = out / key
                evidence.mkdir(exist_ok=True)
                argv = [sys.executable, "-m", "krellbot.cli", "workstation", "--dist", str(FRONTEND / "dist")]
                log = evidence / "backend.log"
                # Bootstrap is one-use per backend, so each viewport gets a fresh server.
                with log.open("w") as stream:
                    proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
                    try:
                        deadline = time.monotonic() + 20
                        url = None
                        while time.monotonic() < deadline:
                            match = re.search(r"Workstation running at (http://127\.0\.0\.1:\d+/)", log.read_text())
                            if match:
                                url = match[1]
                                break
                            if proc.poll() is not None:
                                break
                            time.sleep(0.1)
                        assert url, f"Loopback backend unavailable: {log.read_text()}"
                        code = run(["node", str(browser_file), url, str(width), str(height), str(evidence)],
                                   env, evidence / "browser.log")
                        data = json.loads((evidence / "browser.json").read_text())
                        summary["viewports"][key] = data["results"]
                        assert code == 0, data["results"].get("error", "Browser journey failed")
                    finally:
                        if proc.poll() is None:
                            proc.terminate()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait(timeout=5)
            after = snapshot(home)
            (out / "storage-hashes.json").write_text(json.dumps({"before": before, "after": after}, indent=2))
            old_env = dict(os.environ)
            try:
                os.environ.clear()
                os.environ.update(env)
                safe_after = not config.load_config(home).armed
            finally:
                os.environ.clear()
                os.environ.update(old_env)
            for result in summary["viewports"].values():
                result["history_bytes_unchanged"] = before == after
                result["live_disabled_no_armed_records"] = safe_after
        for name in ASSERTIONS:
            summary["required_assertions"][name] = len(summary["viewports"]) == len(VIEWPORTS) and all(
                result.get(name) is True for result in summary["viewports"].values())
        summary["qualified"] = all(summary["required_assertions"].values())
    except Exception:
        summary["error"] = traceback.format_exc()
    finally:
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps({"qualified": summary["qualified"], "artifact": str(out / "summary.json"),
                          "error": summary.get("error")}, indent=2))
    return 0 if summary["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
