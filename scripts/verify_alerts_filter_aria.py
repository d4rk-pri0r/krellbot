#!/usr/bin/env python3
"""Qualify alert-filter names and empty-result descriptions against the real loopback workstation.

Run with uv run --frozen python scripts/verify_alerts_filter_aria.py.
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
    "session_bootstrap_csrf", "live_disabled_local_fixtures", "mounted_alerts_panel",
    "severity_keyboard_name", "query_keyboard_name", "explicit_label_associations",
    "initial_no_dangling_description", "empty_both_descriptions", "query_recovery_removes_descriptions",
    "clear_removes_descriptions", "real_csrf_command", "truthful_session_failure", "no_browser_errors",
]

BROWSER = r"""
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
const { url, output, executable, required } = JSON.parse(process.env.ALERTS_ARIA_CONFIG);
const assertions = Object.fromEntries(required.map(name => [name, false]));
const errors = [];
const responses = [];
const observations = {};
let browser, context, page;
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
  browser = await chromium.launch({headless: true, timeout: 15000, ...(executable ? {executablePath: executable} : {})});
  context = await browser.newContext({viewport: {width: 1280, height: 900}});
  await context.tracing.start({screenshots: true, snapshots: true});
  page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.setDefaultNavigationTimeout(15000);
  page.on('pageerror', error => errors.push(String(error)));
  page.on('response', response => {
    const path = new URL(response.url()).pathname;
    if (path.startsWith('/api/')) responses.push({path, status: response.status(), method: response.request().method()});
  });
  let csrf;
  const bootstrap = page.waitForResponse(response => response.url().endsWith('/api/v1/session/bootstrap') && response.status() === 200);
  await page.goto(url);
  await check('session_bootstrap_csrf', async () => {
    csrf = (await (await bootstrap).json()).csrf_token;
    expect(typeof csrf).toBe('string');
    expect(csrf.length).toBeGreaterThan(0);
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
    expect((await context.cookies()).some(cookie => cookie.name === 'krellbot_session' && cookie.httpOnly)).toBe(true);
  });
  const nav = page.getByRole('navigation', {name: 'Workstation navigation'});
  await tabTo(nav.getByRole('button', {name: 'Operations', exact: true}));
  await page.keyboard.press('Enter');
  const panel = page.getByTestId('ops-alerts-panel');
  const severity = panel.getByTestId('ops-alerts-filter-severity');
  const query = panel.getByTestId('ops-alerts-filter-query');
  const empty = panel.getByTestId('ops-alerts-empty');
  const rows = panel.locator('.kbot-ops__alert');
  await check('mounted_alerts_panel', async () => {
    await expect(panel).toHaveAttribute('aria-label', 'Alerts');
    await expect(rows).toHaveCount(2);
    await expect(page.getByTestId('ops-live-status')).toContainText('Live trading is disabled');
  });
  await check('live_disabled_local_fixtures', async () => {
    const state = await page.evaluate(async () => {
      const response = await fetch('/api/v1/operations', {credentials: 'include', signal: AbortSignal.timeout(10000)});
      return {status: response.status, body: await response.json()};
    });
    expect(state.status).toBe(200);
    expect(state.body.live.live_enabled).toBe(false);
    expect(state.body.live.authorized).toEqual([]);
    expect(state.body.deployments).toEqual([]);
    expect(state.body.alerts).toHaveLength(2);
    expect(state.body.alerts.every(alert => alert.code.startsWith('LOCAL_ALERTS_ARIA_') && alert.venue === 'local-paper-fixture')).toBe(true);
    observations.fixtures = state.body.alerts;
  });
  await check('severity_keyboard_name', async () => {
    await tabTo(severity);
    await expect(severity).toBeFocused();
    await expect(severity).toHaveAccessibleName('Filter alerts by severity');
  });
  await check('query_keyboard_name', async () => {
    await page.keyboard.press('Tab');
    await expect(query).toBeFocused();
    await expect(query).toHaveAccessibleName('Search alerts by code or venue');
  });
  await check('explicit_label_associations', async () => {
    for (const [control, stem] of [[severity, 'severity'], [query, 'query']]) {
      await expect(control).toHaveAttribute('id', `ops-alerts-filter-${stem}-input`);
      const label = panel.locator(`#ops-alerts-filter-${stem}-label`);
      await expect(label).toHaveAttribute('for', `ops-alerts-filter-${stem}-input`);
      expect(await label.evaluate(element => element.control?.id)).toBe(await control.getAttribute('id'));
    }
  });
  async function noDescription() {
    await expect(empty).toHaveCount(0);
    for (const control of [severity, query]) {
      expect(await control.getAttribute('aria-describedby')).toBeNull();
      await expect(control).toHaveAccessibleDescription('');
    }
  }
  await check('initial_no_dangling_description', noDescription);
  await page.screenshot({path: `${output}/named-controls.png`, fullPage: true});
  await page.keyboard.type('no-such-local-alert');
  await check('empty_both_descriptions', async () => {
    await expect(rows).toHaveCount(0);
    await expect(empty).toHaveAttribute('id', 'ops-alerts-empty-id');
    await expect(empty).toHaveText('No alerts match the current filters.');
    for (const control of [severity, query]) {
      await tabTo(control, true);
      await expect(control).toBeFocused();
      await expect(control).toHaveAttribute('aria-describedby', 'ops-alerts-empty-id');
      await expect(control).toHaveAccessibleDescription('No alerts match the current filters.');
    }
    fs.writeFileSync(`${output}/empty-accessibility.yml`, await panel.ariaSnapshot());
    const cdp = await context.newCDPSession(page);
    const ax = await cdp.send('Accessibility.getFullAXTree');
    fs.writeFileSync(`${output}/empty-ax-tree.json`, JSON.stringify(ax, null, 2));
    await cdp.detach();
    await page.screenshot({path: `${output}/empty-described.png`, fullPage: true});
  });
  await check('query_recovery_removes_descriptions', async () => {
    await tabTo(query);
    await page.keyboard.press('ControlOrMeta+A');
    await page.keyboard.type(' LOCAL_ALERTS_ARIA_ONE ');
    await expect(rows).toHaveCount(1);
    await noDescription();
  });
  await check('clear_removes_descriptions', async () => {
    await page.keyboard.press('ControlOrMeta+A');
    await page.keyboard.type('no-such-local-alert');
    await expect(empty).toBeVisible();
    await tabTo(panel.getByTestId('ops-alerts-filter-clear'));
    await page.keyboard.press('Enter');
    await expect(rows).toHaveCount(2);
    await noDescription();
    await expect(severity).toHaveValue('all');
    await expect(query).toHaveValue('');
    await page.screenshot({path: `${output}/restored.png`, fullPage: true});
  });
  await check('real_csrf_command', async () => {
    const fixture = observations.fixtures[0];
    await tabTo(panel.getByTestId(`ops-alert-ack-${fixture.id}`));
    const command = page.waitForResponse(response => response.url().endsWith('/api/v1/commands'));
    await page.keyboard.press('Enter');
    const result = await command;
    expect(result.status()).toBe(200);
    expect((await result.json()).code).toBe('acknowledged');
    const headers = await result.request().allHeaders();
    expect(headers['x-krellbot-csrf']).toBe(csrf);
    expect(headers['origin']).toBe(new URL(url).origin);
    await expect(panel.getByTestId(`ops-alert-ack-${fixture.id}`)).toHaveCount(0);
  });
  await check('truthful_session_failure', async () => {
    await context.clearCookies();
    const refresh = page.getByRole('button', {name: 'Refresh now', exact: true});
    await tabTo(refresh, true);
    const failure = page.waitForResponse(response => response.url().endsWith('/api/v1/operations') && response.status() === 403);
    await page.keyboard.press('Enter');
    await failure;
    await expect(page.getByTestId('ops-stale-warning')).toContainText('Operations state may be stale');
    await expect(page.getByTestId('ops-stale-warning')).toContainText('403');
    await expect(rows).toHaveCount(2);
    await noDescription();
    await page.screenshot({path: `${output}/session-failure.png`, fullPage: true});
  });
  await check('no_browser_errors', async () => expect(errors).toEqual([]));
  observations.browser_version = browser.version();
} catch (error) {
  observations.failure = String(error.stack || error);
  if (page) await page.screenshot({path: `${output}/failure.png`, fullPage: true, timeout: 5000}).catch(() => {});
} finally {
  if (page) fs.writeFileSync(`${output}/visible-text.txt`, await page.locator('body').innerText({timeout: 5000}).catch(() => ''));
  if (context) await context.tracing.stop({path: `${output}/browser-trace.zip`}).catch(() => {});
  if (browser) await browser.close();
  const qualified = Object.values(assertions).every(Boolean);
  fs.writeFileSync(`${output}/browser.json`, JSON.stringify({qualified, required_assertions: assertions, observations, responses, errors}, null, 2));
  process.exitCode = qualified ? 0 : 1;
}
"""


def serve() -> int:
    home = Path(os.environ["KRELLBOT_HOME"])
    for code in ("LOCAL_ALERTS_ARIA_ONE", "LOCAL_ALERTS_ARIA_TWO"):
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
        stopped.wait(timeout=240)
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
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()
    output = (args.output_dir or ROOT / "tests_tmp" / "alerts-filter-aria" / f"{sha[:12]}-{time.time_ns()}").resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    summary = {
        "source_sha": sha, "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, timeout=10)),
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
        child = None
        with (output / f"{name}.log").open("w") as log:
            try:
                child = subprocess.Popen(
                    argv, cwd=cwd, env=env, text=True,
                    stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=os.name != "nt",
                )
                child.communicate(input=stdin, timeout=180)
                record["exit_code"] = child.returncode
            except subprocess.TimeoutExpired:
                record["exit_code"] = 124
            except OSError as error:
                log.write(str(error))
                record["exit_code"] = 127
            finally:
                if child is not None:
                    # The owned process group includes npm's build child and Chromium.
                    if os.name != "nt":
                        try:
                            os.killpg(child.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                    elif child.poll() is None:
                        child.terminate()
                    try:
                        child.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.communicate(timeout=5)
                    finally:
                        if os.name != "nt":
                            try:
                                os.killpg(child.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
        return record["exit_code"]

    try:
        if run("build", ["npm", "run", "build"], ROOT / "frontend") != 0:
            raise RuntimeError("current frontend build failed")
        with tempfile.TemporaryDirectory(prefix="krellbot-alerts-aria-home-") as fresh_home:
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
                    env["ALERTS_ARIA_CONFIG"] = json.dumps({
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
