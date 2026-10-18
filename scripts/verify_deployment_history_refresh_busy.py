#!/usr/bin/env python3
"""Qualify toolbar refresh via real loopback session and headless Chromium.

Stdlib parent harness; the child imports the installed backend. Latency-only
integration wrapper forwards genuine API responses without browser interception.
DOM/AX evidence is not human screen-reader or platform qualification.
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
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
REQUIRED = ["bootstrap_session_csrf", "live_disabled", "initial_idle",
            "enter_busy", "enter_settled", "space_busy", "space_settled",
            "no_duplicate_reads", "request_contract", "loopback_only", "no_browser_errors"]


BROWSER = r"""
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const {chromium, expect} = require('@playwright/test');
const {url, output, executable} = JSON.parse(process.env.HISTORY_VERIFY_CONFIG);
const results = {}, requests = [], responses = [], errors = [];
let browser, context, page;
const endpoint = '/api/v1/operations/deployments';
async function check(name, action) { await action(); results[name] = true; }
async function tabTo(target) {
  for (let i = 0; i < 140; i++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Tab target unreachable');
}
const reads = () => requests.filter(r => r.path === endpoint).length;
try {
  browser = await chromium.launch({headless: true, timeout: 15000,
    ...(executable ? {executablePath: executable} : {})});
  context = await browser.newContext({viewport: {width: 1100, height: 760}});
  await context.tracing.start({screenshots: true, snapshots: true});
  page = await context.newPage();
  page.setDefaultTimeout(8000);
  page.setDefaultNavigationTimeout(15000);
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('request', r => requests.push({path: new URL(r.url()).pathname,
    origin: new URL(r.url()).origin, method: r.method(),
    csrf_present: !!r.headers()['x-krellbot-csrf']}));
  page.on('response', r => responses.push({path: new URL(r.url()).pathname, status: r.status()}));
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  // Avoid Chromium's unrelated implicit /favicon.ico request; no API interception.
  await page.addInitScript(() => document.addEventListener('DOMContentLoaded', () => {
    const icon = document.createElement('link');
    icon.rel = 'icon'; icon.href = 'data:,'; document.head.append(icon);
  }, {once: true}));
  await page.goto(url);
  await check('bootstrap_session_csrf', async () => {
    const reply = await bootstrap;
    expect(reply.status()).toBe(200);
    expect(typeof (await reply.json()).csrf_token).toBe('string');
    expect((await context.cookies()).some(c => c.name === 'krellbot_session' && c.httpOnly)).toBe(true);
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
  });
  const nav = page.getByRole('navigation', {name: 'Workstation navigation'});
  await tabTo(nav.locator('button[aria-current="page"]'));
  for (let i = 0; i < 5; i++) await page.keyboard.press('ArrowRight');
  await expect(nav.getByRole('button', {name: 'Operations', exact: true})).toBeFocused();
  await page.keyboard.press('Enter');
  const panel = page.getByTestId('ops-deployment-history');
  await expect(panel).toBeVisible();
  const button = panel.getByTestId('ops-history-refresh');
  const status = panel.getByTestId('ops-history-refresh-status');
  await check('live_disabled', async () => {
    const state = await page.evaluate(async () => {
      const r = await fetch('/api/v1/operations', {credentials: 'include'});
      if (!r.ok) throw new Error(`state ${r.status}`);
      return r.json();
    });
    expect(state.live.live_enabled).toBe(false);
    expect(state.live.authorized).toEqual([]);
    expect(state.deployments).toEqual([]);
  });
  await check('initial_idle', async () => {
    await expect(button).toBeEnabled();
    await expect(button).toHaveText('Refresh');
    await expect(button).not.toHaveAttribute('aria-busy');
    await expect(status).toHaveCount(0);
  });
  for (const [name, key] of [['enter', 'Enter'], ['space', 'Space']]) {
    await tabTo(button);
    const before = reads();
    await page.keyboard.press(key);
    await check(`${name}_busy`, async () => {
      await expect(button).toHaveAttribute('aria-busy', 'true');
      await expect(button).toBeDisabled();
      await expect(button).toBeFocused();
      await expect(button).toHaveText('Refreshing history…');
      await expect(button).toHaveAttribute('aria-keyshortcuts', 'Enter Space');
      await expect(status).toHaveAttribute('aria-live', 'polite');
      await expect(status).toHaveText('Refreshing history…');
      expect(await status.evaluate(el => el.parentElement.className)).toBe('kbot-ops__history-toolbar');
      expect(await status.getAttribute('role')).toBeNull();
      await expect.poll(reads).toBe(before + 1);
      await page.mouse.click(...await button.evaluate(el => {
        const r = el.getBoundingClientRect(); return [r.x + r.width/2, r.y + r.height/2];
      }));
      await page.keyboard.down('Enter');
      await page.keyboard.down('Enter');
      await page.keyboard.up('Enter');
      fs.writeFileSync(`${output}/${name}-busy-aria.yml`, await panel.ariaSnapshot());
      const cdp = await context.newCDPSession(page);
      fs.writeFileSync(`${output}/${name}-busy-ax.json`, JSON.stringify(await cdp.send('Accessibility.getFullAXTree'), null, 2));
      await cdp.detach();
      await page.screenshot({path: `${output}/${name}-busy.png`, fullPage: true});
    });
    await check(`${name}_settled`, async () => {
      await expect(button).toBeEnabled();
      await expect(button).not.toHaveAttribute('aria-busy');
      await expect(button).toHaveText('Refresh');
      await expect(status).toHaveText('Refresh complete');
      expect(reads()).toBe(before + 1);
      fs.writeFileSync(`${output}/${name}-settled-aria.yml`, await panel.ariaSnapshot());
      await page.screenshot({path: `${output}/${name}-settled.png`, fullPage: true});
    });
  }
  await check('no_duplicate_reads', async () => {
    expect(reads()).toBe(3);
    expect(responses.filter(r => r.path === endpoint).map(r => r.status)).toEqual([200, 200, 200]);
  });
  await check('request_contract', async () => {
    expect(requests.filter(r => r.path === endpoint).every(r => r.method === 'GET' && r.csrf_present)).toBe(true);
    expect(requests.filter(r => r.method !== 'GET').map(r => r.path)).toEqual(['/api/v1/session/bootstrap']);
  });
  await check('loopback_only', async () => expect(requests.every(r => r.origin === new URL(url).origin)).toBe(true));
  await check('no_browser_errors', async () => expect(errors).toEqual([]));
} catch (e) {
  results.error = String(e.stack || e);
  process.exitCode = 1;
  if (page) await page.screenshot({path: `${output}/probe-failure.png`, timeout: 5000}).catch(() => {});
} finally {
  fs.writeFileSync(`${output}/browser.json`, JSON.stringify({results, requests, responses, errors}, null, 2));
  if (context) await context.tracing.stop({path: `${output}/trace.zip`}).catch(() => {});
  if (browser) await browser.close();
}
"""


def serve(_scenario: str) -> int:
    import asyncio
    import secrets
    import socket
    import threading

    import uvicorn
    from krellbot import config, paths
    from krellbot.api.app import create_app

    home = Path(os.environ["KRELLBOT_HOME"])
    paths.ensure_layout()
    assert not config.load_config(home).armed
    assert os.environ["KRELLBOT_ENABLE_LIVE"] == "0"
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())

    class SlowHistoryResponse:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            async def delayed_send(message):
                if (scope["type"] == "http" and scope["method"] == "GET"
                        and scope["path"] == "/api/v1/operations/deployments"
                        and message["type"] == "http.response.start"):
                    print("DELAYED_HISTORY status=" + str(message["status"]), flush=True)
                    await asyncio.sleep(3)
                await send(message)
            await self.app(scope, receive, delayed_send)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        port = sock.getsockname()[1]
        app = create_app(home, port=port, bootstrap_token=secrets.token_urlsafe(32),
                         dist_dir=FRONTEND / "dist")
        server = uvicorn.Server(uvicorn.Config(SlowHistoryResponse(app), log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        try:
            thread.start()
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("real backend failed readiness")
                time.sleep(0.02)
            print(f"RUNTIME_URL=http://127.0.0.1:{port}/", flush=True)
            if not stopped.wait(timeout=180):
                return 124
        finally:
            server.should_exit = True
            thread.join(timeout=5)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--serve", choices=("refresh",), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        return serve(args.serve)
    output = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="deployment-history-refresh-busy-"))
    output.mkdir(parents=True, exist_ok=True)
    summary = {"qualified": False, "required_assertions": dict.fromkeys(REQUIRED, False),
               "commands": [], "scenarios": {}, "output_dir": str(output),
               "fixture_scope": "Real empty journal; delayed genuine history response; fresh home; live off; no keys",
               "limitations": "Linux Chromium DOM/AX only; no human screen-reader/Windows/Operator acceptance; empty favicon; real roving navigation (no operations test-id)"}
    env = {k: v for k, v in os.environ.items() if not (
        k.startswith(("KRELLBOT_", "KRAKEN_", "COINBASE_", "STRIPE_", "PAYPAL_"))
        or any(word in k.upper() for word in ("SECRET", "TOKEN", "PASSWORD", "API_KEY")))}
    env.update(KRELLBOT_ENABLE_LIVE="0", PYTHONUNBUFFERED="1", FRONTEND_PACKAGE=str(FRONTEND / "package.json"))

    def stop(child: subprocess.Popen) -> None:
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
        # Reap only this child's owned group, including Chromium on timeout.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def run(argv: list[str], cwd: Path, log: Path, timeout: int) -> int:
        record = {"argv": argv, "cwd": str(cwd), "log": str(log), "timeout_seconds": timeout, "exit": None}
        summary["commands"].append(record)
        with log.open("w") as stream:
            child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            record["pid"] = child.pid
            try:
                record["exit"] = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record["exit"] = 124
            finally:
                stop(child)
        return record["exit"]

    try:
        summary["source_sha"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()
        summary["source_status"] = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True, timeout=10)
        sources = ["frontend/src/features/operations/DeploymentHistory.tsx",
                   "frontend/src/features/operations/DeploymentHistory.refreshBusy.test.tsx",
                   "scripts/verify_deployment_history_refresh_busy.py"]
        summary["source_hashes"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources}
        with tempfile.TemporaryDirectory(prefix="history-build-home-") as temp:
            env["KRELLBOT_HOME"] = temp
            if run(["npm", "run", "build"], FRONTEND, output / "build.log", 120) != 0:
                raise RuntimeError("frontend build failed")
        browser_file = output / "journey.mjs"
        browser_file.write_text(BROWSER)
        
        for scenario in ("refresh",):
            evidence = output / scenario
            evidence.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=f"history-{scenario}-home-") as temp:
                home = Path(temp)
                env["KRELLBOT_HOME"] = temp
                argv = [sys.executable, str(Path(__file__).resolve()), "--serve", scenario]
                record = {"argv": argv, "cwd": str(ROOT), "log": str(evidence / "backend.log"),
                          "timeout_seconds": 180, "exit": None}
                summary["commands"].append(record)
                with (evidence / "backend.log").open("w") as stream:
                    child = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stream,
                                             stderr=subprocess.STDOUT, start_new_session=True)
                    record["pid"] = child.pid
                    try:
                        deadline = time.monotonic() + 20
                        url = None
                        while time.monotonic() < deadline:
                            match = re.search(r"RUNTIME_URL=(http://127[.]0[.]0[.]1:[0-9]+/)", (evidence / "backend.log").read_text())
                            if match:
                                url = match.group(1)
                                break
                            if child.poll() is not None:
                                raise RuntimeError("backend exited before readiness")
                            time.sleep(0.05)
                        if not url:
                            raise RuntimeError("backend readiness timed out")
                        
                        env["HISTORY_VERIFY_CONFIG"] = json.dumps({"url": url, "output": str(evidence),
                            "scenario": scenario, "executable": shutil.which("chromium") or shutil.which("chromium-browser")})
                        code = run(["node", str(browser_file)], FRONTEND, evidence / "browser.log", 120)
                        result = json.loads((evidence / "browser.json").read_text())
                        summary["scenarios"][scenario] = result
                        
                        if code != 0:
                            raise RuntimeError(f"{scenario} browser probe failed")
                    finally:
                        stop(child)
                        record["exit"] = child.returncode
                    if record["exit"] != 0:
                        raise RuntimeError("backend shutdown failed")
        result = summary["scenarios"]["refresh"]["results"]
        for name in REQUIRED:
            summary["required_assertions"][name] = result.get(name) is True
        summary["qualified"] = all(summary["required_assertions"].values())
    except Exception:
        summary["failure"] = traceback.format_exc()
    finally:
        summary["exit"] = 0 if summary["qualified"] else 1
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return summary["exit"]


if __name__ == "__main__":
    sys.exit(main())
