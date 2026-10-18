#!/usr/bin/env python3
"""Qualify promotion failure honesty against the real loopback workstation.

Run with uv run --frozen python scripts/verify_promote_failure.py.
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

from decimal import Decimal

from krellbot import config
from krellbot.api.serve import WorkstationServer

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = [
    "session_bootstrap", "live_disabled", "real_403_inline_error",
    "failed_promote_remains_unknown", "refresh_failure_visible",
    "retry_refusal_result", "retry_clears_error", "network_inline_error",
    "network_retry_refusal", "row_error_isolation", "mobile_keyboard",
    "request_contract", "loopback_only", "no_browser_errors",
    "prior_result_cleared_on_failure", "deployment_state_unchanged",
]

BROWSER = r"""
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
const { url, output, executable, required } = JSON.parse(process.env.PROMOTE_VERIFY_CONFIG);
const assertions = Object.fromEntries(required.map(name => [name, false]));
const requests = [], responses = [], errors = [], external = [], observations = {};
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
  await page.screenshot({path: `${output}/${name}.png`, fullPage: true, timeout: 8000});
  fs.writeFileSync(`${output}/${name}.txt`, await page.locator('body').innerText());
}
const pair1 = 'HTTPUSD', pair2 = 'NETWORKUSD';
const button = pair => page.getByTestId(`ops-promote-local-paper-fixture-${pair}`);
const row = pair => page.getByTestId(`ops-deployment-local-paper-fixture-${pair}`);
const result = pair => page.getByTestId(`ops-promote-result-local-paper-fixture-${pair}`);
const failure = pair => row(pair).getByTestId('ops-promote-error');
async function unknown(pair, message) {
  await expect(failure(pair)).toHaveAttribute('role', 'alert');
  await expect(failure(pair)).toHaveText(`Promote failed: ${message}`);
  await expect(button(pair)).toBeVisible();
  await expect(result(pair)).toHaveCount(0);
  await expect(row(pair).getByRole('status')).toHaveCount(0);
  await expect(row(pair)).not.toContainText(/confirmed|promoted/i);
}
async function retry(pair) {
  await expect(button(pair)).toBeEnabled();
  const reply = page.waitForResponse(r => r.url().endsWith('/api/v1/commands'), {timeout: 8000});
  await button(pair).focus();
  await page.keyboard.press('Enter');
  const response = await reply;
  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.code).toBe('live_disabled');
  expect(body.ok).toBe(false);
  await expect(result(pair)).toHaveText(`Refused: Live disabled — ${body.message}`);
  await expect(result(pair)).toHaveAttribute('role', 'status');
  await expect(button(pair)).toBeVisible();
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
      csrf_present: Boolean(request.headers()['x-krellbot-csrf']), body: request.postDataJSON(),
    });
  });
  page.on('response', response => {
    const path = new URL(response.url()).pathname;
    if (path === '/api/v1/commands' || path === '/api/v1/operations')
      responses.push({path, status: response.status()});
  });
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'), {timeout: 15000});
  await page.goto(url);
  await check('session_bootstrap', async () => {
    expect((await bootstrap).status()).toBe(200);
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
    expect((await context.cookies()).some(c => c.name === 'krellbot_session' && c.httpOnly)).toBe(true);
  });
  await page.getByRole('navigation', {name: 'Workstation navigation'})
    .getByRole('button', {name: 'Operations', exact: true}).click();
  await expect(button(pair1)).toBeVisible();
  const initial = await state();
  observations.initial_deployments = initial.deployments;
  await check('live_disabled', async () => {
    expect(initial.live.live_enabled).toBe(false);
    expect(initial.live.authorized).toEqual([]);
    expect(initial.deployments).toHaveLength(2);
    expect(initial.deployments.every(d => d.mode === 'paper' && d.pack_id.startsWith('LOCAL_PROMOTE_'))).toBe(true);
    await expect(page.getByTestId('ops-live-status')).toContainText('Live trading is disabled');
  });
  await evidence('initial');

  // Session removal makes the real backend reject the real production command.
  const cookies = await context.cookies();
  await context.clearCookies();
  const rejected = page.waitForResponse(r => r.url().endsWith('/api/v1/commands'), {timeout: 8000});
  await button(pair1).focus(); await page.keyboard.press('Enter');
  await check('real_403_inline_error', async () => {
    const response = await rejected;
    expect(response.status()).toBe(403);
    expect((await response.json()).detail).toBe('session required');
    await unknown(pair1, 'live.promote failed: 403');
  });
  await check('refresh_failure_visible', async () => {
    await expect(page.getByTestId('ops-stale-warning')).toContainText('operations view failed: 403');
  });
  await check('row_error_isolation', async () => {
    await expect(failure(pair2)).toHaveCount(0);
    await expect(button(pair2)).toBeVisible();
    await expect(button(pair2)).toBeEnabled();
  });
  await evidence('http-403-failure');
  await context.addCookies(cookies);
  await check('failed_promote_remains_unknown', async () => {
    expect((await state()).deployments).toEqual(initial.deployments);
    await expect(result(pair1)).toHaveCount(0);
  });
  await check('retry_refusal_result', async () => retry(pair1));
  await check('retry_clears_error', async () => {
    await expect(failure(pair1)).toHaveCount(0);
    await expect(page.getByTestId('ops-stale-warning')).toHaveCount(0);
  });
  await evidence('http-retry-refused');

  // Chromium offline is a real transport failure, not request interception.
  await expect(button(pair1)).toBeEnabled();
  await context.setOffline(true);
  await button(pair1).click();
  await check('prior_result_cleared_on_failure', async () => {
    await unknown(pair1, 'Failed to fetch');
    await expect(page.getByTestId('ops-stale-warning')).toContainText('Failed to fetch');
  });
  await expect(button(pair2)).toBeEnabled();
  await button(pair2).click();
  await check('network_inline_error', async () => {
    await unknown(pair2, 'Failed to fetch');
    await expect(page.getByTestId('ops-stale-warning')).toContainText('Failed to fetch');
  });
  await evidence('network-failure');
  await context.setOffline(false);
  await page.setViewportSize({width: 390, height: 844});
  await check('mobile_keyboard', async () => {
    await expect(button(pair2)).toBeVisible();
    expect((await button(pair2).boundingBox()).height).toBeGreaterThanOrEqual(44);
    await button(pair2).focus(); await expect(button(pair2)).toBeFocused();
  });
  await check('network_retry_refusal', async () => {
    await retry(pair2);
    await expect(failure(pair2)).toHaveCount(0);
    await expect(page.getByTestId('ops-stale-warning')).toHaveCount(0);
    await expect(failure(pair1)).toBeVisible();
  });
  await evidence('mobile-retry-refused');
  await check('deployment_state_unchanged', async () => {
    observations.final_deployments = (await state()).deployments;
    expect(observations.final_deployments).toEqual(initial.deployments);
  });
  await check('request_contract', async () => {
    expect(requests).toHaveLength(5);
    for (const [index, request] of requests.entries()) {
      expect(request.method).toBe('POST'); expect(request.csrf_present).toBe(true);
      expect(request.body).toEqual({schema_version: '1', command: 'live.promote', payload: {
        venue: 'local-paper-fixture', pair: index < 3 ? pair1 : pair2, revision_id: 'deployment',
      }});
    }
  });
  await check('loopback_only', async () => expect(external).toEqual([]));
  await check('no_browser_errors', async () => expect(errors).toEqual([]));
  observations.browser_version = browser.version();
} catch (error) {
  observations.failure = String(error.stack || error);
  if (page) await evidence('failure').catch(() => {});
} finally {
  if (context) await context.setOffline(false).catch(() => {});
  if (browser) await browser.close();
  const qualified = Object.values(assertions).every(Boolean);
  fs.writeFileSync(`${output}/browser.json`, JSON.stringify({qualified,
    required_assertions: assertions, observations, requests, responses, errors, external}, null, 2));
  process.exitCode = qualified ? 0 : 1;
}
"""


def serve() -> int:
    home = Path(os.environ["KRELLBOT_HOME"])
    config.save_config(home, config.Config(armed=[
        config.ArmedPack(
            pack_path="LOCAL_PROMOTE_FIXTURE_NOT_EXECUTABLE", pack_sha256="",
            pack_id=f"LOCAL_PROMOTE_{pair}_FIXTURE", pack_version="local-only",
            venue="local-paper-fixture", pair=pair, cap=Decimal("1"),
            stop=Decimal("0"), mode="paper", starting_cash=None,
            requires_license=False, armed_at_ts=1700000000,
        )
        for pair in ("HTTPUSD", "NETWORKUSD")
    ]))
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
    output = (args.output_dir or ROOT / "tests_tmp" / "promote-failure" / f"{sha[:12]}-{time.time_ns()}").resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    summary = {
        "source_sha": sha, "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, timeout=10)),
        "platform": sys.platform, "qualified": False, "commands": [],
        "isolated_home": True, "live_enabled": False,
        "failure_modes": "real backend session-gate 403 and Chromium offline; no request interception",
        "invocation": ["uv", "run", "--frozen", "python", "scripts/verify_promote_failure.py"],
        "fixture_scope": "two clearly labelled local paper deployment fixtures; no balances, keys or orders",
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
        with tempfile.TemporaryDirectory(prefix="krellbot-promote-failure-home-") as fresh_home:
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
                    env["PROMOTE_VERIFY_CONFIG"] = json.dumps({
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
