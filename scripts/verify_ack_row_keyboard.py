#!/usr/bin/env python3
"""Qualify acknowledged-row keyboard behavior against the real loopback workstation.

Run with uv run --frozen python scripts/verify_ack_row_keyboard.py.
Requires the locked frontend dependencies and a local headless Chromium.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

from krellbot import journal
from krellbot.api.serve import WorkstationServer

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = [
    "session_bootstrap", "live_disabled", "empty_initial", "keyboard_acknowledge_csrf",
    "keyboard_refresh", "acknowledged_only", "tab_space_expand",
    "tab_escape_leave_enter_collapse", "arrow_navigation_and_boundaries",
    "detail_no_network", "truthful_session_failure", "no_browser_errors",
]

BROWSER = r"""
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
const { url, output, executable, required } = JSON.parse(process.env.ACK_VERIFY_CONFIG);
const assertions = Object.fromEntries(required.map(name => [name, false]));
const requests = [];
const errors = [];
const observations = {};
let browser;
let context;
let page;
process.on('SIGTERM', () => {
  void (async () => {
    if (browser) await browser.close();
    process.exit(124);
  })();
});
async function check(name, action) {
  await action();
  assertions[name] = true;
}
async function tabTo(locator, reverse = false) {
  await expect(locator).toHaveCount(1);
  for (let i = 0; i < 100; i++) {
    if (await locator.evaluate(element => element === document.activeElement)) return;
    await page.keyboard.press(reverse ? 'Shift+Tab' : 'Tab');
  }
  throw new Error(`Not reachable with Tab: ${locator}`);
}
try {
  browser = await chromium.launch({headless: true, ...(executable ? {executablePath: executable} : {})});
  context = await browser.newContext({viewport: {width: 1280, height: 900}});
  page = await context.newPage();
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path === '/api/v1/operations' || path === '/api/v1/commands') {
      requests.push({path, method: request.method(), at: Date.now()});
    }
  });
  const bootstrap = page.waitForResponse(response => response.url().endsWith('/api/v1/session/bootstrap') && response.status() === 200);
  await page.goto(url);
  await check('session_bootstrap', async () => {
    await bootstrap;
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
    expect((await context.cookies()).some(cookie => cookie.name === 'krellbot_session' && cookie.httpOnly)).toBe(true);
  });
  await context.tracing.start({screenshots: true, snapshots: true});
  const nav = page.getByRole('navigation', {name: 'Workstation navigation'});
  await tabTo(nav.getByRole('button', {name: 'Operations', exact: true}));
  await page.keyboard.press('Enter');
  const panel = page.getByTestId('ops-acknowledged-alerts');
  const refresh = page.getByTestId('ops-acknowledged-refresh');
  await check('empty_initial', async () => {
    await expect(panel).toHaveAttribute('aria-label', 'Acknowledged alerts');
    await expect(panel).toContainText('No acknowledged alerts.');
    await expect(panel.getByTestId('ops-acknowledged-table')).toHaveCount(0);
    await page.screenshot({path: `${output}/empty.png`, fullPage: true});
  });
  const state = await page.evaluate(async () => {
    const response = await fetch('/api/v1/operations', {credentials: 'include'});
    return {status: response.status, body: await response.json()};
  });
  await check('live_disabled', async () => {
    expect(state.status).toBe(200);
    expect(state.body.live.live_enabled).toBe(false);
    expect(state.body.live.authorized).toEqual([]);
    expect(state.body.deployments).toEqual([]);
  });
  expect(state.body.alerts).toHaveLength(3);
  const fixtures = state.body.alerts.filter(alert => alert.code.startsWith('LOCAL_PAPER_HISTORY_ACK_'));
  const unacknowledged = state.body.alerts.find(alert => alert.code === 'LOCAL_PAPER_HISTORY_UNACK_FIXTURE');
  expect(fixtures).toHaveLength(2);
  expect(unacknowledged).toBeTruthy();
  await check('keyboard_acknowledge_csrf', async () => {
    for (const alert of fixtures) {
      await tabTo(page.getByTestId(`ops-alert-ack-${alert.id}`));
      const command = page.waitForResponse(response => response.url().endsWith('/api/v1/commands') && response.status() === 200);
      await page.keyboard.press('Enter');
      const result = await command;
      expect((await result.json()).code).toBe('acknowledged');
      const headers = await result.request().allHeaders();
      expect(headers['x-krellbot-csrf']).toBeTruthy();
      expect(headers['origin']).toBe(new URL(url).origin);
      await expect(page.getByTestId(`ops-alert-ack-${alert.id}`)).toHaveCount(0);
    }
  });
  await check('keyboard_refresh', async () => {
    await tabTo(refresh);
    const response = page.waitForResponse(response => response.url().endsWith('/api/v1/operations') && response.status() === 200);
    await page.keyboard.press('Enter');
    await response;
    await expect(panel.locator('tbody tr')).toHaveCount(2);
  });
  await check('acknowledged_only', async () => {
    await expect(panel.getByTestId(`ops-acknowledged-alert-${unacknowledged.id}`)).toHaveCount(0);
    for (const alert of fixtures) {
      await expect(panel.getByTestId(`ops-ack-severity-${alert.id}`)).toHaveText(alert.severity);
    }
  });
  const rows = panel.locator('tbody tr');
  const first = rows.nth(0);
  const last = rows.nth(1);
  const firstId = (await first.getAttribute('data-testid')).replace('ops-acknowledged-alert-', '');
  const lastId = (await last.getAttribute('data-testid')).replace('ops-acknowledged-alert-', '');
  const detail = page.getByTestId(`ops-ack-detail-${firstId}`);
  const lastDetail = page.getByTestId(`ops-ack-detail-${lastId}`);
  const beforeToggle = requests.length;
  await check('tab_space_expand', async () => {
    await expect(refresh).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(first).toBeFocused();
    await expect(first).toHaveAttribute('role', 'button');
    await expect(first).toHaveAttribute('aria-expanded', 'false');
    await page.keyboard.press('Space');
    await expect(first).toHaveAttribute('aria-expanded', 'true');
    await expect(detail).toBeVisible();
    await expect(detail).toContainText('LOCAL_PAPER_HISTORY_ACK_');
    await expect(detail.locator('button, input, a')).toHaveCount(0);
    observations.focus_outline = await first.evaluate(element => getComputedStyle(element).outlineStyle);
    expect(observations.focus_outline).toBe('solid');
    await page.screenshot({path: `${output}/keyboard-expanded.png`, fullPage: true});
  });
  await check('tab_escape_leave_enter_collapse', async () => {
    await page.keyboard.press('Tab');
    await expect(last).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(last).toBeFocused();
    await expect(detail).toBeVisible();
    await page.keyboard.press('Shift+Tab');
    await expect(first).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(first).toHaveAttribute('aria-expanded', 'false');
    await expect(detail).toHaveCount(0);
  });
  await check('arrow_navigation_and_boundaries', async () => {
    await page.keyboard.press('ArrowUp');
    await expect(first).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await expect(last).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await expect(last).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(lastDetail).toBeVisible();
    await expect(last).toHaveAttribute('aria-expanded', 'true');
    await page.keyboard.press('ArrowUp');
    await expect(first).toBeFocused();
    await page.keyboard.press('Space');
    await expect(detail).toBeVisible();
    await expect(lastDetail).toHaveCount(0);
    await expect(last).toHaveAttribute('aria-expanded', 'false');
    await page.keyboard.press('Space');
    await expect(detail).toHaveCount(0);
  });
  await check('detail_no_network', async () => expect(requests.length).toBe(beforeToggle));
  await page.screenshot({path: `${output}/keyboard-collapsed.png`, fullPage: true});
  await context.clearCookies();
  await check('truthful_session_failure', async () => {
    await tabTo(refresh, true);
    const failure = page.waitForResponse(response => response.url().endsWith('/api/v1/operations') && response.status() === 403);
    await page.keyboard.press('Enter');
    await failure;
    await expect(panel.getByRole('alert')).toContainText('Failed to load acknowledged alerts. operations view failed: 403');
    await expect(panel.getByTestId('ops-acknowledged-table')).toHaveCount(0);
    await expect(panel).not.toContainText('No acknowledged alerts.');
    await expect(detail).toHaveCount(0);
    await page.screenshot({path: `${output}/session-failure.png`, fullPage: true});
  });
  await check('no_browser_errors', async () => expect(errors).toEqual([]));
  observations.browser_version = browser.version();
} catch (error) {
  observations.failure = String(error.stack || error);
  if (page) await page.screenshot({path: `${output}/failure.png`, fullPage: true}).catch(() => {});
} finally {
  if (page) fs.writeFileSync(`${output}/visible-text.txt`, await page.locator('body').innerText().catch(() => ''));
  if (context) await context.tracing.stop({path: `${output}/keyboard-trace.zip`}).catch(() => {});
  if (browser) await browser.close();
  const qualified = Object.values(assertions).every(Boolean);
  fs.writeFileSync(`${output}/browser.json`, JSON.stringify({qualified, required_assertions: assertions, observations, requests, errors}, null, 2));
  process.exitCode = qualified ? 0 : 1;
}
"""


def serve() -> int:
    home = Path(os.environ["KRELLBOT_HOME"])
    for code in ("LOCAL_PAPER_HISTORY_ACK_ONE", "LOCAL_PAPER_HISTORY_ACK_TWO", "LOCAL_PAPER_HISTORY_UNACK_FIXTURE"):
        journal.append({
            "ts": 1700000000, "kind": "tick", "venue": "local-paper-fixture",
            "pack": "local-paper-history-only", "bar_ts": 1700000000,
            "detail": {"intent_refused": code, "pair": "PAPERUSD"},
        })
    server = WorkstationServer(home, dist_dir=ROOT / "frontend" / "dist")
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    try:
        server.start()
        print(f"RUNTIME_URL={server.url}", flush=True)
        stopped.wait()
    finally:
        server.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        return serve()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    output = (args.output_dir or ROOT / "tests_tmp" / "ack-row-keyboard" / f"{sha[:12]}-{time.time_ns()}").resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    summary = {
        "source_sha": sha, "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
        "platform": sys.platform, "qualified": False, "commands": [],
        "isolated_home": True, "live_enabled": False,
        "fixture_scope": "clearly labelled local paper/history refusal records only",
        "required_assertions": dict.fromkeys(REQUIRED, False),
        "output_dir": str(output),
    }
    env = {key: value for key, value in os.environ.items() if not (
        key.startswith(("KRELLBOT_", "KRAKEN_", "COINBASE_", "STRIPE_", "PAYPAL_"))
        or any(word in key.upper() for word in ("SECRET", "TOKEN", "PASSWORD", "API_KEY"))
    )}
    env["KRELLBOT_ENABLE_LIVE"] = "0"
    env["PYTHONUNBUFFERED"] = "1"
    process = None

    def run(name: str, argv: list[str], cwd: Path, *, stdin: str | None = None) -> int:
        record = {"name": name, "argv": argv, "cwd": str(cwd), "exit_code": None}
        summary["commands"].append(record)
        with (output / f"{name}.log").open("w") as log:
            try:
                child = subprocess.Popen(
                    argv, cwd=cwd, env=env, text=True,
                    stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT,
                )
                try:
                    child.communicate(input=stdin, timeout=240)
                    record["exit_code"] = child.returncode
                except subprocess.TimeoutExpired:
                    child.terminate()
                    try:
                        child.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.communicate()
                    record["exit_code"] = 124
            except OSError as error:
                log.write(str(error))
                record["exit_code"] = 127
        return record["exit_code"]

    try:
        if run("build", ["npm", "run", "build"], ROOT / "frontend") != 0:
            raise RuntimeError("current frontend build failed")
        with tempfile.TemporaryDirectory(prefix="krellbot-ack-home-") as fresh_home:
            env["KRELLBOT_HOME"] = fresh_home
            argv = [sys.executable, str(Path(__file__).resolve()), "--serve"]
            backend_record = {"name": "backend", "argv": argv, "cwd": str(ROOT), "exit_code": None}
            summary["commands"].append(backend_record)
            with (output / "backend.log").open("w") as log:
                process = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 20
                    url = None
                    while time.monotonic() < deadline:
                        match = re.search(r"RUNTIME_URL=(http://127[.]0[.]0[.]1:[0-9]+/)", (output / "backend.log").read_text())
                        if match:
                            url = match.group(1)
                            break
                        if process.poll() is not None:
                            raise RuntimeError("real backend exited before readiness")
                        time.sleep(0.05)
                    if url is None:
                        raise RuntimeError("real backend readiness timed out")
                    env["ACK_VERIFY_CONFIG"] = json.dumps({
                        "url": url, "output": str(output), "required": REQUIRED,
                        "executable": shutil.which("chromium") or shutil.which("chromium-browser"),
                    })
                    exit_code = run("browser", ["node", "--input-type=module"], ROOT / "frontend", stdin=BROWSER)
                    result_path = output / "browser.json"
                    if result_path.exists():
                        result = json.loads(result_path.read_text())
                        summary["required_assertions"] = result["required_assertions"]
                        summary["qualified"] = exit_code == 0 and all(
                            summary["required_assertions"].get(name) is True for name in REQUIRED
                        )
                finally:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    backend_record["exit_code"] = process.returncode
                    if process.returncode != 0:
                        summary["qualified"] = False
    except Exception:
        summary["failure"] = traceback.format_exc()
        summary["qualified"] = False
    finally:
        summary["exit_code"] = 0 if summary["qualified"] else 1
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["qualified"] else 1


if __name__ == "__main__":
    sys.exit(main())
