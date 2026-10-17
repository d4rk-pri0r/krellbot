#!/usr/bin/env python3
"""Qualify pack copy feedback on the real loopback backend and headless Chromium.

Run: uv run --frozen python scripts/verify_pack_copy_failure.py
Real browser permission denial and explicitly simulated unsupported API are separate probes.
Artifacts default to a fresh temporary directory; only the recorded host is qualified.
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
from pathlib import Path

from krellbot import config, paths
from krellbot.application.packs import list_packs

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
ASSERTIONS = [
    "bootstrap_session_csrf", "empty_inventory", "real_permission_denied",
    "row_bound_accessible_failure", "keyboard_retry_exact_bytes", "success_expires",
    "simulated_unsupported_api", "unsupported_retry", "filter_refresh_preserved",
    "mobile_keyboard", "session_failure_visible", "failure_keeps_inventory",
    "inventory_bytes_unchanged", "no_mutating_requests", "loopback_only",
    "live_disabled_no_armed_records",
]

BROWSER = r'''
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const { chromium, expect } = require('@playwright/test');
const [url, scenario, out] = process.argv.slice(2);
const results = {}, requests = [], permissionEvidence = {}, errors = [];
let browserVersion = null;
const packIds = ['LOCAL-PAPER-COPY-α exact', 'LOCAL-PAPER-COPY-bravo'];
let browser, page;
const id = name => page.getByTestId(`pack-library-${name}`);
const copy = i => id(`copy-${packIds[i]}`);
const row = i => id(`row-${packIds[i]}`);
const feedback = i => id(`copy-feedback-${packIds[i]}`);
async function tabTo(locator) {
  for (let i = 0; i < 180; i++) {
    if (await locator.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Keyboard target unreachable');
}
async function check(name, action) { await action(); results[name] = true; }
try {
  browser = await chromium.launch({headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {})});
  browserVersion = browser.version();
  const context = await browser.newContext({viewport: {width: 1100, height: 800}});
  await context.tracing.start({screenshots: true, snapshots: true, sources: false});
  page = await context.newPage();
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => requests.push({url: request.url(), method: request.method(),
    csrf_present: !!request.headers()['x-krellbot-csrf']}));
  page.on('response', response => {
    const request = [...requests].reverse().find(r => r.url === response.url());
    if (request) request.status = response.status();
  });
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  const response = await bootstrap;
  await check('bootstrap_session_csrf', async () => {
    expect(response.status()).toBe(200);
    expect((await response.json()).csrf_token.length).toBeGreaterThan(0);
    expect((await context.cookies()).some(c => c.httpOnly && c.value.length > 0)).toBe(true);
  });
  const nav = page.getByRole('navigation', {name: 'Workstation navigation'});
  await tabTo(nav.getByRole('button', {name: 'Strategies', exact: true}));
  await page.keyboard.press('Enter');
  await tabTo(page.getByTestId('strategies-packs-toggle'));
  await page.keyboard.press('Space');
  await expect(id('panel')).toBeVisible();
  if (scenario === 'empty') {
    await check('empty_inventory', async () => {
      await expect(id('empty')).toHaveText('No packs.');
      await expect(id('list')).toHaveCount(0);
      await expect(id('panel').getByRole('alert')).toHaveCount(0);
    });
  } else {
    await expect(row(0)).toBeVisible();
    await expect(row(1)).toBeVisible();
    const cdp = await context.newCDPSession(page);
    const {targetInfo} = await cdp.send('Target.getTargetInfo');
    await cdp.send('Browser.setPermission', {permission: {name: 'clipboard-write'},
      browserContextId: targetInfo.browserContextId,
      setting: 'denied', origin: new URL(url).origin});
    await check('real_permission_denied', async () => {
      permissionEvidence.denied = await page.evaluate(async () => ({
        apiPresent: typeof navigator.clipboard?.writeText === 'function',
        state: (await navigator.permissions.query({name: 'clipboard-write'})).state,
      }));
      expect(permissionEvidence.denied).toEqual({apiPresent: true, state: 'denied'});
      await tabTo(copy(0));
      await page.keyboard.press('Enter');
      await expect(row(0).getByRole('alert')).toBeVisible();
      await expect(feedback(0)).toHaveText('Copy');
    });
    await check('row_bound_accessible_failure', async () => {
      const alert = row(0).getByRole('alert');
      await expect(alert).toContainText(`Could not copy pack_id ${packIds[0]}`);
      await expect(copy(0)).toHaveAttribute('aria-describedby', await alert.getAttribute('id'));
      await expect(row(1).getByRole('alert')).toHaveCount(0);
      await expect(feedback(1)).toHaveText('Copy');
      await id('panel').screenshot({path: `${out}/real-permission-denied.png`});
    });
    await context.grantPermissions(['clipboard-read', 'clipboard-write'], {origin: new URL(url).origin});
    await check('keyboard_retry_exact_bytes', async () => {
      await tabTo(copy(0));
      await page.keyboard.press('Space');
      await expect(feedback(0)).toHaveText('Copied');
      await expect(row(0).getByRole('alert')).toHaveCount(0);
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(packIds[0]);
      await id('panel').screenshot({path: `${out}/retry-success.png`});
    });
    await check('success_expires', async () => { await expect(feedback(0)).toHaveText('Copy'); });
    await check('simulated_unsupported_api', async () => {
      // Deliberate API simulation, separate from real Chromium permission denial above.
      await page.evaluate(() => Object.defineProperty(navigator, 'clipboard', {configurable: true, value: undefined}));
      await copy(1).click();
      await expect(row(1).getByRole('alert')).toContainText('Could not copy pack_id');
      await expect(feedback(1)).toHaveText('Copy');
      await id('panel').screenshot({path: `${out}/SIMULATED-unsupported-api.png`});
      await page.evaluate(() => { delete navigator.clipboard; });
    });
    await check('unsupported_retry', async () => {
      await copy(1).click();
      await expect(feedback(1)).toHaveText('Copied');
      await expect(row(1).getByRole('alert')).toHaveCount(0);
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(packIds[1]);
    });
    await check('filter_refresh_preserved', async () => {
      await id('search').fill(packIds[0]);
      await id('bucket-select').selectOption('installed');
      await expect(id('count')).toHaveText('1 of 2 packs shown');
      const refresh = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/packs');
      await id('refresh').click();
      expect((await refresh).status()).toBe(200);
      await expect(id('search')).toHaveValue(packIds[0]);
      await expect(id('bucket-select')).toHaveValue('installed');
      await expect(row(0)).toBeVisible();
      await expect(row(1)).toHaveCount(0);
      await id('search').fill('LOCAL-PAPER-NO-SUCH-PACK');
      await expect(id('no-matches')).toBeVisible();
      await id('clear-filters').click();
      await expect(id('count')).toHaveText('2 of 2 packs shown');
    });
    await check('mobile_keyboard', async () => {
      await page.setViewportSize({width: 390, height: 844});
      await tabTo(copy(1));
      await page.keyboard.press('Enter');
      await expect(feedback(1)).toHaveText('Copied');
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(packIds[1]);
      const box = await copy(1).boundingBox();
      expect(box.height).toBeGreaterThanOrEqual(44);
      expect(box.width).toBeGreaterThanOrEqual(44);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await id('panel').screenshot({path: `${out}/mobile-keyboard.png`});
    });
  }
  expect(requests.some(r => new URL(r.url).pathname === '/api/v1/packs' && r.status === 200 && r.csrf_present)).toBe(true);
  await context.clearCookies();
  await tabTo(id('refresh'));
  await page.keyboard.press('Enter');
  await check('session_failure_visible', async () => {
    await expect(id('error')).toHaveText('Pack library failed (HTTP 403)');
    expect(requests.some(r => new URL(r.url).pathname === '/api/v1/packs' && r.status === 403)).toBe(true);
  });
  await check('failure_keeps_inventory', async () => {
    if (scenario === 'empty') await expect(id('empty')).toBeVisible();
    else { await expect(row(0)).toBeVisible(); await expect(row(1)).toBeVisible(); }
  });
  await page.screenshot({path: `${out}/session-failure.png`, fullPage: true});
  fs.writeFileSync(`${out}/panel.txt`, await id('panel').innerText());
  await check('no_mutating_requests', async () => {
    expect(requests.filter(r => r.method !== 'GET').map(r => new URL(r.url).pathname)).toEqual(['/api/v1/session/bootstrap']);
  });
  await check('loopback_only', async () => {
    expect(requests.every(r => new URL(r.url).origin === new URL(url).origin)).toBe(true);
    expect(errors).toEqual([]);
  });
  await context.tracing.stop({path: `${out}/trace.zip`});
} catch (error) {
  results.error = String(error.stack || error);
  if (page) await page.screenshot({path: `${out}/failure.png`, fullPage: true}).catch(() => {});
  process.exitCode = 1;
} finally {
  fs.writeFileSync(`${out}/browser.json`, JSON.stringify({results, requests, permissionEvidence, errors, browserVersion}, null, 2));
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
    for pack_id in ("LOCAL-PAPER-COPY-α exact", "LOCAL-PAPER-COPY-bravo"):
        paths.atomic_write(home / "packs" / f"{pack_id}.json", json.dumps({
            "id": pack_id, "public_label": "LOCAL PAPER HISTORY FIXTURE — not runnable",
            "version": "local-fixture", "permissions": [],
        }, ensure_ascii=False).encode("utf-8"))
    assert len(list_packs(home)) == 2


def snapshot(home: Path) -> dict[str, str]:
    return {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ("packs", "journal", "run") for p in sorted((home / folder).rglob("*")) if p.is_file()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="pack-copy-failure-"))
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True),
        "platform": platform.platform(), "qualified": False,
        "required_assertions": {name: False for name in ASSERTIONS}, "commands": [],
        "fixtures": "Clearly labelled LOCAL-PAPER-COPY non-runnable historical pack data; no real keys or orders",
    }

    def run(argv: list[str], cwd: Path, env: dict[str, str], log: Path) -> int:
        record = {"argv": argv, "cwd": str(cwd), "log": str(log), "exit": None}
        summary["commands"].append(record)
        with log.open("w") as stream:
            try:
                result = subprocess.run(argv, cwd=cwd, env=env, stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=180)
                record["exit"] = result.returncode
            except subprocess.TimeoutExpired:
                record["exit"] = 124
                stream.write("\nCommand timed out after 180 seconds\n")
            except OSError as error:
                record["exit"] = 127
                stream.write(f"\nCommand could not start: {error}\n")
        return record["exit"]

    try:
        source_files = ["frontend/src/features/packs/PackLibrary.tsx",
                        "frontend/src/features/packs/PackLibrary.clipboardFailure.test.tsx",
                        "scripts/verify_pack_copy_failure.py"]
        summary["source_hashes"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source_files}
        browser_file = out / "journey.mjs"
        browser_file.write_text(BROWSER)
        with tempfile.TemporaryDirectory(prefix="krellbot-copy-build-") as build_home:
            assert run(["npm", "run", "build"], FRONTEND, clean_env(Path(build_home)), out / "build.log") == 0
        scenario_results = {}
        summary["scenarios"] = scenario_results
        for scenario in ("empty", "populated"):
            evidence = out / scenario
            evidence.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=f"krellbot-copy-{scenario}-") as temp:
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
                scenario_results[scenario]["inventory_bytes_unchanged"] = True
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
