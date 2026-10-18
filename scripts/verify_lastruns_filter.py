#!/usr/bin/env python3
"""Qualify mounted run filters using an isolated real backend and Chromium.

Only stdlib Python is required by this wrapper; Node uses the frontend's existing
Playwright dependency. Evidence defaults to a fresh temporary directory. This is
local Linux/host evidence, not Windows or live-trading qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
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
SOURCES = [
    "frontend/src/features/paper/LastRunsPanel.tsx",
    "frontend/src/features/paper/LastRunsPanel.signal.css",
    "frontend/src/features/paper/LastRunsPanel.filter.test.tsx",
    "scripts/verify_lastruns_filter.py",
]
ASSERTIONS = [
    "bootstrap_session_csrf", "mounted_controls", "source_derived_options",
    "venue_subset", "pack_search", "pair_search", "summary_search",
    "status_subset", "and_semantics", "honest_empty", "clear_restores",
    "underlying_count", "narrow_layout", "no_filter_requests", "loopback_only",
    "no_console_errors", "storage_unchanged", "live_disabled",
]
BROWSER = r'''
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const { chromium, expect } = require('@playwright/test');
const [url, out] = process.argv.slice(2);
const results = {}, requests = [], consoleErrors = [], pageErrors = [];
let browser, context, page;
const id = name => page.getByTestId(`paper-last-runs-${name}`);
async function check(name, action) { await action(); results[name] = true; }
try {
  browser = await chromium.launch({headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {})});
  context = await browser.newContext({viewport: {width: 1280, height: 900}});
  await context.tracing.start({screenshots: true, snapshots: true});
  page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push({text: msg.text(), location: msg.location()}); });
  page.on('pageerror', error => pageErrors.push(String(error)));
  page.on('request', request => requests.push({method: request.method(),
    origin: new URL(request.url()).origin, path: new URL(request.url()).pathname,
    csrf_present: !!request.headers()['x-krellbot-csrf']}));
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('bootstrap_session_csrf', async () => {
    const response = await bootstrap;
    expect(response.status()).toBe(200);
    expect((await response.json()).csrf_token.length).toBeGreaterThan(0);
    expect((await context.cookies()).some(c => c.httpOnly && c.value.length > 0)).toBe(true);
  });
  const historyResponse = page.waitForResponse(r => r.url().endsWith('/api/v1/paper/history') && r.status() === 200);
  await page.getByRole('navigation', {name: 'Workstation navigation'})
    .getByRole('button', {name: 'Workstation', exact: true}).click();
  const history = (await (await historyResponse).json()).runs;
  expect(history.length).toBe(4);
  const rows = id('table').locator('tbody tr');
  const venue = id('filter-venue'), query = id('filter-query'), status = id('filter-status');
  const clear = id('filter-clear');
  const totalWord = `${history.length} runs`;
  await expect(rows).toHaveCount(history.length);
  // Record the gap observation without injecting controls or replacing endpoints.
  results.toolbar_absent_observed = await id('filter').count() === 0;
  await check('mounted_controls', async () => {
    await expect(id('panel')).toBeVisible();
    await expect(id('filter')).toHaveCount(1);
    await expect(venue).toHaveRole('combobox');
    await expect(status).toHaveRole('combobox');
    await expect(query).toHaveRole('textbox');
    await expect(clear).toHaveCount(0);
  });
  await check('source_derived_options', async () => {
    expect(await venue.locator('option').evaluateAll(nodes => nodes.map(n => n.value)))
      .toEqual(['', ...new Set(history.map(r => r.venue))]);
    expect(await status.locator('option').evaluateAll(nodes => nodes.map(n => n.value)))
      .toEqual(['', ...new Set(history.map(r => r.status))]);
    await expect(status.locator('option').first()).toHaveText('all');
    await expect(venue.locator('option').first()).toHaveText('all');
  });
  const requestCount = requests.length;
  await page.screenshot({path: `${out}/all-runs.png`, fullPage: true});
  await check('venue_subset', async () => {
    await venue.selectOption('kraken');
    await expect(rows).toHaveCount(2);
    expect(await rows.locator('td:first-child').allTextContents()).toEqual(['kraken', 'kraken']);
  });
  await check('and_semantics', async () => {
    await query.fill('beta');
    await expect(id('filter-empty')).toHaveText('No runs match the current filters.');
    await expect(rows).toHaveCount(0);
    await venue.selectOption('');
    await expect(rows).toHaveCount(1);
  });
  await check('pack_search', async () => {
    await query.fill('  aLPHa  ');
    await expect(rows).toHaveCount(1);
    await expect(rows).toContainText('SUIUSD');
  });
  await check('pair_search', async () => {
    await query.fill('bTcUsD');
    await expect(rows).toHaveCount(1);
    await expect(rows).toContainText('BTCUSD');
  });
  await check('summary_search', async () => {
    await query.fill('2 TICKS');
    await expect(rows).toHaveCount(1);
    await expect(rows).toContainText('DOTUSD');
  });
  await query.fill('');
  await check('status_subset', async () => {
    await status.selectOption('active');
    await expect(rows).toHaveCount(1);
    await expect(rows).toContainText('SUIUSD');
  });
  await check('underlying_count', async () => {
    await expect(id('count')).toHaveText(totalWord);
  });
  await check('honest_empty', async () => {
    await query.fill('NO-SUCH-PAPER-RUN');
    await expect(rows).toHaveCount(0);
    await expect(id('filter-empty')).toHaveText('No runs match the current filters.');
    await expect(id('empty')).toHaveCount(0);
    await expect(id('count')).toHaveText(totalWord);
    await page.screenshot({path: `${out}/no-matches.png`, fullPage: true});
  });
  await check('clear_restores', async () => {
    await expect(clear).toHaveCount(1);
    await expect(clear).toHaveText('Clear filters');
    await clear.click();
    await expect(rows).toHaveCount(history.length);
    await expect(venue).toHaveValue('');
    await expect(status).toHaveValue('');
    await expect(query).toHaveValue('');
    await expect(clear).toHaveCount(0);
    await expect(id('filter-empty')).toHaveCount(0);
    await expect(id('count')).toHaveText(totalWord);
  });
  await check('narrow_layout', async () => {
    await page.setViewportSize({width: 390, height: 844});
    await expect(id('filter')).toHaveCSS('flex-direction', 'column');
    for (const control of [venue, query, status]) {
      await expect(control).toHaveCSS('min-height', '44px');
      await expect.poll(async () => (await control.boundingBox()).height).toBeGreaterThanOrEqual(44);
      const box = await control.boundingBox();
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(390);
    }
    await page.screenshot({path: `${out}/narrow.png`, fullPage: true});
  });
  await check('no_filter_requests', async () => {
    expect(requests.length).toBe(requestCount);
    expect(requests.filter(r => r.method !== 'GET').map(r => r.path))
      .toEqual(['/api/v1/session/bootstrap']);
    expect(requests.some(r => r.path === '/api/v1/paper/history' && r.csrf_present)).toBe(true);
  });
  await check('loopback_only', async () => {
    expect(requests.every(r => r.origin === new URL(url).origin)).toBe(true);
  });
  await check('no_console_errors', async () => {
    expect(consoleErrors).toEqual([]);
    expect(pageErrors).toEqual([]);
  });
  fs.writeFileSync(`${out}/panel.txt`, await id('panel').innerText());
  fs.writeFileSync(`${out}/panel-aria.yml`, await id('panel').ariaSnapshot());
} catch (error) {
  results.error = String(error.stack || error);
  process.exitCode = 1;
  if (page) await page.screenshot({path: `${out}/failure.png`, fullPage: true}).catch(() => {});
} finally {
  fs.writeFileSync(`${out}/browser.json`, JSON.stringify({results, requests, consoleErrors, pageErrors}, null, 2));
  if (context) await context.tracing.stop({path: `${out}/trace.zip`}).catch(() => {});
  if (browser) await browser.close();
}
'''


def clean_env(home: Path) -> dict[str, str]:
    allowed = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT",
               "USERPROFILE", "LOCALAPPDATA", "PLAYWRIGHT_BROWSERS_PATH")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update(KRELLBOT_HOME=str(home), KRELLBOT_ENABLE_LIVE="0",
               PYTHONUNBUFFERED="1", PYTHONPATH=str(ROOT / "src"),
               FRONTEND_PACKAGE=str(FRONTEND / "package.json"))
    chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    if chromium:
        env["CHROMIUM_EXECUTABLE"] = chromium
    return env


def seed(home: Path) -> None:
    # Synthetic local storage fixtures, consumed by the unmodified history API.
    journal = home / "journal"
    journal.mkdir(mode=0o700)
    rows = [("kraken", "SUIUSD", "LOCAL-FILTER-ALPHA", 1),
            ("coinbase", "BTCUSD", "LOCAL-FILTER-BETA", 1),
            ("kraken", "DOTUSD", "LOCAL-FILTER-GAMMA", 2),
            ("coinbase", "ETHUSD", "LOCAL-FILTER-DELTA", 1)]
    records = [dict(ts=1792108800 + index, kind="tick", venue=venue,
                    pack=pack, bar_ts=1792108800 + index,
                    detail={"pair": pair, "fixture": "local filter acceptance only"})
               for venue, pair, pack, ticks in rows for index in range(ticks)]
    history = journal / "2026-10.jsonl"
    history.write_text("".join(json.dumps(row) + "\n" for row in records))
    history.chmod(0o600)
    config = home / "config.json"
    config.write_text(json.dumps({"live_first_armed": False, "armed": [{
        "venue": "kraken", "pair": "SUIUSD", "pack_id": "LOCAL-FILTER-ALPHA",
        "mode": "paper", "entries_paused": True, "starting_cash": "100",
    }]}))
    config.chmod(0o600)


def snapshot(home: Path) -> dict[str, str]:
    files = [home / "config.json"]
    for folder in ("journal", "run"):
        files.extend((home / folder).rglob("*"))
    return {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files) if p.is_file()}


def stop(proc: subprocess.Popen) -> int:
    if proc.poll() is None:
        proc.terminate()
    try:
        return proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="lastruns-filter-"))
    out.mkdir(parents=True, exist_ok=True)
    summary = {"qualified": False, "required_assertions": {name: False for name in ASSERTIONS},
               "commands": [], "platform": platform.platform(),
               "limitations": "Synthetic local paper history; no live or Windows qualification. Independent Operator acceptance required."}

    def run(argv: list[str], cwd: Path, env: dict[str, str], name: str, timeout: int = 180) -> int:
        record = {"argv": argv, "cwd": str(cwd), "exit": None, "log": str(out / name)}
        summary["commands"].append(record)
        with (out / name).open("w") as log:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            try:
                record["exit"] = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record["timeout"] = True
                raise
            finally:
                # Reap only this owned process group, including Chromium on timeout.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=10)
                if record["exit"] is None:
                    record["exit"] = proc.returncode
        return record["exit"]

    try:
        summary["source_sha"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        summary["source_status"] = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
        summary["source_hashes"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}
        browser_file = out / "journey.mjs"
        browser_file.write_text(BROWSER)
        with tempfile.TemporaryDirectory(prefix="krellbot-filter-home-") as temp:
            home = Path(temp)
            env = clean_env(home)
            seed(home)
            before = snapshot(home)
            assert run(["npm", "run", "build"], FRONTEND, env, "build.log") == 0
            argv = [sys.executable, "-m", "krellbot.cli", "workstation", "--dist", str(FRONTEND / "dist")]
            log_path = out / "backend.log"
            record = {"argv": argv, "cwd": str(ROOT), "exit": None, "log": str(log_path)}
            summary["commands"].append(record)
            with log_path.open("w") as log:
                proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 25
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
                    code = run(["node", str(browser_file), url, str(out)], ROOT, env, "browser.log")
                    data = json.loads((out / "browser.json").read_text())
                    summary["browser"] = data["results"]
                    summary["required_assertions"].update({name: data["results"].get(name, False)
                                                         for name in ASSERTIONS if name not in ("storage_unchanged", "live_disabled")})
                finally:
                    record["exit"] = stop(proc)
            after = snapshot(home)
            (out / "storage-hashes.json").write_text(json.dumps({"before": before, "after": after}, indent=2))
            summary["required_assertions"]["storage_unchanged"] = before == after
            config = json.loads((home / "config.json").read_text())
            summary["required_assertions"]["live_disabled"] = env["KRELLBOT_ENABLE_LIVE"] == "0" and all(
                row["mode"] == "paper" and row["entries_paused"] for row in config["armed"])
            assert code == 0, data["results"].get("error", "Browser failed")
        summary["qualified"] = all(summary["required_assertions"].values()) and all(
            command["exit"] == 0 for command in summary["commands"])
    except Exception:
        summary["error"] = traceback.format_exc()
    finally:
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps({"qualified": summary["qualified"], "artifact": str(out / "summary.json"),
                          "error": summary.get("error")}, indent=2))
    return 0 if summary["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
