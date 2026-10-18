#!/usr/bin/env python3
"""Real loopback workstation/Chromium disclosure qualification; no live trading.

Writes current-SHA JSON, screenshots, accessibility snapshots and browser traces
into a fresh temporary artifact directory (or --output-dir).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

from krellbot import config, paths
from verify_paper_runs_keyboard import FRONTEND, ROOT, clean_env, seed_local_history, snapshot

ASSERTIONS = [
    "bootstrap_session_csrf", "empty_history", "collapsed_tab_focus",
    "enter_focused_expanded_named_target", "close_collapsed_no_stale_node",
    "space_focused_expanded_no_scroll", "idempotent_selection", "selection_switch",
    "click_preserved", "table_semantics", "unrelated_keys_ignored", "empty_fills",
    "session_failure_visible", "failure_keeps_history", "history_bytes_unchanged",
    "no_trading_requests", "loopback_only", "live_disabled_no_armed_records",
]

BROWSER = r'''
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const { chromium, expect } = require('@playwright/test');
const [url, scenario, out] = process.argv.slice(2);
const results = {};
const requests = [];
let browser, page, cdp;
const id = name => page.getByTestId(`paper-last-runs-${name}`);
async function check(name, action) { await action(); results[name] = true; }
async function tabTo(target) {
  for (let i = 0; i < 160; i++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Tab target unreachable');
}
async function accessibility(row, isExpanded, target, artifact) {
  const tree = await cdp.send('Accessibility.getFullAXTree');
  const name = await row.getAttribute('aria-label');
  const node = tree.nodes.find(n => n.role?.value === 'row' && n.name?.value === name);
  expect(node).toBeTruthy();
  const prop = name => node.properties.find(p => p.name === name)?.value;
  expect(prop('expanded')?.value).toBe(isExpanded);
  expect(prop('focused')?.value).toBe(true);
  if (isExpanded) {
    expect(prop('controls')?.relatedNodes.some(n => n.idref === target)).toBe(true);
    expect(tree.nodes.some(n => n.role?.value === 'region' &&
      n.name?.value === 'Selected paper run detail')).toBe(true);
  } else {
    expect(tree.nodes.some(n => n.role?.value === 'region' &&
      n.name?.value === 'Selected paper run detail')).toBe(false);
  }
  fs.writeFileSync(`${out}/${artifact}-ax.json`, JSON.stringify(tree, null, 2));
}
async function expanded(row, target) {
  await expect(row).toBeFocused();
  await expect(row).toHaveAttribute('aria-expanded', 'true');
  await expect(row).toHaveAttribute('aria-controls', target);
  await expect(id('detail')).toHaveAttribute('id', target);
  await expect(id('detail')).toHaveRole('region');
  await expect(id('detail')).toHaveAccessibleName('Selected paper run detail');
  expect(await row.evaluate(el => document.getElementById(el.getAttribute('aria-controls')) ===
    document.querySelector('[data-testid="paper-last-runs-detail"]'))).toBe(true);
}
async function closed(row, target) {
  await expect(id('detail')).toHaveCount(0);
  await expect(row).toHaveAttribute('aria-expanded', 'false');
  await expect(row).toHaveAttribute('aria-controls', target);
  expect(await page.evaluate(target => document.getElementById(target) === null, target)).toBe(true);
}
try {
  browser = await chromium.launch({ headless: true, timeout: 15000,
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {}) });
  const context = await browser.newContext({ viewport: {width: 1100, height: 760} });
  await context.tracing.start({screenshots: true, snapshots: true});
  page = await context.newPage();
  cdp = await context.newCDPSession(page);
  await cdp.send('Accessibility.enable');
  page.setDefaultTimeout(8000);
  page.setDefaultNavigationTimeout(15000);
  page.on('request', request => requests.push({path: new URL(request.url()).pathname,
    origin: new URL(request.url()).origin, method: request.method(),
    csrf_present: !!request.headers()['x-krellbot-csrf']}));
  page.on('response', response => {
    const request = [...requests].reverse().find(r => r.path === new URL(response.url()).pathname);
    if (request) request.status = response.status();
  });
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  const response = await bootstrap;
  await check('bootstrap_session_csrf', async () => {
    expect(response.status()).toBe(200);
    expect(typeof (await response.json()).csrf_token).toBe('string');
    expect((await context.cookies()).some(c => c.httpOnly && c.value.length > 0)).toBe(true);
  });
  await tabTo(page.getByRole('navigation', {name: 'Workstation navigation'})
    .getByRole('button', {name: 'Workstation', exact: true}));
  await page.keyboard.press('Enter');
  await expect(id('refresh')).toBeEnabled();
  if (scenario === 'empty') {
    await check('empty_history', async () => {
      await expect(id('empty')).toHaveText('No paper runs yet');
      await expect(id('table')).toHaveCount(0);
      await expect(id('detail')).toHaveCount(0);
      expect(await page.getByTestId('paper-last-runs-panel').locator('[aria-expanded]').count()).toBe(0);
    });
  } else {
    const row = id('row-kraken-SUIUSD');
    const other = id('row-kraken-DOTUSD');
    await expect(row).toBeVisible();
    const target = await row.getAttribute('aria-controls');
    expect(target).toBeTruthy();
    await check('table_semantics', async () => {
      await expect(row).toHaveRole('row');
      expect(await row.evaluate(el => el.tagName)).toBe('TR');
      await expect(id('table').getByRole('columnheader')).toHaveCount(9);
      await expect(row.locator('[aria-hidden="true"]')).toHaveText('›');
    });
    await tabTo(row);
    await check('collapsed_tab_focus', async () => {
      await expect(row).toBeFocused();
      await expect(row).toHaveAccessibleName('Open run detail for kraken SUIUSD');
      await closed(row, target);
      await accessibility(row, false, target, 'collapsed');
      fs.writeFileSync(`${out}/collapsed-aria.yml`, await row.ariaSnapshot());
    });
    await check('unrelated_keys_ignored', async () => {
      for (const key of ['Escape', 'ArrowDown', 'ArrowUp', 'ArrowRight', 'a']) {
        await page.keyboard.press(key);
        await closed(row, target);
      }
    });
    await check('enter_focused_expanded_named_target', async () => {
      await page.keyboard.press('Enter');
      await expanded(row, target);
      await accessibility(row, true, target, 'expanded');
      await expect(id('detail-summary')).toHaveText('1 tick, 1 fill, no refusal, closed');
      await expect(id('fills-table')).toContainText('LOCAL-KEYBOARD-FIXTURE-fill');
      fs.writeFileSync(`${out}/expanded-aria.yml`, await row.ariaSnapshot());
      fs.writeFileSync(`${out}/detail-aria.yml`, await id('detail').ariaSnapshot());
      await page.screenshot({path: `${out}/expanded.png`, fullPage: true});
    });
    await check('idempotent_selection', async () => {
      await id('detail').evaluate(el => { window.__originalDetail = el; });
      await page.keyboard.press('Enter');
      await page.keyboard.press('Space');
      await expanded(row, target);
      expect(await id('detail').evaluate(el => el === window.__originalDetail)).toBe(true);
    });
    await check('close_collapsed_no_stale_node', async () => {
      await tabTo(id('detail-close'));
      await page.keyboard.press('Enter');
      await closed(row, target);
      await tabTo(row);
      await expect(row).toBeFocused();
      await accessibility(row, false, target, 're-collapsed');
    });
    await check('space_focused_expanded_no_scroll', async () => {
      const before = await page.evaluate(() => [scrollX, scrollY]);
      await page.keyboard.press('Space');
      await expanded(row, target);
      await page.waitForTimeout(250);
      expect(await page.evaluate(() => [scrollX, scrollY])).toEqual(before);
      await tabTo(id('detail-close'));
      await page.keyboard.press('Space');
      await closed(row, target);
    });
    await check('click_preserved', async () => {
      await row.click();
      await expanded(row, target);
    });
    await check('selection_switch', async () => {
      await tabTo(other);
      await page.keyboard.press('Enter');
      await expanded(other, target);
      await expect(row).toHaveAttribute('aria-expanded', 'false');
      await expect(other).toHaveClass(/kbot-paper-runs__row--selected/);
    });
    await check('empty_fills', async () => {
      await expect(id('fills-empty')).toHaveText('no fills in this run');
      await expect(id('detail-summary')).toHaveText('1 tick, 0 fills, no refusal, closed');
      await tabTo(id('detail-close'));
      await page.keyboard.press('Enter');
      await closed(other, target);
    });
    expect(requests.some(r => r.path === '/api/v1/paper/history' && r.status === 200 && r.csrf_present)).toBe(true);
  }
  await context.clearCookies();
  await tabTo(id('refresh'));
  await page.keyboard.press('Enter');
  await check('session_failure_visible', async () => {
    await expect(id('error')).toContainText('paper history refused:');
    expect(requests.some(r => r.path === '/api/v1/paper/history' && r.status === 403)).toBe(true);
  });
  await check('failure_keeps_history', async () => {
    if (scenario === 'empty') await expect(id('empty')).toBeVisible();
    else {
      const row = id('row-kraken-SUIUSD');
      await tabTo(row);
      await page.keyboard.press('Enter');
      const target = await row.getAttribute('aria-controls');
      await expanded(row, target);
      await expect(id('fills-table')).toContainText('LOCAL-KEYBOARD-FIXTURE-fill');
      await tabTo(id('detail-close'));
      await page.keyboard.press('Space');
      await closed(row, target);
    }
  });
  await page.screenshot({path: `${out}/session-failure.png`, fullPage: true});
  await check('no_trading_requests', async () => {
    expect(requests.filter(r => r.method !== 'GET').map(r => r.path)).toEqual(['/api/v1/session/bootstrap']);
  });
  await check('loopback_only', async () => {
    expect(requests.every(r => r.origin === new URL(url).origin)).toBe(true);
  });
} catch (error) {
  results.error = String(error.stack || error);
  if (page) await page.screenshot({path: `${out}/failure.png`, fullPage: true}).catch(() => {});
  process.exitCode = 1;
} finally {
  fs.writeFileSync(`${out}/browser.json`, JSON.stringify({results, requests}, null, 2));
  if (page) await page.context().tracing.stop({path: `${out}/trace.zip`}).catch(() => {});
  if (browser) await browser.close();
}
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="last-runs-disclosure-"))
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "qualified": False, "required_assertions": {name: False for name in ASSERTIONS},
        "commands": [], "scenarios": {}, "platform": platform.platform(),
        "fixtures": "LOCAL-KEYBOARD-FIXTURE from existing paper storage helpers; test data only",
        "limitations": "Chromium accessibility/DOM evidence, not a human screen-reader speech test",
    }

    def run(argv: list[str], cwd: Path, env: dict[str, str], log: Path, timeout: int = 180) -> int:
        record = {"argv": argv, "cwd": str(cwd), "log": str(log), "exit": None, "timeout_seconds": timeout}
        summary["commands"].append(record)
        with log.open("w") as stream:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            record["pid"] = proc.pid
            try:
                record["exit"] = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record["exit"] = 124
                raise
            finally:
                # Node owns Chromium descendants; also reap them on a timeout.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)
        return record["exit"]

    try:
        summary["source_sha"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()
        summary["source_status"] = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True, timeout=10)
        sources = ["frontend/src/features/paper/LastRunsPanel.tsx",
                   "frontend/src/features/paper/LastRunsPanel.disclosureAria.test.tsx",
                   "scripts/verify_last_runs_disclosure_aria.py", "scripts/verify_paper_runs_keyboard.py"]
        summary["source_hashes"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources}
        browser_file = out / "journey.mjs"
        browser_file.write_text(BROWSER)
        with tempfile.TemporaryDirectory(prefix="disclosure-build-") as home:
            assert run(["npm", "run", "build"], FRONTEND, clean_env(Path(home)), out / "build.log") == 0
        for scenario in ("empty", "populated"):
            evidence = out / scenario
            evidence.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=f"disclosure-{scenario}-") as temp:
                home = Path(temp)
                env = clean_env(home)
                old_env = dict(os.environ)
                try:
                    os.environ.clear()
                    os.environ.update(env)
                    paths.ensure_layout()
                    if scenario == "populated":
                        seed_local_history(home)
                    safe_before = not config.load_config(home).armed and env["KRELLBOT_ENABLE_LIVE"] == "0"
                    assert safe_before
                finally:
                    os.environ.clear()
                    os.environ.update(old_env)
                before = snapshot(home)
                argv = [sys.executable, "-m", "krellbot.cli", "workstation", "--dist", str(FRONTEND / "dist")]
                log_path = evidence / "backend.log"
                record = {"argv": argv, "cwd": str(ROOT), "log": str(log_path), "exit": None,
                          "deadline_seconds": 220, "cleanup": "terminate owned backend in finally"}
                summary["commands"].append(record)
                with log_path.open("w") as stream:
                    proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
                    record["pid"] = proc.pid
                    try:
                        deadline = time.monotonic() + 20
                        url = None
                        while time.monotonic() < deadline:
                            match = re.search(r"Workstation running at (http://127\.0\.0\.1:\d+/)", log_path.read_text())
                            if match:
                                url = match[1]
                                break
                            if proc.poll() is not None:
                                break
                            time.sleep(0.1)
                        assert url, f"Backend unavailable: {log_path.read_text()}"
                        code = run(["node", str(browser_file), url, scenario, str(evidence)], ROOT, env, evidence / "browser.log")
                        data = json.loads((evidence / "browser.json").read_text())
                        summary["scenarios"][scenario] = data["results"]
                        assert code == 0, data["results"].get("error", "Browser failed")
                    finally:
                        if proc.poll() is None:
                            proc.terminate()
                        try:
                            record["exit"] = proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            record["exit"] = proc.wait(timeout=5)
                after = snapshot(home)
                (evidence / "storage-hashes.json").write_text(json.dumps({"before": before, "after": after}, indent=2))
                result = summary["scenarios"][scenario]
                result["history_bytes_unchanged"] = before == after
                old_env = dict(os.environ)
                try:
                    os.environ.clear()
                    os.environ.update(env)
                    result["live_disabled_no_armed_records"] = safe_before and not config.load_config(home).armed
                finally:
                    os.environ.clear()
                    os.environ.update(old_env)
        for name in ASSERTIONS:
            values = [r[name] for r in summary["scenarios"].values() if name in r]
            summary["required_assertions"][name] = bool(values) and all(v is True for v in values)
        summary["qualified"] = all(summary["required_assertions"].values()) and all(
            c["exit"] == 0 for c in summary["commands"])
    except Exception:
        summary["error"] = traceback.format_exc()
    finally:
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps({"qualified": summary["qualified"], "artifact": str(out / "summary.json"),
                          "error": summary.get("error")}, indent=2))
    return 0 if summary["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
