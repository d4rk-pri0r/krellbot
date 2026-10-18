#!/usr/bin/env python3
"""Qualify starter error semantics on the real loopback backend and Chromium.

Offline Chromium injects a network failure, without request interception or a
substituted client/server. Recovery uses ordinary navigation, not a retry control.
AX semantics are evidence for AT, not a claim of audible screen-reader testing.
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

from krellbot import config
from krellbot.api.serve import WorkstationServer

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "session_bootstrap_csrf", "live_disabled_unarmed", "lazy_before_intersection",
    "real_network_failure", "verbatim_error_paragraph", "alert_polite_ax_tree",
    "single_failure_live_region", "recovery_real_catalogue", "success_silent",
    "pick_seeds_real_pack", "loopback_only", "no_browser_errors",
]

BROWSER = r"""
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
const {url, output, executable, required} = JSON.parse(process.env.STARTER_VERIFY_CONFIG);
const assertions = Object.fromEntries(required.map(name => [name, false]));
const requests = [], failed = [], external = [], errors = [], observations = {};
let browser, context, page;
const id = name => page.getByTestId(name);
const cataloguePath = '/api/v1/packs/starters';
async function check(name, action) { await action(); assertions[name] = true; }
async function tabTo(target) {
  for (let i = 0; i < 150; i++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Keyboard target not reachable');
}
async function navigate(name) {
  const target = page.getByRole('navigation', {name: 'Workstation navigation'})
    .getByRole('button', {name, exact: true});
  await tabTo(target);
  await page.keyboard.press('Enter');
}
async function settle() {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
async function revealPicker() {
  for (let i = 0; i < 20; i++) {
    if (await id('starter-picker').evaluate(el => {
      const b = el.getBoundingClientRect(); return b.top < innerHeight && b.bottom > 0;
    })) return;
    await page.keyboard.press('PageDown');
    await page.waitForTimeout(100);
  }
  throw new Error('Picker not reachable with keyboard scrolling');
}
async function evidence(name) {
  await page.screenshot({path: `${output}/${name}.png`, fullPage: true, timeout: 8000});
  fs.writeFileSync(`${output}/${name}.txt`, await page.locator('body').innerText());
  fs.writeFileSync(`${output}/${name}.aria.txt`, await id('starter-picker').ariaSnapshot());
}
try {
  browser = await chromium.launch({headless: true, timeout: 15000,
    ...(executable ? {executablePath: executable} : {})});
  observations.browser_version = browser.version();
  context = await browser.newContext({viewport: {width: 1280, height: 300}});
  context.setDefaultTimeout(8000);
  context.setDefaultNavigationTimeout(15000);
  await context.tracing.start({screenshots: true, snapshots: true, sources: false});
  page = await context.newPage();
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => {
    const parsed = new URL(request.url());
    if (parsed.origin !== new URL(url).origin) external.push(request.url());
    if (parsed.pathname === cataloguePath) requests.push({method: request.method(),
      csrf_present: Boolean(request.headers()['x-krellbot-csrf'])});
  });
  page.on('requestfailed', request => {
    if (new URL(request.url()).pathname === cataloguePath) failed.push(request.failure());
  });
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('session_bootstrap_csrf', async () => {
    const response = await bootstrap;
    expect(response.status()).toBe(200);
    expect((await response.json()).csrf_token.length).toBeGreaterThan(0);
    await expect(id('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
    expect((await context.cookies()).some(c => c.name === 'krellbot_session' && c.httpOnly)).toBe(true);
  });
  await check('live_disabled_unarmed', async () => {
    const operations = await page.evaluate(async () => {
      const response = await fetch('/api/v1/operations', {credentials: 'include'});
      if (!response.ok) throw new Error(`operations failed: ${response.status}`);
      return response.json();
    });
    expect(operations.live.live_enabled).toBe(false);
    expect(operations.deployments).toEqual([]);
  });
  await page.evaluate(() => {
    window.starterLiveRegions = [];
    new MutationObserver(records => {
      for (const record of records) for (const node of record.addedNodes) {
        if (!(node instanceof Element)) continue;
        for (const el of [node, ...node.querySelectorAll('[role="alert"], [aria-live]')]) {
          if (el.closest('[data-testid="starter-picker"]') &&
              el.matches('[role="alert"], [aria-live]')) {
            window.starterLiveRegions.push({text: el.textContent, role: el.getAttribute('role'),
              live: el.getAttribute('aria-live')});
          }
        }
      }
    }).observe(document.body, {childList: true, subtree: true});
  });
  await context.setOffline(true);
  await navigate('Strategies');
  await expect(id('starter-picker-loading')).toBeVisible();
  await settle();
  await check('lazy_before_intersection', async () => {
    await expect(id('starter-picker')).not.toBeInViewport();
    expect(requests).toHaveLength(0);
    await expect(id('starter-picker').locator('[role="alert"], [aria-live]')).toHaveCount(0);
  });
  await revealPicker();
  const error = id('starter-picker-error');
  await expect(error).toBeVisible();
  await check('real_network_failure', async () => {
    expect(requests).toEqual([{method: 'GET', csrf_present: true}]);
    expect(failed).toHaveLength(1);
    expect(failed[0].errorText).toContain('ERR_INTERNET_DISCONNECTED');
  });
  await check('verbatim_error_paragraph', async () => {
    expect(await error.evaluate(el => el.tagName)).toBe('P');
    await expect(error).toHaveText('Could not load starter examples: Failed to fetch');
    await expect(error).toHaveAttribute('role', 'alert');
    await expect(error).toHaveAttribute('aria-live', 'polite');
    await expect(page.getByRole('region', {name: 'Free starter examples'})).toHaveCount(1);
  });
  await check('alert_polite_ax_tree', async () => {
    const cdp = await context.newCDPSession(page);
    try {
      const {result} = await cdp.send('Runtime.evaluate', {
        expression: 'document.querySelector("[data-testid=starter-picker-error]")'});
      const {node} = await cdp.send('DOM.describeNode', {objectId: result.objectId});
      const tree = await cdp.send('Accessibility.getPartialAXTree', {backendNodeId: node.backendNodeId});
      fs.writeFileSync(`${output}/failure-ax.json`, JSON.stringify(tree, null, 2));
      const alert = tree.nodes.find(n => n.role?.value === 'alert');
      expect(alert).toBeTruthy();
      expect(alert.ignored).toBe(false);
      expect(alert.properties.find(p => p.name === 'live').value.value).toBe('polite');
      const children = alert.childIds.map(id => tree.nodes.find(n => n.nodeId === id));
      expect(children.every(n => n && !n.ignored && n.role.value === 'StaticText')).toBe(true);
      expect(children.map(n => n.name.value).join('')).toBe('Could not load starter examples: Failed to fetch');
    } finally { await cdp.detach(); }
  });
  await settle();
  await check('single_failure_live_region', async () => {
    expect(await page.evaluate(() => window.starterLiveRegions)).toEqual([{
      text: 'Could not load starter examples: Failed to fetch', role: 'alert', live: 'polite'}]);
  });
  await evidence('offline-failure');
  await context.setOffline(false);
  await navigate('Home');
  await expect(id('starter-picker')).toHaveCount(0);
  const success = page.waitForResponse(r => r.url().endsWith(cataloguePath));
  await navigate('Strategies');
  await revealPicker();
  let catalogue;
  await check('recovery_real_catalogue', async () => {
    const response = await success;
    expect(response.status()).toBe(200);
    catalogue = await response.json();
    expect(catalogue.examples.length).toBeGreaterThan(0);
    await expect(id(`starter-picker-item-${catalogue.examples[0].id}`)).toBeVisible();
    expect(requests).toHaveLength(2);
    expect(requests.every(r => r.method === 'GET' && r.csrf_present)).toBe(true);
  });
  await settle();
  await check('success_silent', async () => {
    await expect(error).toHaveCount(0);
    await expect(id('starter-picker').locator('[role="alert"], [aria-live]')).toHaveCount(0);
    expect((await page.evaluate(() => window.starterLiveRegions)).length).toBe(1);
  });
  await check('pick_seeds_real_pack', async () => {
    const example = catalogue.examples[0];
    await tabTo(id(`starter-picker-item-${example.id}`).getByRole('button', {name: `Use ${example.label}`}));
    await page.keyboard.press('Enter');
    await expect(page.getByLabel(/raw json/i)).toHaveValue(JSON.stringify(example.pack, null, 2));
  });
  await evidence('online-success');
  observations.live_regions = await page.evaluate(() => window.starterLiveRegions);
  await check('loopback_only', async () => expect(external).toEqual([]));
  await check('no_browser_errors', async () => expect(errors).toEqual([]));
} catch (error) {
  observations.failure = String(error.stack || error);
  if (page) await evidence('failure').catch(() => {});
} finally {
  if (context) {
    await context.setOffline(false).catch(() => {});
    await context.tracing.stop({path: `${output}/trace.zip`}).catch(() => {});
  }
  if (browser) await browser.close();
  const qualified = Object.values(assertions).every(Boolean);
  fs.writeFileSync(`${output}/browser.json`, JSON.stringify({qualified,
    required_assertions: assertions, observations, requests, failed, external, errors}, null, 2));
  process.exitCode = qualified ? 0 : 1;
}
"""


def serve() -> int:
    home = Path(os.environ["KRELLBOT_HOME"])
    assert os.environ["KRELLBOT_ENABLE_LIVE"] == "0"
    assert not config.load_config(home).armed
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
    assert not config.load_config(home).armed
    return 0


def stop(child: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(child.pid, signal.SIGTERM)
        elif child.poll() is None:
            child.terminate()
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(child.pid, signal.SIGKILL)
        else:
            child.kill()
        child.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        return serve()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()
    output = (args.output_dir or ROOT / "tests_tmp" / "starter-picker-announce" / f"{sha[:12]}-{time.time_ns()}").resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    sources = ["frontend/src/features/strategies/StarterPicker.tsx",
               "frontend/src/features/strategies/StarterPicker.announce.test.tsx",
               "scripts/verify_starter_picker_announce.py"]
    summary = {
        "source_sha": sha,
        "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, timeout=10)),
        "source_hashes": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources},
        "platform": sys.platform, "qualified": False, "commands": [],
        "invocation": ["uv", "run", "--frozen", "python", "scripts/verify_starter_picker_announce.py"],
        "required_assertions": dict.fromkeys(REQUIRED, False), "output_dir": str(output),
        "isolation": "fresh temporary KRELLBOT_HOME; live off; no credentials; loopback only",
        "limits": "Chromium AX/DOM semantics, not audible screen reader or Windows qualification",
    }
    env = {key: value for key, value in os.environ.items() if not (
        key.startswith(("KRELLBOT_", "KRAKEN_", "COINBASE_", "STRIPE_", "PAYPAL_"))
        or any(word in key.upper() for word in ("SECRET", "TOKEN", "PASSWORD", "API_KEY"))
    )}
    env.update(KRELLBOT_ENABLE_LIVE="0", PYTHONUNBUFFERED="1")

    def run(name: str, argv: list[str], cwd: Path, stdin: str | None = None) -> int:
        record = {"name": name, "argv": argv, "cwd": str(cwd), "exit_code": None, "timeout_seconds": 120}
        summary["commands"].append(record)
        child = None
        with (output / f"{name}.log").open("w") as log:
            try:
                child = subprocess.Popen(argv, cwd=cwd, env=env, text=True,
                    stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name == "posix")
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
        with tempfile.TemporaryDirectory(prefix="krellbot-starter-announce-") as fresh_home:
            env["KRELLBOT_HOME"] = fresh_home
            if run("build", ["npm", "run", "build"], ROOT / "frontend") != 0:
                raise RuntimeError("current frontend build failed")
            argv = [sys.executable, str(Path(__file__).resolve()), "--serve"]
            record = {"name": "backend", "argv": argv, "cwd": str(ROOT), "exit_code": None,
                      "startup_timeout_seconds": 20, "lifetime_timeout_seconds": 180}
            summary["commands"].append(record)
            process = None
            with (output / "backend.log").open("w") as log:
                try:
                    process = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=log,
                        stderr=subprocess.STDOUT, start_new_session=os.name == "posix")
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
                    env["STARTER_VERIFY_CONFIG"] = json.dumps({"url": url, "output": str(output),
                        "required": REQUIRED, "executable": shutil.which("chromium") or shutil.which("chromium-browser")})
                    result = run("browser", ["node", "--input-type=module"], ROOT / "frontend", BROWSER)
                    browser_path = output / "browser.json"
                    if browser_path.exists():
                        browser = json.loads(browser_path.read_text())
                        summary["required_assertions"] = browser["required_assertions"]
                        summary["qualified"] = result == 0 and all(
                            summary["required_assertions"].get(name) is True for name in REQUIRED)
                finally:
                    if process is not None:
                        stop(process)
                        record["exit_code"] = process.returncode
                        if process.returncode != 0:
                            summary["qualified"] = False
    except Exception:
        summary["failure"] = traceback.format_exc()
        summary["qualified"] = False
    finally:
        summary["exit_code"] = 0 if summary["qualified"] else 1
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return summary["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
