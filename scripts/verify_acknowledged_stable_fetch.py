#!/usr/bin/env python3
"""Qualify acknowledged-list fetch behavior against the real loopback workstation.

Run with uv run --frozen python scripts/verify_acknowledged_stable_fetch.py.
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
    "session_bootstrap", "live_disabled", "empty_initial_one_read",
    "no_self_triggered_reads", "keyboard_acknowledge", "keyboard_refresh_one_read",
    "acknowledged_only", "detail_toggle_no_read", "remount_one_read",
    "parent_polling_unchanged", "truthful_session_failure", "failure_no_retry_loop",
    "no_browser_errors",
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
try {
  browser = await chromium.launch({headless: true, ...(executable ? {executablePath: executable} : {})});
  context = await browser.newContext({viewport: {width: 1280, height: 900}});
  page = await context.newPage();
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path === '/api/v1/operations') requests.push({method: request.method(), at: Date.now()});
  });
  const bootstrap = page.waitForResponse(response => response.url().endsWith('/api/v1/session/bootstrap') && response.status() === 200);
  await page.goto(url);
  await check('session_bootstrap', async () => {
    await bootstrap;
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
    expect((await context.cookies()).some(cookie => cookie.name === 'krellbot_session' && cookie.httpOnly)).toBe(true);
  });
  const nav = page.getByRole('navigation', {name: 'Workstation navigation'});
  const beforeMount = requests.length;
  await nav.getByRole('button', {name: 'Operations', exact: true}).focus();
  await page.keyboard.press('Enter');
  const panel = page.getByTestId('ops-acknowledged-alerts');
  const refresh = page.getByTestId('ops-acknowledged-refresh');
  await check('empty_initial_one_read', async () => {
    await expect(panel).toContainText('No acknowledged alerts.');
    await page.waitForTimeout(300);
    // The mounted Operations view makes its own independent read, plus one list read.
    observations.initial_mount_reads = requests.length - beforeMount;
    expect(observations.initial_mount_reads).toBe(2);
    await page.screenshot({path: `${output}/acknowledged-empty.png`, fullPage: true});
  });
  await check('live_disabled', async () => {
    const response = await page.evaluate(async () => {
      const response = await fetch('/api/v1/operations', {credentials: 'include'});
      return {status: response.status, body: await response.json()};
    });
    expect(response.status).toBe(200);
    expect(response.body.live.live_enabled).toBe(false);
    expect(response.body.deployments).toEqual([]);
  });
  const idleCount = requests.length;
  await check('no_self_triggered_reads', async () => {
    await page.waitForTimeout(1200);
    expect(requests.length).toBe(idleCount);
  });
  const fixture = await page.evaluate(async () => (await (await fetch('/api/v1/operations')).json()).alerts);
  expect(fixture).toHaveLength(2);
  const acknowledged = fixture.find(alert => alert.code === 'LOCAL_PAPER_HISTORY_ACK_FIXTURE');
  const unacknowledged = fixture.find(alert => alert.code === 'LOCAL_PAPER_HISTORY_UNACK_FIXTURE');
  expect(acknowledged).toBeTruthy();
  expect(unacknowledged).toBeTruthy();
  await check('keyboard_acknowledge', async () => {
    const command = page.waitForResponse(response => response.url().endsWith('/api/v1/commands') && response.status() === 200);
    await page.getByTestId(`ops-alert-ack-${acknowledged.id}`).focus();
    await page.keyboard.press('Enter');
    const result = await command;
    expect((await result.json()).code).toBe('acknowledged');
    expect(result.request().headers()['x-krellbot-csrf']).toBeTruthy();
    await expect(page.getByTestId(`ops-alert-ack-${acknowledged.id}`)).toHaveCount(0);
    await page.waitForTimeout(150);
  });
  const beforeRefresh = requests.length;
  await check('keyboard_refresh_one_read', async () => {
    await refresh.focus();
    await page.keyboard.press('Enter');
    await expect(panel.getByTestId(`ops-acknowledged-alert-${acknowledged.id}`)).toBeVisible();
    await page.waitForTimeout(250);
    observations.explicit_refresh_reads = requests.length - beforeRefresh;
    expect(observations.explicit_refresh_reads).toBe(1);
  });
  await check('acknowledged_only', async () => {
    await expect(panel.getByTestId(`ops-acknowledged-alert-${unacknowledged.id}`)).toHaveCount(0);
    await expect(panel.locator('tbody tr')).toHaveCount(1);
  });
  const beforeDetails = requests.length;
  await check('detail_toggle_no_read', async () => {
    const row = panel.getByTestId(`ops-acknowledged-alert-${acknowledged.id}`);
    const detail = panel.getByTestId(`ops-ack-detail-${acknowledged.id}`);
    await row.click();
    await expect(detail).toContainText('LOCAL_PAPER_HISTORY_ACK_FIXTURE');
    await page.screenshot({path: `${output}/acknowledged-detail.png`, fullPage: true});
    await row.click();
    await expect(detail).toHaveCount(0);
    expect(requests.length).toBe(beforeDetails);
  });
  await nav.getByRole('button', {name: 'Home', exact: true}).click();
  const beforeRemount = requests.length;
  await check('remount_one_read', async () => {
    await nav.getByRole('button', {name: 'Operations', exact: true}).click();
    await expect(panel.locator('tbody tr')).toHaveCount(1);
    await page.waitForTimeout(300);
    observations.remount_reads = requests.length - beforeRemount;
    expect(observations.remount_reads).toBe(2);
  });
  const beforePolling = requests.length;
  await check('parent_polling_unchanged', async () => {
    await page.waitForTimeout(6000);
    // StatusStrip and OperationsView each poll every 5 seconds; the list adds none.
    observations.existing_poller_reads = requests.length - beforePolling;
    expect(observations.existing_poller_reads).toBe(2);
  });
  await page.screenshot({path: `${output}/acknowledged-success.png`, fullPage: true});
  await context.clearCookies();
  const beforeFailure = requests.length;
  await check('truthful_session_failure', async () => {
    await refresh.focus();
    await page.keyboard.press('Enter');
    await expect(panel.getByRole('alert')).toContainText('Failed to load acknowledged alerts. operations view failed: 403');
    await expect(panel.getByTestId('ops-acknowledged-table')).toHaveCount(0);
    await expect(panel).not.toContainText('No acknowledged alerts.');
  });
  await check('failure_no_retry_loop', async () => {
    await page.waitForTimeout(500);
    observations.failed_refresh_reads = requests.length - beforeFailure;
    expect(observations.failed_refresh_reads).toBe(1);
  });
  await page.screenshot({path: `${output}/acknowledged-failure.png`, fullPage: true});
  await check('no_browser_errors', async () => expect(errors).toEqual([]));
  observations.browser_version = browser.version();
} catch (error) {
  observations.failure = String(error.stack || error);
  if (page) await page.screenshot({path: `${output}/failure.png`, fullPage: true}).catch(() => {});
} finally {
  if (page) fs.writeFileSync(`${output}/visible-text.txt`, await page.locator('body').innerText().catch(() => ''));
  if (browser) await browser.close();
  const qualified = Object.values(assertions).every(Boolean);
  fs.writeFileSync(`${output}/browser.json`, JSON.stringify({qualified, required_assertions: assertions, observations, requests, errors}, null, 2));
  process.exitCode = qualified ? 0 : 1;
}
"""


def serve() -> int:
    home = Path(os.environ["KRELLBOT_HOME"])
    for code in ("LOCAL_PAPER_HISTORY_ACK_FIXTURE", "LOCAL_PAPER_HISTORY_UNACK_FIXTURE"):
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
    output = (args.output_dir or ROOT / "tests_tmp" / "acknowledged-stable-fetch" / f"{sha[:12]}-{time.time_ns()}").resolve()
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
