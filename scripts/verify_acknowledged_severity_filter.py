#!/usr/bin/env python3
"""Qualify the acknowledged-list severity filter + search against the real loopback workstation.

Run with uv run --frozen python scripts/verify_acknowledged_severity_filter.py.
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
from krellbot.application import alerts as alerts_app

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = [
    "session_bootstrap", "fixture_acknowledged_three", "severity_options_ack_only",
    "severity_filters_warning", "severity_absent_shows_filtered_empty",
    "query_substring_narrows", "clear_button_resets", "keyboard_rows_unchanged",
    "refresh_still_works", "no_state_changing_commands", "no_browser_errors",
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
    if (path === '/api/v1/operations' || path === '/api/v1/commands') {
      requests.push({path, method: request.method(), at: Date.now()});
    }
  });
  const bootstrap = page.waitForResponse(response => response.url().endsWith('/api/v1/session/bootstrap') && response.status() === 200);
  await page.goto(url);
  await check('session_bootstrap', async () => {
    await bootstrap;
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
  });
  await context.tracing.start({screenshots: true, snapshots: true});
  const nav = page.getByRole('navigation', {name: 'Workstation navigation'});
  await nav.getByRole('button', {name: 'Operations', exact: true}).click();
  const panel = page.getByTestId('ops-acknowledged-alerts');
  const refresh = page.getByTestId('ops-acknowledged-refresh');
  const severity = page.getByTestId('ops-acknowledged-filter-severity');
  const query = page.getByTestId('ops-acknowledged-filter-query');
  const clear = page.getByTestId('ops-acknowledged-filter-clear');
  const fixture = await page.evaluate(async () => (await (await fetch('/api/v1/operations', {credentials: 'include'})).json()).alerts);
  expect(fixture).toHaveLength(3);
  expect(fixture.every(alert => alert.acknowledged === true && alert.severity === 'warning')).toBe(true);
  const byCode = Object.fromEntries(fixture.map(alert => [alert.code, alert]));
  const crit = byCode['LOCAL_PAPER_HISTORY_ACK_SEV_CRIT'];
  const one = byCode['LOCAL_PAPER_HISTORY_ACK_SEV_WARN_ONE'];
  const two = byCode['LOCAL_PAPER_HISTORY_ACK_SEV_WARN_TWO'];
  expect(crit && one && two).toBeTruthy();
  await check('fixture_acknowledged_three', async () => {
    await expect(panel.locator('tbody tr')).toHaveCount(3);
    await expect(panel.getByTestId(`ops-ack-severity-${crit.id}`)).toHaveText('warning');
    await expect(panel.getByTestId('ops-acknowledged-empty')).toHaveCount(0);
    await expect(panel).not.toContainText('No acknowledged alerts.');
    await page.screenshot({path: `${output}/initial.png`, fullPage: true});
  });
  await check('severity_options_ack_only', async () => {
    await expect(severity).toBeVisible();
    const values = await severity.locator('option').evaluateAll(options => options.map(option => option.value));
    expect(values).toEqual(['all', 'warning']);
    expect(await severity.inputValue()).toBe('all');
  });
  await check('severity_filters_warning', async () => {
    await severity.selectOption('warning');
    await expect(panel.locator('tbody tr')).toHaveCount(3);
    await expect(clear).toBeVisible();
    await expect(panel.getByTestId('ops-acknowledged-empty')).toHaveCount(0);
  });
  await check('severity_absent_shows_filtered_empty', async () => {
    // "critical" is not offered because every acknowledged row is a warning.
    await query.fill('critical');
    await expect(panel.getByTestId('ops-acknowledged-empty')).toBeVisible();
    await expect(panel.getByTestId('ops-acknowledged-empty')).toHaveText('No acknowledged alerts match the current filters.');
    await expect(panel).not.toContainText('No acknowledged alerts.');
    await expect(panel.locator('tbody tr')).toHaveCount(0);
    await page.screenshot({path: `${output}/filtered-empty.png`, fullPage: true});
  });
  await check('query_substring_narrows', async () => {
    await clear.click();
    await expect(panel.locator('tbody tr')).toHaveCount(3);
    // Pair is shared by every fixture row, case-insensitively.
    await query.fill('xxbtzusd');
    await expect(panel.locator('tbody tr')).toHaveCount(3);
    await query.fill('local_paper_history_ack_sev_warn_one');
    await expect(panel.locator('tbody tr')).toHaveCount(1);
    await expect(panel.getByTestId(`ops-acknowledged-alert-${one.id}`)).toBeVisible();
    await expect(panel.getByTestId(`ops-acknowledged-alert-${crit.id}`)).toHaveCount(0);
    await expect(panel.getByTestId('ops-acknowledged-empty')).toHaveCount(0);
    await page.screenshot({path: `${output}/query-narrowed.png`, fullPage: true});
  });
  await check('clear_button_resets', async () => {
    await severity.selectOption('warning');
    await clear.click();
    await expect(panel.locator('tbody tr')).toHaveCount(3);
    await expect(severity).toHaveValue('all');
    await expect(query).toHaveValue('');
    await expect(clear).toHaveCount(0);
    await expect(panel.getByTestId('ops-acknowledged-empty')).toHaveCount(0);
  });
  await check('keyboard_rows_unchanged', async () => {
    const twoRow = panel.getByTestId(`ops-acknowledged-alert-${two.id}`);
    const oneRow = panel.getByTestId(`ops-acknowledged-alert-${one.id}`);
    await severity.focus();
    await page.keyboard.press('Tab');
    await expect(query).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(clear).toHaveCount(0);
    // two has the greatest last_ts, so it is the topmost warning row.
    await twoRow.focus();
    await expect(twoRow).toBeFocused();
    await expect(twoRow).toHaveAttribute('role', 'button');
    await page.keyboard.press('ArrowUp');
    await expect(twoRow).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await expect(oneRow).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(panel.getByTestId(`ops-ack-detail-${one.id}`)).toBeVisible();
    await page.keyboard.press('Enter');
    await expect(panel.getByTestId(`ops-ack-detail-${one.id}`)).toHaveCount(0);
    await page.keyboard.press('ArrowUp');
    await expect(twoRow).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(panel.getByTestId(`ops-ack-detail-${two.id}`)).toBeVisible();
    await page.keyboard.press('Enter');
    await expect(panel.getByTestId(`ops-ack-detail-${two.id}`)).toHaveCount(0);
  });
  const beforeRefresh = requests.length;
  await check('refresh_still_works', async () => {
    await refresh.click();
    await expect(panel.locator('tbody tr')).toHaveCount(3);
    await page.waitForTimeout(400);
    observations.refresh_reads = requests.filter(request => request.at > 0).length - beforeRefresh;
    expect(observations.refresh_reads).toBeGreaterThanOrEqual(1);
    await expect(panel.getByRole('alert')).toHaveCount(0);
    await page.screenshot({path: `${output}/refreshed.png`, fullPage: true});
  });
  await check('no_state_changing_commands', async () => {
    observations.commands = requests.filter(request => request.method === 'POST').length;
    expect(observations.commands).toBe(0);
    expect(requests.every(request => request.method === 'GET')).toBe(true);
  });
  await check('no_browser_errors', async () => expect(errors).toEqual([]));
  observations.browser_version = browser.version();
} catch (error) {
  observations.failure = String(error.stack || error);
  if (page) await page.screenshot({path: `${output}/failure.png`, fullPage: true}).catch(() => {});
} finally {
  if (page) fs.writeFileSync(`${output}/visible-text.txt`, await page.locator('body').innerText().catch(() => ''));
  if (context) await context.tracing.stop({path: `${output}/severity-filter-trace.zip`}).catch(() => {});
  if (browser) await browser.close();
  const qualified = Object.values(assertions).every(Boolean);
  fs.writeFileSync(`${output}/browser.json`, JSON.stringify({qualified, required_assertions: assertions, observations, requests, errors}, null, 2));
  process.exitCode = qualified ? 0 : 1;
}
"""

