#!/usr/bin/env python3
"""Qualify Home session recovery against the real loopback backend and Chromium.

Run: uv run --frozen python scripts/verify_recover_failure.py
Requires locked frontend dependencies and a local headless Chromium.
No interception, exchange credentials, orders, or persistent user home.
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

from krellbot.api.serve import WorkstationServer

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = [
    "session_bootstrap", "live_disabled", "expired_reload_401",
    "http_failure_inline", "retry_enabled", "network_failure_inline",
    "different_network_message", "mobile_keyboard_retry", "success_clears_both",
    "request_contract", "loopback_only", "no_browser_errors",
]

BROWSER = r"""
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
const { url, output, executable, required } = JSON.parse(process.env.RECOVER_VERIFY_CONFIG);
const assertions = Object.fromEntries(required.map(name => [name, false]));
const requests = [], failures = [], errors = [], external = [], observations = {};
let browser, context, page;
process.on('SIGTERM', () => {
  void (async () => { if (browser) await browser.close(); process.exit(124); })();
});
async function check(name, action) { await action(); assertions[name] = true; }
async function evidence(name) {
  await page.screenshot({path: `${output}/${name}.png`, fullPage: true, timeout: 8000});
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
    if (parsed.pathname.startsWith('/api/v1/session/')) requests.push({
      method: request.method(), path: parsed.pathname,
    });
  });
  page.on('requestfailed', request => failures.push({
    path: new URL(request.url()).pathname, error: request.failure()?.errorText,
  }));
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('session_bootstrap', async () => {
    const response = await bootstrap;
    expect(response.status()).toBe(200);
    expect(typeof (await response.json()).csrf_token).toBe('string');
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
    expect((await context.cookies()).some(c => c.name === 'krellbot_session' && c.httpOnly)).toBe(true);
  });
  await check('live_disabled', async () => {
    const state = await page.evaluate(async () => {
      const r = await fetch('/api/v1/operations', {credentials: 'include'});
      if (!r.ok) throw new Error(`operations failed: ${r.status}`);
      return r.json();
    });
    expect(state.live.live_enabled).toBe(false);
    expect(state.deployments).toEqual([]);
    await expect(page.getByTestId('app-home-availability')).toContainText('Live trading unavailable');
  });
  const cookies = await context.cookies();
  await context.clearCookies();
  const expired = page.waitForResponse(r => r.url().endsWith('/api/v1/session/csrf'));
  await page.reload();
  const banner = page.getByTestId('app-home-session-failure');
  const button = page.getByTestId('app-home-recover-session');
  const error = page.getByTestId('apphome-recover-error');
  await check('expired_reload_401', async () => {
    expect((await expired).status()).toBe(401);
    await expect(banner).toBeVisible();
    await expect(error).toHaveCount(0);
  });
  await evidence('expired-after-reload');
  const refused = page.waitForResponse(r => r.url().endsWith('/api/v1/session/csrf'));
  await button.click();
  await check('http_failure_inline', async () => {
    expect((await refused).status()).toBe(401);
    await expect(error).toHaveAttribute('role', 'alert');
    await expect(error).toContainText('Recovery failed: recovery refused');
    await expect(banner).toBeVisible();
    expect(await error.evaluate(el => el.previousElementSibling?.getAttribute('data-testid')))
      .toBe('app-home-recover-session');
  });
  observations.http_message = await error.innerText();
  await check('retry_enabled', async () => { await expect(button).toBeEnabled(); });
  await evidence('http-401-failure');

  // Chromium's real offline transport; no route interception or substituted responses.
  await context.setOffline(true);
  await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(false);
  await button.click();
  await check('network_failure_inline', async () => {
    await expect(error).toContainText('browser is offline; reconnect and retry');
    await expect(button).toBeEnabled();
    await expect(banner).toBeVisible();
    expect(failures.some(f => f.path === '/api/v1/session/csrf' && f.error.includes('INTERNET_DISCONNECTED'))).toBe(true);
  });
  await check('different_network_message', async () => {
    observations.network_message = await error.innerText();
    expect(observations.network_message).not.toBe(observations.http_message);
  });
  await evidence('network-failure');
  await context.setOffline(false);
  await context.addCookies(cookies);
  await page.setViewportSize({width: 390, height: 844});
  await evidence('mobile-before-retry');
  const recovered = page.waitForResponse(r => r.url().endsWith('/api/v1/session/csrf'));
  await check('mobile_keyboard_retry', async () => {
    await expect(button).toBeEnabled();
    expect((await button.boundingBox()).height).toBeGreaterThanOrEqual(44);
    await button.focus();
    await expect(button).toBeFocused();
    await page.keyboard.press('Enter');
  });
  await check('success_clears_both', async () => {
    const response = await recovered;
    expect(response.status()).toBe(200);
    expect(typeof (await response.json()).csrf_token).toBe('string');
    await expect(banner).toHaveCount(0);
    await expect(error).toHaveCount(0);
    await expect(page.getByTestId('app-home')).toBeVisible();
  });
  await evidence('mobile-recovery-success');
  await check('request_contract', async () => {
    expect(requests.filter(r => r.path.endsWith('/bootstrap'))).toEqual([
      {method: 'POST', path: '/api/v1/session/bootstrap'},
    ]);
    expect(requests.filter(r => r.path.endsWith('/csrf'))).toHaveLength(4);
    expect(requests.filter(r => r.path.endsWith('/csrf')).every(r => r.method === 'GET')).toBe(true);
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
    required_assertions: assertions, observations, requests, failures, errors, external}, null, 2));
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
    output = (args.output_dir or ROOT / "tests_tmp" / "recover-failure" / f"{sha[:12]}-{time.time_ns()}").resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    summary = {
        "source_sha": sha, "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, timeout=10)),
        "platform": sys.platform, "qualified": False, "commands": [],
        "isolated_home": True, "live_enabled": False,
        "failure_modes": "real backend session-gate 401 and Chromium offline; no request interception",
        "invocation": ["uv", "run", "--frozen", "python", "scripts/verify_recover_failure.py"],
        "fixture_scope": "fresh empty home; no fabricated domain data or credentials",
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
        with tempfile.TemporaryDirectory(prefix="krellbot-recover-failure-home-") as fresh_home:
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
                    env["RECOVER_VERIFY_CONFIG"] = json.dumps({
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
