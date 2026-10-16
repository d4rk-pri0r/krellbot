#!/usr/bin/env python3
"""Qualify deployment-row keyboard behavior with real loopback API and Chromium.

Fresh test homes, live off, labelled journal fixtures. No HTTP interception.
Artifacts are runtime evidence, not human screen-reader or Operator acceptance.
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

from krellbot import config, journal, paths
from krellbot.api.serve import WorkstationServer

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
COMMON = ["bootstrap_session_csrf", "live_disabled", "request_contract", "loopback_only", "no_browser_errors"]
POPULATED = ["table_name_role", "tab_each_row", "enter_expand", "enter_collapse_focus_no_refetch",
             "space_expand_no_scroll", "space_collapse_focus_no_refetch", "arrows_ignored",
             "repeat_composition_ignored", "selection_switch", "mouse_preserved", "detail_failure",
             "list_failure_retry"]
REQUIRED = COMMON + POPULATED + ["empty_history", "storage_unchanged"]

BROWSER = r"""
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const {chromium, expect} = require('@playwright/test');
const {url, output, scenario, executable} = JSON.parse(process.env.HISTORY_VERIFY_CONFIG);
const results = {}, requests = [], responses = [], errors = [];
let browser, context, page;
const id = name => page.getByTestId(`ops-history-${name}`);
async function check(name, action) { await action(); results[name] = true; }
async function tabTo(target) {
  for (let i = 0; i < 140; i++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Tab target unreachable');
}
const fetchCount = () => requests.filter(r => r.path.startsWith('/api/v1/operations/deployments/')).length;
async function expanded(row, n) {
  await expect(row).toBeFocused();
  await expect(row).toHaveAttribute('aria-expanded', 'true');
  await expect(id(`detail-LOCAL-KEYBOARD-${n}`)).toBeVisible();
  await expect(id('detail-config')).toContainText('mode: paper');
  await expect(id('detail-schedule')).toContainText('timeframe: 1h');
  await expect(id('detail-summary')).toHaveText('LOCAL KEYBOARD TEST STATE ONLY');
}
async function collapsed(row, n, count) {
  await expect(row).toBeFocused();
  await expect(row).toHaveAttribute('aria-expanded', 'false');
  await expect(id(`detail-LOCAL-KEYBOARD-${n}`)).toHaveCount(0);
  expect(fetchCount()).toBe(count);
}
try {
  browser = await chromium.launch({headless: true, timeout: 15000,
    ...(executable ? {executablePath: executable} : {})});
  context = await browser.newContext({viewport: {width: 1100, height: 760}});
  await context.tracing.start({screenshots: true, snapshots: true});
  page = await context.newPage();
  page.setDefaultTimeout(8000);
  page.setDefaultNavigationTimeout(15000);
  page.on('pageerror', e => errors.push(String(e)));
  page.on('request', r => requests.push({path: new URL(r.url()).pathname,
    origin: new URL(r.url()).origin, method: r.method(),
    csrf_present: !!r.headers()['x-krellbot-csrf']}));
  page.on('response', r => responses.push({path: new URL(r.url()).pathname, status: r.status()}));
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('bootstrap_session_csrf', async () => {
    const reply = await bootstrap;
    expect(reply.status()).toBe(200);
    expect(typeof (await reply.json()).csrf_token).toBe('string');
    expect((await context.cookies()).some(c => c.name === 'krellbot_session' && c.httpOnly)).toBe(true);
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
  });
  await tabTo(page.getByRole('navigation', {name: 'Workstation navigation'})
    .getByRole('button', {name: 'Operations', exact: true}));
  await page.keyboard.press('Enter');
  const panel = page.getByTestId('ops-deployment-history');
  await expect(panel).toBeVisible();
  await expect(id('refresh')).toBeEnabled();
  await expect(id('preview-badge')).toHaveText('Local preview');
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
  if (scenario === 'empty') {
    await check('empty_history', async () => {
      await expect(id('empty')).toHaveText('No deployments yet. Local preview only — live trading unavailable.');
      await expect(panel.locator('[data-testid^="ops-history-row-"]')).toHaveCount(0);
      await expect(id('table')).toBeVisible();
    });
    await page.screenshot({path: `${output}/empty.png`, fullPage: true});
  } else {
    const row = id('row-LOCAL-KEYBOARD-1'), other = id('row-LOCAL-KEYBOARD-2');
    await expect(row).toBeVisible();
    await check('table_name_role', async () => {
      expect(await row.evaluate(el => el.tagName)).toBe('TR');
      await expect(id('table').locator('thead th')).toHaveCount(5);
      await expect(id('table').locator('tbody > tr')).toHaveCount(2);
      await expect(row).toHaveRole('button');
      await expect(row).toHaveAttribute('tabindex', '0');
      await expect(row).toHaveAccessibleName('Deployment LOCAL-KEYBOARD-1, paper');
      await expect(other).toHaveAccessibleName('Deployment LOCAL-KEYBOARD-2, paused');
      await expect(row).toHaveAttribute('aria-expanded', 'false');
    });
    await check('tab_each_row', async () => {
      await tabTo(id('refresh'));
      await page.keyboard.press('Tab');
      await expect(row).toBeFocused();
      await page.keyboard.press('Tab');
      await expect(other).toBeFocused();
      await page.keyboard.press('Shift+Tab');
      await expect(row).toBeFocused();
    });
    await check('arrows_ignored', async () => {
      const count = fetchCount();
      for (const key of ['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Escape', 'a']) {
        await page.keyboard.press(key);
        await collapsed(row, 1, count);
      }
      // Native button-style navigation is Tab, not a roving arrow grid.
      await page.keyboard.press('Tab');
      await expect(other).toBeFocused();
      await page.keyboard.press('Shift+Tab');
      await expect(row).toBeFocused();
    });
    await check('repeat_composition_ignored', async () => {
      const count = fetchCount();
      for (const key of ['Enter', ' ']) {
        await row.dispatchEvent('keydown', {key, repeat: true});
        await row.dispatchEvent('keydown', {key, isComposing: true});
      }
      await collapsed(row, 1, count);
    });
    await check('enter_expand', async () => {
      const count = fetchCount();
      await page.keyboard.press('Enter');
      await expanded(row, 1);
      expect(fetchCount()).toBe(count + 1);
      fs.writeFileSync(`${output}/expanded-aria.yml`, await row.ariaSnapshot());
      const cdp = await context.newCDPSession(page);
      const tree = await cdp.send('Accessibility.getFullAXTree');
      const node = tree.nodes.find(n => n.role?.value === 'button' &&
        n.name?.value === 'Deployment LOCAL-KEYBOARD-1, paper');
      expect(node).toBeTruthy();
      expect(node.properties.find(p => p.name === 'expanded').value.value).toBe(true);
      fs.writeFileSync(`${output}/expanded-ax.json`, JSON.stringify(tree, null, 2));
      await cdp.detach();
      await page.screenshot({path: `${output}/expanded.png`, fullPage: true});
    });
    await check('enter_collapse_focus_no_refetch', async () => {
      const count = fetchCount();
      await page.keyboard.press('Enter');
      await collapsed(row, 1, count);
    });
    await check('space_expand_no_scroll', async () => {
      await row.scrollIntoViewIfNeeded();
      const before = await page.evaluate(() => [scrollX, scrollY]);
      const count = fetchCount();
      await page.keyboard.press('Space');
      await expanded(row, 1);
      expect(fetchCount()).toBe(count + 1);
      await page.waitForTimeout(200);
      expect(await page.evaluate(() => [scrollX, scrollY])).toEqual(before);
    });
    await check('space_collapse_focus_no_refetch', async () => {
      const count = fetchCount();
      await page.keyboard.press('Space');
      await collapsed(row, 1, count);
    });
    await check('selection_switch', async () => {
      await page.keyboard.press('Enter');
      await expanded(row, 1);
      await page.keyboard.press('Tab');
      await expect(other).toBeFocused();
      await page.keyboard.press('Space');
      await expanded(other, 2);
      await expect(row).toHaveAttribute('aria-expanded', 'false');
      await expect(id('detail-LOCAL-KEYBOARD-1')).toHaveCount(0);
      const count = fetchCount();
      await page.keyboard.press('Enter');
      await collapsed(other, 2, count);
    });
    await check('mouse_preserved', async () => {
      const count = fetchCount();
      await row.click();
      await expanded(row, 1);
      expect(fetchCount()).toBe(count + 1);
      await row.click();
      await collapsed(row, 1, count + 1);
    });
    await context.clearCookies();
    await check('detail_failure', async () => {
      await tabTo(row);
      await page.keyboard.press('Enter');
      await expect(id('detail-error')).toHaveAttribute('role', 'alert');
      await expect(id('detail-error')).toContainText('deployment history failed: 403');
      await expect(row).toHaveAttribute('aria-expanded', 'true');
      expect(responses.some(r => r.path.endsWith('/LOCAL-KEYBOARD-1') && r.status === 403)).toBe(true);
      const count = fetchCount();
      await page.keyboard.press('Space');
      await collapsed(row, 1, count);
    });
    await check('list_failure_retry', async () => {
      await tabTo(id('refresh'));
      await page.keyboard.press('Enter');
      await expect(id('error')).toHaveAttribute('role', 'alert');
      await expect(id('error')).toContainText('Could not load deployments — check the workstation is running.');
      await expect(id('error')).toContainText('deployment history failed: 403');
      await expect(id('table')).toHaveCount(0);
      await expect(id('empty')).toHaveCount(0);
      await tabTo(id('retry'));
      const reply = page.waitForResponse(r => r.url().endsWith('/api/v1/operations/deployments') && r.status() === 403);
      await page.keyboard.press('Enter');
      await reply;
      await expect(id('error')).toContainText('403');
      await page.screenshot({path: `${output}/session-failure.png`, fullPage: true});
    });
  }
  await check('request_contract', async () => {
    const history = requests.filter(r => r.path.startsWith('/api/v1/operations/deployments'));
    expect(history.length).toBeGreaterThan(0);
    expect(history.every(r => r.method === 'GET' && r.csrf_present)).toBe(true);
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


def snapshot(home: Path) -> dict[str, str]:
    return {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in home.rglob("*") if p.is_file()}


def serve(scenario: str) -> int:
    home = Path(os.environ["KRELLBOT_HOME"])
    paths.ensure_layout()
    if scenario == "populated":
        for number, state in ((1, "paper"), (2, "paused")):
            journal.append({
                "ts": 1700000002 - number, "kind": "deployment", "venue": "local-test",
                "pack": "LOCAL-KEYBOARD-TEST", "bar_ts": 1700000000,
                "detail": {"deployment_id": f"LOCAL-KEYBOARD-{number}", "venue": "local-test",
                           "pair": "TESTUSD", "state": state, "config": {"mode": "paper"},
                           "schedule": {"timeframe": "1h"},
                           "last_execution_summary": "LOCAL KEYBOARD TEST STATE ONLY"},
            })
    assert not config.load_config(home).armed
    assert os.environ["KRELLBOT_ENABLE_LIVE"] == "0"
    server = WorkstationServer(home, dist_dir=FRONTEND / "dist")
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    try:
        server.start()
        print(f"RUNTIME_URL={server.url}", flush=True)
        if not stopped.wait(timeout=180):
            return 124
    finally:
        server.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--serve", choices=("empty", "populated"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        return serve(args.serve)
    output = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="deployment-history-keyboard-"))
    output.mkdir(parents=True, exist_ok=True)
    summary = {"qualified": False, "required_assertions": dict.fromkeys(REQUIRED, False),
               "commands": [], "scenarios": {}, "output_dir": str(output),
               "fixture_scope": "LOCAL-KEYBOARD test journal state only; fresh home; live off; no keys",
               "limitations": "Chromium DOM/AX evidence, not human screen-reader or Operator acceptance"}
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
                   "frontend/src/features/operations/DeploymentHistory.rowKeyboard.test.tsx",
                   "scripts/verify_deployment_history_row_keyboard.py"]
        summary["source_hashes"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources}
        with tempfile.TemporaryDirectory(prefix="history-build-home-") as temp:
            env["KRELLBOT_HOME"] = temp
            if run(["npm", "run", "build"], FRONTEND, output / "build.log", 120) != 0:
                raise RuntimeError("frontend build failed")
        browser_file = output / "journey.mjs"
        browser_file.write_text(BROWSER)
        storage_checks = []
        for scenario in ("empty", "populated"):
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
                        before = snapshot(home)
                        env["HISTORY_VERIFY_CONFIG"] = json.dumps({"url": url, "output": str(evidence),
                            "scenario": scenario, "executable": shutil.which("chromium") or shutil.which("chromium-browser")})
                        code = run(["node", str(browser_file)], FRONTEND, evidence / "browser.log", 120)
                        result = json.loads((evidence / "browser.json").read_text())
                        summary["scenarios"][scenario] = result
                        storage_checks.append(snapshot(home) == before)
                        if code != 0:
                            raise RuntimeError(f"{scenario} browser probe failed")
                    finally:
                        stop(child)
                        record["exit"] = child.returncode
                    if record["exit"] != 0:
                        raise RuntimeError("backend shutdown failed")
        empty = summary["scenarios"]["empty"]["results"]
        populated = summary["scenarios"]["populated"]["results"]
        for name in COMMON:
            summary["required_assertions"][name] = empty.get(name) is True and populated.get(name) is True
        for name in POPULATED:
            summary["required_assertions"][name] = populated.get(name) is True
        summary["required_assertions"]["empty_history"] = empty.get("empty_history") is True
        summary["required_assertions"]["storage_unchanged"] = len(storage_checks) == 2 and all(storage_checks)
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
