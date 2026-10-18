#!/usr/bin/env python3
"""Qualify alert acknowledgement error honesty against the real loopback workstation.

Run with uv run --frozen python scripts/verify_alert_ack_error.py.
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
    "session_bootstrap", "live_disabled", "real_403_inline_error",
    "failed_ack_remains_unacknowledged", "refresh_failure_visible",
    "retry_success_badge", "retry_clears_error", "network_inline_error",
    "network_retry_success", "row_error_isolation", "mobile_keyboard",
    "request_contract", "loopback_only", "no_browser_errors",
]

BROWSER = r"""
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
const { url, output, executable, required } = JSON.parse(process.env.ACK_VERIFY_CONFIG);
const assertions = Object.fromEntries(required.map(name => [name, false]));
const requests = [], errors = [], external = [], observations = {};
let browser, context, page;
process.on('SIGTERM', () => {
  void (async () => {
    if (browser) await browser.close();
    process.exit(124);
  })();
});
async function check(name, action) { await action(); assertions[name] = true; }
async function state() {
  return page.evaluate(async () => {
    const response = await fetch('/api/v1/operations', {credentials: 'include'});
    if (!response.ok) throw new Error(`operations state failed: ${response.status}`);
    return response.json();
  });
}
async function evidence(name) {
  await page.screenshot({path: `${output}/${name}.png`, fullPage: true});
  fs.writeFileSync(`${output}/${name}.txt`, await page.locator('body').innerText());
}
try {
  browser = await chromium.launch({headless: true, timeout: 15000,
    ...(executable ? {executablePath: executable} : {})});
  context = await browser.newContext({viewport: {width: 1280, height: 900}});
  context.setDefaultTimeout(8000);
  context.setDefaultNavigationTimeout(15000);
  page = await context.newPage();
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => {
    const parsed = new URL(request.url());
    if (parsed.origin !== new URL(url).origin) external.push(request.url());
    if (parsed.pathname === '/api/v1/commands') requests.push({
      method: request.method(), path: parsed.pathname,
      csrf_present: Boolean(request.headers()['x-krellbot-csrf']),
      body: request.postDataJSON(),
    });
  });
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('session_bootstrap', async () => {
    expect((await bootstrap).status()).toBe(200);
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
    expect((await context.cookies()).some(c => c.name === 'krellbot_session' && c.httpOnly)).toBe(true);
  });
  await page.getByRole('navigation', {name: 'Workstation navigation'})
    .getByRole('button', {name: 'Operations', exact: true}).click();
  await expect(page.getByTestId('operations-view')).toBeVisible();
  const initial = await state();
  await check('live_disabled', async () => {
    expect(initial.live.live_enabled).toBe(false);
    expect(initial.deployments).toEqual([]);
    expect(initial.alerts).toHaveLength(2);
  });
  const first = initial.alerts.find(a => a.code === 'LOCAL_ACK_ERROR_HTTP_FIXTURE');
  const second = initial.alerts.find(a => a.code === 'LOCAL_ACK_ERROR_NETWORK_FIXTURE');
  expect(first).toBeTruthy(); expect(second).toBeTruthy();
  const button = alert => page.getByTestId(`ops-alert-ack-${alert.id}`);
  const row = alert => page.getByTestId(`ops-alert-${alert.id}`);
  const failure = alert => row(alert).getByTestId('ops-alert-ack-error');
  await expect(button(first)).toBeVisible();
  await evidence('initial');

  // Remove only this isolated browser's session: the real backend must reject.
  const cookies = await context.cookies();
  await context.clearCookies();
  const rejected = page.waitForResponse(r => r.url().endsWith('/api/v1/commands'));
  await button(first).focus();
  await page.keyboard.press('Enter');
  await check('real_403_inline_error', async () => {
    const response = await rejected;
    expect(response.status()).toBe(403);
    expect((await response.json()).detail).toBe('session required');
    await expect(failure(first)).toHaveAttribute('role', 'alert');
    await expect(failure(first)).toContainText('Acknowledge failed: alerts.ack failed: 403');
    await expect(button(first)).toBeVisible();
    await expect(row(first).locator('.kbot-ops__alert-ack')).toHaveCount(0);
  });
  await check('refresh_failure_visible', async () => {
    await expect(page.getByTestId('ops-stale-warning')).toContainText('operations view failed: 403');
  });
  await check('row_error_isolation', async () => {
    await expect(failure(second)).toHaveCount(0);
    await expect(button(second)).toBeVisible();
  });
  await evidence('http-403-failure');
  await context.addCookies(cookies);
  await check('failed_ack_remains_unacknowledged', async () => {
    const actual = await state();
    expect(actual.alerts.find(a => a.id === first.id).acknowledged).toBe(false);
  });
  const success = page.waitForResponse(r => r.url().endsWith('/api/v1/commands'));
  await button(first).focus(); await page.keyboard.press('Enter');
  await check('retry_success_badge', async () => {
    const response = await success;
    expect(response.status()).toBe(200);
    expect((await response.json()).code).toBe('acknowledged');
    await expect(button(first)).toHaveCount(0);
    await expect(row(first).locator('.kbot-ops__alert-ack')).toHaveText('acknowledged');
    expect((await state()).alerts.find(a => a.id === first.id).acknowledged).toBe(true);
  });
  await check('retry_clears_error', async () => {
    await expect(failure(first)).toHaveCount(0);
    await expect(page.getByTestId('ops-stale-warning')).toHaveCount(0);
  });
  await evidence('http-retry-success');

  // Real Chromium offline mode, not request interception or a substituted server.
  await context.setOffline(true);
  await button(second).click();
  await check('network_inline_error', async () => {
    await expect(failure(second)).toHaveAttribute('role', 'alert');
    await expect(failure(second)).toContainText('Acknowledge failed: Failed to fetch');
    await expect(button(second)).toBeVisible();
    await expect(row(second).locator('.kbot-ops__alert-ack')).toHaveCount(0);
    await expect(page.getByTestId('ops-stale-warning')).toContainText('Failed to fetch');
  });
  await evidence('network-failure');
  await context.setOffline(false);
  expect((await state()).alerts.find(a => a.id === second.id).acknowledged).toBe(false);
  await page.setViewportSize({width: 390, height: 844});
  await check('mobile_keyboard', async () => {
    await expect(button(second)).toBeVisible();
    expect((await button(second).boundingBox()).height).toBeGreaterThanOrEqual(44);
    await button(second).focus();
    await expect(button(second)).toBeFocused();
    await page.keyboard.press('Enter');
  });
  await check('network_retry_success', async () => {
    await expect(button(second)).toHaveCount(0);
    await expect(row(second).locator('.kbot-ops__alert-ack')).toHaveText('acknowledged');
    await expect(failure(second)).toHaveCount(0);
    await expect(page.getByTestId('ops-stale-warning')).toHaveCount(0);
    expect((await state()).alerts.find(a => a.id === second.id).acknowledged).toBe(true);
  });
  await evidence('mobile-retry-success');
  await check('request_contract', async () => {
    expect(requests).toHaveLength(4);
    for (const [index, request] of requests.entries()) {
      expect(request.method).toBe('POST'); expect(request.csrf_present).toBe(true);
      expect(request.body).toEqual({schema_version: '1', command: 'alerts.ack',
        payload: {alert_id: index < 2 ? first.id : second.id}});
    }
  });
  await check('loopback_only', async () => expect(external).toEqual([]));
  await check('no_browser_errors', async () => expect(errors).toEqual([]));
  observations.browser_version = browser.version();
  observations.final_alerts = (await state()).alerts;
} catch (error) {
  observations.failure = String(error.stack || error);
  if (page) await evidence('failure').catch(() => {});
} finally {
  if (context) await context.setOffline(false).catch(() => {});
  if (browser) await browser.close();
  const qualified = Object.values(assertions).every(Boolean);
  fs.writeFileSync(`${output}/browser.json`, JSON.stringify({qualified,
    required_assertions: assertions, observations, requests, errors, external}, null, 2));
  process.exitCode = qualified ? 0 : 1;
}
"""


def serve() -> int:
    home = Path(os.environ["KRELLBOT_HOME"])
    for code in ("LOCAL_ACK_ERROR_HTTP_FIXTURE", "LOCAL_ACK_ERROR_NETWORK_FIXTURE"):
        journal.append({
            "ts": 1700000000, "kind": "tick", "venue": "local-paper-fixture",
            "pack": "local-alert-ack-error-only", "bar_ts": 1700000000,
            "detail": {"intent_refused": code, "pair": "PAPERUSD"},
        })
    server = WorkstationServer(home, dist_dir=ROOT / "frontend" / "dist")
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    try:
        server.start()
        print(f"RUNTIME_URL={server.url}", flush=True)
        stopped.wait(timeout=180)
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
    output = (args.output_dir or ROOT / "tests_tmp" / "alert-ack-error" / f"{sha[:12]}-{time.time_ns()}").resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    summary = {
        "source_sha": sha, "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, timeout=10)),
        "platform": sys.platform, "qualified": False, "commands": [],
        "isolated_home": True, "live_enabled": False,
        "failure_modes": "real backend session-gate 403 and Chromium offline; no request interception",
        "invocation": ["uv", "run", "--frozen", "python", "scripts/verify_alert_ack_error.py"],
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

    def stop(child: subprocess.Popen) -> None:
        if child.poll() is not None:
            return
        if os.name == "posix":
            os.killpg(child.pid, signal.SIGTERM)
        else:
            child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(child.pid, signal.SIGKILL)
            else:
                child.kill()
            child.wait(timeout=5)

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
                    start_new_session=os.name == "posix",
                )
                child.communicate(input=stdin, timeout=120)
                record["exit_code"] = child.returncode
            except subprocess.TimeoutExpired:
                record["exit_code"] = 124
            except OSError as error:
                log.write(str(error))
                record["exit_code"] = 127
            finally:
                if child is not None:
                    stop(child)
                    if child.stdin is not None:
                        child.stdin.close()
        return record["exit_code"]

    try:
        if run("build", ["npm", "run", "build"], ROOT / "frontend") != 0:
            raise RuntimeError("current frontend build failed")
        with tempfile.TemporaryDirectory(prefix="krellbot-ack-error-home-") as fresh_home:
            env["KRELLBOT_HOME"] = fresh_home
            argv = [sys.executable, str(Path(__file__).resolve()), "--serve"]
            backend_record = {"name": "backend", "argv": argv, "cwd": str(ROOT), "exit_code": None}
            summary["commands"].append(backend_record)
            with (output / "backend.log").open("w") as log:
                process = subprocess.Popen(
                    argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=os.name == "posix",
                )
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
                    stop(process)
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
