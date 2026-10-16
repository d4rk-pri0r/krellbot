#!/usr/bin/env python3
"""Qualify kill engagement safety against the real loopback workstation.

Run with uv run --frozen python scripts/verify_ops_kill_engage.py.
Requires the locked frontend dependencies and a local headless Chromium.
"""
from __future__ import annotations

import argparse
import hashlib
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

from krellbot.api.serve import WorkstationServer

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = [
    "session_bootstrap", "live_disabled", "short_reason_refused",
    "whitespace_not_counted", "confirm_names_trimmed_reason", "cancel_no_command",
    "edit_invalidates_confirmation", "real_403_inline_error", "failed_engage_not_applied",
    "network_inline_error", "confirmed_engagement", "statusstrip_engaged",
    "request_contract", "mobile_keyboard", "loopback_only", "no_browser_errors",
]

BROWSER = r"""
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
const { url, output, executable, required } = JSON.parse(process.env.KILL_VERIFY_CONFIG);
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
  await check('live_disabled', async () => {
    const initial = await state();
    expect(initial.live.live_enabled).toBe(false);
    expect(initial.live.kill_switch.engaged).toBe(false);
    expect(initial.deployments).toEqual([]);
    expect(initial.alerts).toEqual([]);
  });
  const input = page.getByTestId('ops-kill-reason');
  const entry = page.getByTestId('ops-kill-engage');
  const confirm = page.getByTestId('ops-kill-engage-confirm');
  const submit = page.getByTestId('ops-kill-engage-confirm-submit');
  const error = page.getByTestId('ops-kill-engage-error');
  await input.fill('x'); await input.press('Enter');
  await check('short_reason_refused', async () => {
    const validation = page.getByTestId('ops-kill-reason-error');
    await expect(validation).toHaveAttribute('role', 'alert');
    await expect(validation).toContainText('at least 4 non-whitespace characters');
    await expect(input).toHaveAttribute('aria-describedby', await validation.getAttribute('id'));
    await expect(input).toHaveAttribute('aria-invalid', 'true');
    await expect(confirm).toHaveCount(0);
    expect(requests).toHaveLength(0);
    expect((await state()).live.kill_switch.engaged).toBe(false);
  });
  await evidence('short-reason-refused');
  await input.fill(' a b c '); await entry.click();
  await check('whitespace_not_counted', async () => {
    await expect(page.getByTestId('ops-kill-reason-error')).toBeVisible();
    await expect(confirm).toHaveCount(0); expect(requests).toHaveLength(0);
  });
  const reason = 'LOCAL KILL SAFETY FIXTURE — operator review';
  await input.fill(`  ${reason}  `); await entry.click();
  await check('confirm_names_trimmed_reason', async () => {
    await expect(confirm.locator('strong')).toHaveText(reason);
    expect(await confirm.locator('strong').textContent()).toBe(reason);
    await expect(submit).toHaveText('Confirm engage');
    expect(requests).toHaveLength(0);
  });
  await evidence('confirm-before-command');
  await page.getByTestId('ops-kill-engage-confirm-cancel').click();
  await check('cancel_no_command', async () => {
    await expect(confirm).toHaveCount(0); expect(requests).toHaveLength(0);
    expect((await state()).live.kill_switch.engaged).toBe(false);
  });
  await entry.click(); await input.fill('changed local fixture');
  await check('edit_invalidates_confirmation', async () => {
    await expect(confirm).toHaveCount(0); expect(requests).toHaveLength(0);
  });
  await input.fill(`  ${reason}  `); await entry.click();
  // Exercise the real session gate without substituting responses.
  const cookies = await context.cookies(); await context.clearCookies();
  const rejected = page.waitForResponse(r => r.url().endsWith('/api/v1/commands'));
  await submit.click();
  await check('real_403_inline_error', async () => {
    const response = await rejected; expect(response.status()).toBe(403);
    expect((await response.json()).detail).toBe('session required');
    await expect(error).toHaveAttribute('role', 'alert');
    await expect(error).toContainText('operations.kill failed: 403');
    await expect(error).toContainText('outcome unknown');
    await expect(confirm).toHaveCount(0);
  });
  await evidence('session-failure'); await context.addCookies(cookies);
  await check('failed_engage_not_applied', async () => {
    expect((await state()).live.kill_switch.engaged).toBe(false);
  });
  await entry.click(); await context.setOffline(true); await submit.click();
  await check('network_inline_error', async () => {
    await expect(error).toContainText('Failed to fetch');
    await expect(error).toContainText('outcome unknown');
    await expect(confirm).toHaveCount(0);
  });
  await evidence('network-failure'); await context.setOffline(false);
  expect((await state()).live.kill_switch.engaged).toBe(false);
  await page.setViewportSize({width: 390, height: 844});
  await entry.click();
  await check('mobile_keyboard', async () => {
    await expect(submit).toBeVisible();
    expect((await submit.boundingBox()).height).toBeGreaterThanOrEqual(44);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await submit.focus(); await expect(submit).toBeFocused();
  });
  await evidence('mobile-confirm');
  const success = page.waitForResponse(r => r.url().endsWith('/api/v1/commands'));
  await submit.press('Enter');
  await check('confirmed_engagement', async () => {
    const response = await success; expect(response.status()).toBe(200);
    expect((await response.json()).code).toBe('kill_switch_engaged');
    await expect(page.getByTestId('ops-kill-state')).toHaveText(`Kill switch: engaged — ${reason}`);
    await expect(confirm).toHaveCount(0); await expect(error).toHaveCount(0);
    await expect(input).toHaveValue('');
    const actual = await state(); expect(actual.live.kill_switch.engaged).toBe(true);
    expect(actual.live.kill_switch.reason).toBe(reason);
  });
  await check('statusstrip_engaged', async () => {
    await expect(page.getByTestId('live-orders-status')).toHaveText(`Kill switch: engaged — ${reason}`, {timeout: 20000});
    await expect(page.getByRole('region', {name: 'Status — kill switch engaged'})).toBeVisible();
  });
  await evidence('engaged-statusstrip');
  await check('request_contract', async () => {
    expect(requests).toHaveLength(3);
    for (const request of requests) {
      expect(request.method).toBe('POST'); expect(request.csrf_present).toBe(true);
      expect(request.body).toEqual({schema_version: '1', command: 'operations.kill', payload: {reason}});
    }
  });
  await check('loopback_only', async () => expect(external).toEqual([]));
  await check('no_browser_errors', async () => expect(errors).toEqual([]));
  observations.browser_version = browser.version();
  observations.final_kill_switch = (await state()).live.kill_switch;
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
    output = (args.output_dir or ROOT / "tests_tmp" / "ops-kill-engage" / f"{sha[:12]}-{time.time_ns()}").resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    (output / "browser.mjs").write_text(BROWSER)
    source_files = [
        "frontend/src/features/operations/OperationsView.tsx",
        "frontend/src/features/operations/OperationsView.killEngage.test.tsx",
        "scripts/verify_ops_kill_engage.py",
    ]
    summary = {
        "source_sha": sha, "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, timeout=10)),
        "source_hashes": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_files
        },
        "platform": sys.platform, "qualified": False, "commands": [],
        "isolated_home": True, "live_enabled": False,
        "failure_modes": "real backend session-gate 403 and Chromium offline; no request interception",
        "invocation": ["uv", "run", "--frozen", "python", "scripts/verify_ops_kill_engage.py"],
        "fixture_scope": "fresh empty domain storage; clearly labelled LOCAL KILL SAFETY FIXTURE reason only",
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
        with tempfile.TemporaryDirectory(prefix="krellbot-kill-engage-home-") as fresh_home:
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
                    env["KILL_VERIFY_CONFIG"] = json.dumps({
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
