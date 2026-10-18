#!/usr/bin/env python3
"""Real loopback/Chromium qualification of the read-only paper history keyboard path.

Run with uv run --frozen python scripts/verify_paper_runs_keyboard.py.
Artifacts default to a fresh directory in the system temp directory. No platform
qualification beyond the actual recorded host is implied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from decimal import Decimal
from pathlib import Path

from krellbot import config, journal, paths
from krellbot.pack.model import Candle
from krellbot.venues.base import PairRules
from krellbot.venues.paper import PaperVenue

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
ASSERTIONS = [
    "bootstrap_session_csrf", "empty_history", "enter_opens_summary_fills",
    "space_opens_without_scroll", "keyboard_close_enter", "keyboard_close_space",
    "unrelated_keys_ignored", "empty_fills", "click_preserved", "table_semantics",
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
let browser;
let page;
const id = name => page.getByTestId(`paper-last-runs-${name}`);
async function tabTo(locator) {
  for (let i = 0; i < 160; i++) {
    if (await locator.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Keyboard tab target unreachable');
}
async function check(name, action) {
  await action();
  results[name] = true;
}
try {
  browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {}) });
  const context = await browser.newContext({ viewport: { width: 1100, height: 760 } });
  page = await context.newPage();
  page.on('request', request => requests.push({
    path: new URL(request.url()).pathname, origin: new URL(request.url()).origin,
    method: request.method(), csrf_present: !!request.headers()['x-krellbot-csrf'],
  }));
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
  const nav = page.getByRole('navigation', { name: 'Workstation navigation' });
  await tabTo(nav.getByRole('button', { name: 'Workstation', exact: true }));
  await page.keyboard.press('Enter');
  await expect(id('refresh')).toBeEnabled();
  const detail = id('detail');
  if (scenario === 'empty') {
    await check('empty_history', async () => {
      await expect(id('empty')).toHaveText('No paper runs yet');
      await expect(id('table')).toHaveCount(0);
      await expect(detail).toHaveCount(0);
    });
  } else {
    const row = id('row-kraken-SUIUSD');
    const emptyRow = id('row-kraken-DOTUSD');
    await expect(row).toBeVisible();
    await check('table_semantics', async () => {
      expect(await row.evaluate(el => el.tagName)).toBe('TR');
      await expect(id('table').getByRole('columnheader')).toHaveCount(9);
    });
    await tabTo(row);
    await check('unrelated_keys_ignored', async () => {
      for (const key of ['Escape', 'ArrowRight', 'a']) {
        await page.keyboard.press(key);
        await expect(detail).toHaveCount(0);
      }
    });
    await check('enter_opens_summary_fills', async () => {
      await page.keyboard.press('Enter');
      await expect(id('detail-summary')).toHaveText('1 tick, 1 fill, no refusal, closed');
      await expect(id('fills-table')).toContainText('LOCAL-KEYBOARD-FIXTURE-fill');
      await expect(id('fills-table')).toContainText('SUIUSD');
      await expect(id('fills-table')).toContainText('buy');
      await page.screenshot({ path: `${out}/enter-detail.png`, fullPage: true });
    });
    await check('keyboard_close_enter', async () => {
      await tabTo(id('detail-close'));
      await page.keyboard.press('Enter');
      await expect(detail).toHaveCount(0);
    });
    await tabTo(row);
    await check('space_opens_without_scroll', async () => {
      const before = await page.evaluate(() => ({ x: scrollX, y: scrollY,
        regions: [...document.querySelectorAll('[data-testid="paper-last-runs-scroll"]')].map(el => [el.scrollLeft, el.scrollTop]) }));
      await page.keyboard.press('Space');
      await expect(id('detail-summary')).toHaveText('1 tick, 1 fill, no refusal, closed');
      await page.waitForTimeout(250);
      const after = await page.evaluate(() => ({ x: scrollX, y: scrollY,
        regions: [...document.querySelectorAll('[data-testid="paper-last-runs-scroll"]')].map(el => [el.scrollLeft, el.scrollTop]) }));
      expect(after).toEqual(before);
    });
    await check('keyboard_close_space', async () => {
      await tabTo(id('detail-close'));
      await page.keyboard.press('Space');
      await expect(detail).toHaveCount(0);
    });
    await check('empty_fills', async () => {
      await tabTo(emptyRow);
      await page.keyboard.press('Space');
      await expect(id('fills-empty')).toHaveText('no fills in this run');
      await expect(id('detail-summary')).toHaveText('1 tick, 0 fills, no refusal, closed');
      await page.screenshot({ path: `${out}/empty-fills.png`, fullPage: true });
      await tabTo(id('detail-close'));
      await page.keyboard.press('Enter');
    });
    await check('click_preserved', async () => {
      await row.click();
      await expect(id('fills-table')).toContainText('LOCAL-KEYBOARD-FIXTURE-fill');
      await tabTo(id('detail-close'));
      await page.keyboard.press('Enter');
    });
    const history = requests.filter(r => r.path === '/api/v1/paper/history');
    expect(history.some(r => r.status === 200 && r.csrf_present)).toBe(true);
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
      await expect(id('row-kraken-SUIUSD')).toBeVisible();
      await tabTo(id('row-kraken-SUIUSD'));
      await page.keyboard.press('Enter');
      await expect(id('fills-table')).toContainText('LOCAL-KEYBOARD-FIXTURE-fill');
      await tabTo(id('detail-close'));
      await page.keyboard.press('Space');
      await expect(detail).toHaveCount(0);
    }
  });
  await page.screenshot({ path: `${out}/session-failure.png`, fullPage: true });
  fs.writeFileSync(`${out}/panel.txt`, await page.getByTestId('paper-last-runs-panel').innerText());
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
  if (browser) await browser.close();
}
'''


def clean_env(home: Path) -> dict[str, str]:
    names = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "USERPROFILE",
             "LOCALAPPDATA", "PLAYWRIGHT_BROWSERS_PATH")
    env = {key: os.environ[key] for key in names if key in os.environ}
    env.update(KRELLBOT_HOME=str(home), KRELLBOT_ENABLE_LIVE="0",
               PYTHONUNBUFFERED="1", PYTHONPATH=str(ROOT / "src"),
               FRONTEND_PACKAGE=str(FRONTEND / "package.json"))
    chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    if chromium:
        env["CHROMIUM_EXECUTABLE"] = chromium
    return env


def seed_local_history(home: Path) -> None:
    paths.ensure_layout()
    for pair in ("SUIUSD", "DOTUSD"):
        journal.append({"ts": 1792108800, "kind": "tick", "venue": "kraken",
                        "pack": "LOCAL-KEYBOARD-FIXTURE", "bar_ts": 1792108800,
                        "detail": {"pair": pair, "fixture": "local keyboard acceptance only"}})
    venue = PaperVenue(
        "kraken", home=home, starting_cash=Decimal("100"),
        rules_provider=lambda pair: PairRules(ordermin=Decimal("0.1"),
            costmin=Decimal("0.1"), lot_decimals=2, price_decimals=2),
        candle_reader=lambda venue, pair: [Candle(ts_ms=1792108800000, open=Decimal("2"),
            high=Decimal("2"), low=Decimal("2"), close=Decimal("2"), volume=Decimal("1"))],
        clock=lambda: 1792108800,
    )
    venue.place_entry_with_stop("LOCAL-KEYBOARD-FIXTURE-fill", Decimal("1"), Decimal("1"), pair="SUIUSD")


def snapshot(home: Path) -> dict[str, str]:
    return {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ("journal", "run") for p in sorted((home / folder).rglob("*")) if p.is_file()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="paper-runs-keyboard-"))
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True),
        "platform": platform.platform(), "qualified": False,
        "required_assertions": {name: False for name in ASSERTIONS}, "commands": [],
        "fixtures": "Clearly labelled LOCAL-KEYBOARD-FIXTURE paper data; no real keys or orders",
    }

    def run(argv: list[str], cwd: Path, env: dict[str, str], log: Path) -> int:
        record = {"argv": argv, "cwd": str(cwd), "log": str(log), "exit": None}
        summary["commands"].append(record)
        with log.open("w") as stream:
            result = subprocess.run(argv, cwd=cwd, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=180)
        record["exit"] = result.returncode
        return result.returncode

    try:
        source_files = ["frontend/src/features/paper/LastRunsPanel.tsx",
                        "frontend/src/features/paper/LastRunsPanel.keyboard.test.tsx",
                        "scripts/verify_paper_runs_keyboard.py"]
        summary["source_hashes"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source_files}
        browser_file = out / "journey.mjs"
        browser_file.write_text(BROWSER)
        with tempfile.TemporaryDirectory(prefix="krellbot-keyboard-build-") as build_home:
            assert run(["npm", "run", "build"], FRONTEND, clean_env(Path(build_home)), out / "build.log") == 0
        scenario_results = {}
        summary["scenarios"] = scenario_results
        for scenario in ("empty", "populated"):
            evidence = out / scenario
            evidence.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=f"krellbot-keyboard-{scenario}-") as temp:
                home = Path(temp)
                env = clean_env(home)
                old_env = dict(os.environ)
                try:
                    os.environ.clear()
                    os.environ.update(env)
                    paths.ensure_layout()
                    if scenario == "populated":
                        seed_local_history(home)
                    assert not config.load_config(home).armed
                    assert os.environ["KRELLBOT_ENABLE_LIVE"] == "0"
                finally:
                    os.environ.clear()
                    os.environ.update(old_env)
                before = snapshot(home)
                argv = [sys.executable, "-m", "krellbot.cli", "workstation", "--dist", str(FRONTEND / "dist")]
                record = {"argv": argv, "cwd": str(ROOT), "exit": None, "log": str(evidence / "backend.log"),
                          "cleanup": "SIGTERM after browser"}
                summary["commands"].append(record)
                log_path = evidence / "backend.log"
                with log_path.open("w") as stream:
                    proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
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
                        assert url, f"Real backend did not start: {log_path.read_text()}"
                        code = run(["node", str(browser_file), url, scenario, str(evidence)], ROOT, env, evidence / "browser.log")
                        data = json.loads((evidence / "browser.json").read_text())
                        scenario_results[scenario] = data["results"]
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
                assert before == after, "Read-only journey changed persisted history/paper state"
                scenario_results[scenario]["history_bytes_unchanged"] = True
                scenario_results[scenario]["live_disabled_no_armed_records"] = True
        summary["scenarios"] = scenario_results
        for name in ASSERTIONS:
            applicable = [result[name] for result in scenario_results.values() if name in result]
            summary["required_assertions"][name] = bool(applicable) and all(value is True for value in applicable)
        summary["qualified"] = all(summary["required_assertions"].values()) and all(
            item["exit"] == 0 for item in summary["commands"])
    except Exception:
        summary["error"] = traceback.format_exc()
    finally:
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps({"qualified": summary["qualified"], "artifact": str(out / "summary.json"),
                          "error": summary.get("error")}, indent=2))
    return 0 if summary["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