FIXTURE_CODES = (
    "LOCAL_PAPER_HISTORY_ACK_SEV_CRIT",
    "LOCAL_PAPER_HISTORY_ACK_SEV_WARN_ONE",
    "LOCAL_PAPER_HISTORY_ACK_SEV_WARN_TWO",
)


def serve() -> int:
    home = Path(os.environ["KRELLBOT_HOME"])
    for index, code in enumerate(FIXTURE_CODES):
        journal.append({
            "ts": 1700000000 + index * 100, "kind": "tick", "venue": "local-paper-fixture",
            "pack": "local-paper-history-only", "bar_ts": 1700000000,
            "detail": {"intent_refused": code, "pair": "XXBTZUSD"},
        })
    # Pre-seed acknowledgements for exactly the three fixture ids so the list
    # starts acknowledged without firing any ack command from the browser.
    collected = alerts_app.collect(home, now=1700000500)
    acks = {alert.id: 1700000500 for alert in collected if alert.code in FIXTURE_CODES}
    if len(acks) != len(FIXTURE_CODES):
        raise RuntimeError(f"expected {len(FIXTURE_CODES)} fixture alerts, collected {len(acks)}")
    ack_file = home / "run" / alerts_app.ACK_FILE
    ack_file.parent.mkdir(parents=True, exist_ok=True)
    ack_file.write_text(json.dumps(acks, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    verified = {a.code: a.acknowledged for a in alerts_app.collect(home, now=1700000500)}
    if not all(verified[code] for code in FIXTURE_CODES):
        raise RuntimeError(f"ack seeding failed: {verified}")
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
    output = (args.output_dir or ROOT / "tests_tmp" / "acknowledged-severity-filter" / f"{sha[:12]}-{time.time_ns()}").resolve()
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
        with tempfile.TemporaryDirectory(prefix="krellbot-ack-sev-home-") as fresh_home:
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
