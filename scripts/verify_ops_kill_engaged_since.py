#!/usr/bin/env python3
"""Qualify engaged age with the real loopback backend and headless Chromium.

Run with uv run --frozen python scripts/verify_ops_kill_engaged_since.py.
The parent harness uses only stdlib; the backend child imports the real app.
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

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = [
    "session_bootstrap", "live_disabled", "seeded_seconds_epoch", "engaged_age",
    "additive_sibling", "release_command", "released_state", "age_removed",
    "loopback_only", "no_browser_errors",
]

BROWSER = r"""
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
const {url, output, executable, required} = JSON.parse(process.env.KILL_VERIFY_CONFIG);
const assertions = Object.fromEntries(required.map(name => [name, false]));
const observations = {}, errors = [], external = [];
let browser, context, page;
process.on('SIGTERM', () => {
  void (async () => { if (browser) await browser.close(); process.exit(124); })();
});
async function check(name, action) { await action(); assertions[name] = true; }
async function state() {
  return page.evaluate(async () => {
    const response = await fetch('/api/v1/operations', {credentials: 'include'});
    if (!response.ok) throw new Error(`operations: ${response.status}`);
    return response.json();
  });
}
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
  await context.tracing.start({screenshots: true, snapshots: true});
  page = await context.newPage();
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => {
    if (new URL(request.url()).origin !== new URL(url).origin) external.push(request.url());
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
  const panel = page.getByTestId('ops-kill');
  await expect(panel).toBeVisible();
  const initial = await state();
  observations.initial = initial.live;
  await check('live_disabled', async () => expect(initial.live.live_enabled).toBe(false));
  await check('seeded_seconds_epoch', async () => {
    const kill = initial.live.kill_switch;
    expect(kill.engaged).toBe(true);
    expect(kill.reason).toBe('operator hold since probe');
    expect(typeof kill.engaged_at).toBe('number');
    const age = Date.now() / 1000 - kill.engaged_at;
    expect(age).toBeGreaterThanOrEqual(90); expect(age).toBeLessThan(120);
  });
  const since = panel.getByTestId('ops-kill-engaged-since');
  await check('engaged_age', async () => {
    await expect(since).toBeVisible();
    await expect(since).toHaveText(/^Engaged for: 1m \d+s ago$/);
    observations.engaged_text = await since.textContent();
  });
  await check('additive_sibling', async () => {
    await expect(panel.getByTestId('ops-kill-state')).toHaveText('Kill switch: engaged — operator hold since probe');
    expect(await since.evaluate(el => ({tag: el.tagName, cls: el.className,
      previous: el.previousElementSibling?.getAttribute('data-testid')}))).toEqual({
      tag: 'P', cls: 'kbot-ops__kill-since', previous: 'ops-kill-state'});
  });
  await evidence('engaged');
  const released = page.waitForResponse(r => r.url().endsWith('/api/v1/commands'));
  await panel.getByTestId('ops-kill-release').click();
  await check('release_command', async () => {
    const response = await released;
    expect(response.status()).toBe(200);
    expect(response.request().postDataJSON()).toEqual({schema_version: '1', command: 'operations.release_kill', payload: {}});
    expect((await response.json()).code).toBe('kill_switch_released');
  });
  await check('released_state', async () => {
    await expect(panel.getByTestId('ops-kill-state')).toHaveText('Kill switch: released');
    await expect(panel).toContainText('Kill switch: released');
    const fresh = await state(); observations.released = fresh.live;
    expect(fresh.live.kill_switch).toEqual({engaged: false, reason: null, engaged_at: null});
  });
  await check('age_removed', async () => await expect(since).toHaveCount(0));
  await evidence('released');
  await check('loopback_only', async () => expect(external).toEqual([]));
  await check('no_browser_errors', async () => expect(errors).toEqual([]));
  observations.browser_version = browser.version();
} catch (error) {
  observations.failure = String(error.stack || error);
  if (page) await evidence('failure').catch(() => {});
} finally {
  try {
    if (context) await context.tracing.stop({path: `${output}/trace.zip`});
  } finally {
    if (browser) await browser.close();
    const qualified = required.every(name => assertions[name] === true);
    fs.writeFileSync(`${output}/browser.json`, JSON.stringify({qualified,
      required_assertions: assertions, observations, errors, external}, null, 2));
    process.exitCode = qualified ? 0 : 1;
  }
}
"""


def serve() -> int:
    # Imported only in the backend child, with this checkout on PYTHONPATH.
    from krellbot.api.serve import WorkstationServer
    from krellbot.application.live_gate import engage_kill

    home = Path(os.environ["KRELLBOT_HOME"])
    engage_kill(home, reason="operator hold since probe", now=int(time.time()) - 90)
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    server = WorkstationServer(home, dist_dir=ROOT / "frontend" / "dist")
    try:
        server.start()
        print(f"RUNTIME_URL={server.url}", flush=True)
        stopped.wait(timeout=150)
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
    output = (args.output_dir or ROOT / "tests_tmp" / "ops-kill-engaged-since" / f"{sha[:12]}-{time.time_ns()}").resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    (output / "browser.mjs").write_text(BROWSER)
    source_files = [
        "frontend/src/features/operations/OperationsView.tsx",
        "frontend/src/features/operations/OperationsView.engagedSince.test.tsx",
        "scripts/verify_ops_kill_engaged_since.py",
    ]
    summary = {
        "source_sha": sha, "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, timeout=10)),
        "source_hashes": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_files
        },
        "platform": sys.platform, "qualified": False, "commands": [],
        "isolated_home": True, "live_enabled": False,
        "qualification_scope": "Linux Chromium local journey only; not CI, platform or operator acceptance",
        "limits": ["Linux Chromium journey only; no Windows/platform qualification, CI waiver, integrator or independent Operator acceptance"],
        "fixture_scope": "Production engage_kill now-90 seconds in isolated local storage; no interception",
        "invocation": ["uv", "run", "--frozen", "python", "scripts/verify_ops_kill_engaged_since.py"],
        "required_assertions": dict.fromkeys(REQUIRED, False),
        "output_dir": str(output),
    }
    env = {key: value for key, value in os.environ.items() if not (
        key.startswith(("KRELLBOT_", "KRAKEN_", "COINBASE_", "STRIPE_", "PAYPAL_"))
        or any(word in key.upper() for word in ("SECRET", "TOKEN", "PASSWORD", "API_KEY"))
    )}
    env["KRELLBOT_ENABLE_LIVE"] = "0"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(ROOT / "src")
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
        record = {"name": name, "argv": argv, "cwd": str(cwd), "timeout_seconds": 120, "exit_code": None}
        if stdin is not None:
            record["stdin_artifact"] = "browser.mjs"
            record["stdin_sha256"] = hashlib.sha256(stdin.encode()).hexdigest()
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
        with tempfile.TemporaryDirectory(prefix="krellbot-engaged-since-home-") as fresh_home:
            env["KRELLBOT_HOME"] = fresh_home
            argv = [sys.executable, str(Path(__file__).resolve()), "--serve"]
            backend_record = {"name": "backend", "argv": argv, "cwd": str(ROOT), "timeout_seconds": 150, "exit_code": None}
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
