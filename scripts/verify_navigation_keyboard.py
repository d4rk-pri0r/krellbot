#!/usr/bin/env python3
"""Qualify Workstation shell navigation keyboard behavior with the real loopback backend and Chromium.

Run: python3 scripts/verify_navigation_keyboard.py [--output-dir DIR]

Drives the bundled frontend (frontend/dist) served by the real loopback
workstation server with a real headless Chromium. No mouse input is used:
the nav row is reached with Tab and every view change is produced with
ArrowLeft/ArrowRight/Home/End keydown events on the bundled React tab
strip. No fixtures, credentials, response interception or fake clients.
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
REQUIRED = [
    "bootstrap_session", "aria_contract_preserved", "single_tab_stop",
    "arrow_right_walks_all_views", "arrow_left_walks_back",
    "home_end_shortcuts", "clamp_no_wrap", "tab_order_follows_active",
    "live_disabled", "loopback_only", "no_browser_errors", "storage_unchanged",
]

BROWSER = r'''
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const {chromium, expect} = require('@playwright/test');
const {url, out, executable} = JSON.parse(process.env.NAV_VERIFY_CONFIG);
const assertions = {}, requests = [], errors = [];
let browser, context, page, version;
const id = name => page.getByTestId(name);
const nav = () => page.getByRole('navigation', {name: 'Workstation navigation'});
const tabButton = label => nav().getByRole('button', {name: label, exact: true});
// Existing mount markers, one per view id, used to prove the keydown path
// really switched the rendered view (not just the focused button).
const MOUNT = {
  home: () => id('app-home'),
  workstation: () => page.getByRole('heading', {name: 'Paper workstation'}),
  strategies: () => id('library-toggle'),
  research: () => id('research-host'),
  studio: () => id('studio-node-count'),
  operations: () => id('operations-view'),
  deployments: () => id('live-preflight-panel'),
};
async function check(name, action) { await action(); assertions[name] = true; }
async function focusedNavLabel() {
  return page.evaluate(() => {
    const el = document.activeElement;
    return el && el.closest('[data-testid="kbot-nav"]') ? el.textContent.trim() : null;
  });
}
async function rowState() {
  return page.evaluate(() => {
    const items = Array.from(document.querySelectorAll('[data-testid="kbot-nav"] .kbot-nav__item'));
    return {
      labels: items.map(b => b.textContent.trim()),
      tabbable: items.filter(b => b.tabIndex === 0).map(b => b.textContent.trim()),
      current: items.filter(b => b.getAttribute('aria-current') === 'page').map(b => b.textContent.trim()),
      removed: items.filter(b => b.tabIndex === -1).length,
    };
  });
}
try {
  browser = await chromium.launch({headless: true, timeout: 20000,
    ...(executable ? {executablePath: executable} : {})});
  version = browser.version();
  context = await browser.newContext({viewport: {width: 1280, height: 900}});
  await context.tracing.start({screenshots: true, snapshots: true, sources: false});
  page = await context.newPage();
  page.setDefaultTimeout(8000);
  page.setDefaultNavigationTimeout(15000);
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => requests.push({path: new URL(request.url()).pathname,
    origin: new URL(request.url()).origin, method: request.method()}));
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('bootstrap_session', async () => {
    const response = await bootstrap;
    expect(response.status()).toBe(200);
    await expect(id('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
  });
  await check('aria_contract_preserved', async () => {
    await expect(nav()).toHaveAttribute('data-testid', 'kbot-nav');
    await expect(nav()).toHaveAttribute('aria-label', 'Workstation navigation');
    expect(await nav().locator('.kbot-nav__item').count()).toBe(7);
    await expect(tabButton('Home')).toHaveAttribute('aria-current', 'page');
    await expect(tabButton('Home')).toHaveAttribute('aria-pressed', 'true');
    for (const label of ['Workstation', 'Strategies', 'Research', 'Studio', 'Operations', 'Deploy']) {
      await expect(tabButton(label)).not.toHaveAttribute('aria-current');
      await expect(tabButton(label)).toHaveAttribute('aria-pressed', 'false');
    }
  });
  await check('single_tab_stop', async () => {
    expect(await rowState()).toEqual({
      labels: ['Home', 'Workstation', 'Strategies', 'Research', 'Studio', 'Operations', 'Deploy'],
      tabbable: ['Home'], current: ['Home'], removed: 6,
    });
    await tabButton('Home').focus();
    await expect(tabButton('Home')).toBeFocused();
    await page.keyboard.press('Tab');
    expect(await focusedNavLabel()).toBeNull();  // Tab leaves the row; no sibling is tabbable
    await page.keyboard.press('Shift+Tab');
    await expect(tabButton('Home')).toBeFocused();
  });
  const walk = [
    ['Workstation', 'workstation'], ['Strategies', 'strategies'], ['Research', 'research'],
    ['Studio', 'studio'], ['Operations', 'operations'], ['Deploy', 'deployments'],
  ];
  let operationsResponse = null;
  await check('arrow_right_walks_all_views', async () => {
    await tabButton('Home').focus();
    for (const [label, view] of walk) {
      if (view === 'operations') operationsResponse = page.waitForResponse(r => r.url().endsWith('/api/v1/operations'));
      await page.keyboard.press('ArrowRight');
      await expect(tabButton(label)).toBeFocused();
      await expect(tabButton(label)).toHaveAttribute('aria-current', 'page');
      await expect(MOUNT[view]()).toBeVisible();
    }
  });
  await check('arrow_left_walks_back', async () => {
    await page.keyboard.press('ArrowLeft');
    await expect(tabButton('Operations')).toBeFocused();
    await expect(MOUNT.operations()).toBeVisible();
    await page.keyboard.press('ArrowLeft');
    await expect(tabButton('Studio')).toBeFocused();
    await expect(MOUNT.studio()).toBeVisible();
  });
  await page.screenshot({path: `${out}/keyboard-arrows.png`, fullPage: true});
  await check('home_end_shortcuts', async () => {
    await page.keyboard.press('Home');
    await expect(tabButton('Home')).toBeFocused();
    await expect(MOUNT.home()).toBeVisible();
    await page.keyboard.press('End');
    await expect(tabButton('Deploy')).toBeFocused();
    await expect(MOUNT.deployments()).toBeVisible();
  });
  await check('clamp_no_wrap', async () => {
    await page.keyboard.press('End');   // already last: focus and view must not wrap
    await expect(tabButton('Deploy')).toBeFocused();
    await expect(MOUNT.deployments()).toBeVisible();
    await page.keyboard.press('Home');
    await page.keyboard.press('ArrowLeft');  // already first: no wrap, stays Home
    await expect(tabButton('Home')).toBeFocused();
    await expect(MOUNT.home()).toBeVisible();
  });
  await check('tab_order_follows_active', async () => {
    await page.keyboard.press('End');
    await expect(tabButton('Deploy')).toBeFocused();
    expect((await rowState()).tabbable).toEqual(['Deploy']);
    await page.keyboard.press('Tab');
    expect(await focusedNavLabel()).toBeNull();
    await page.keyboard.press('Shift+Tab');
    await expect(tabButton('Deploy')).toBeFocused();
    await page.keyboard.press('Home');
    await expect(tabButton('Home')).toBeFocused();
  });
  await check('live_disabled', async () => {
    expect(operationsResponse).toBeTruthy();
    const body = await (await operationsResponse).json();
    expect(body.live.live_enabled).toBe(false);
    expect(body.live.authorized).toEqual([]);
  });
  await page.screenshot({path: `${out}/keyboard-home.png`, fullPage: true});
} catch (error) {
  assertions.failure = String(error.stack || error);
  if (page) await page.screenshot({path: `${out}/failure.png`, fullPage: true, timeout: 5000}).catch(() => {});
  process.exitCode = 1;
} finally {
  assertions.loopback_only = requests.length > 0 && requests.every(r => r.origin === new URL(url).origin);
  assertions.no_browser_errors = errors.length === 0;
  if (context) await context.tracing.stop({path: `${out}/trace.zip`}).catch(error => {
    assertions.trace_error = String(error); process.exitCode = 1;
  });
  fs.writeFileSync(`${out}/browser.json`, JSON.stringify({assertions, requests, errors, version}, null, 2));
  if (browser) await browser.close();
}
'''


def clean_env(home: Path) -> dict[str, str]:
    names = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "USERPROFILE",
             "LOCALAPPDATA", "PLAYWRIGHT_BROWSERS_PATH")
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update(KRELLBOT_HOME=str(home), KRELLBOT_ENABLE_LIVE="0", PYTHONUNBUFFERED="1",
               PYTHONPATH=str(ROOT / "src"), FRONTEND_PACKAGE=str(FRONTEND / "package.json"))
    return env


def snapshot(home: Path) -> dict[str, str]:
    return {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
            for directory in ("drafts", "packs", "run", "journal")
            for p in sorted((home / directory).rglob("*")) if p.is_file()}


def stop(proc: subprocess.Popen) -> int:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        return proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        return proc.wait(timeout=5)
    finally:
        # Only this exclusively owned process group can contain server descendants.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="nav-keyboard-w1-"))
    out.mkdir(parents=True, exist_ok=True)
    summary = {"qualified": False, "required_assertions": dict.fromkeys(REQUIRED, False),
               "commands": [], "output_dir": str(out), "platform": platform.platform(),
               "invocation": [sys.executable, *sys.argv],
               "mechanism": "Real loopback backend and Chromium; keydown-only navigation (no mouse); no interception",
               "fixtures": "None: an isolated KRELLBOT_HOME; navigation works offline"}

    def run(argv: list[str], cwd: Path, env: dict[str, str], name: str, timeout: int) -> int:
        record = {"argv": argv, "cwd": str(cwd), "log": str(out / name), "timeout_seconds": timeout}
        summary["commands"].append(record)
        with (out / name).open("w") as log:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            record["pid"] = proc.pid
            try:
                record["exit"] = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record["exit"] = 124
            finally:
                record["cleanup_exit"] = stop(proc)
                record.setdefault("exit", record["cleanup_exit"])
                record["reaped"] = proc.poll() is not None
        return record["exit"]

    try:
        with tempfile.TemporaryDirectory(prefix="krellbot-nav-keyboard-home-") as temp:
            home = Path(temp)
            env = clean_env(home)
            assert run(["git", "rev-parse", "HEAD"], ROOT, env, "source-sha.log", 10) == 0
            summary["source_sha"] = (out / "source-sha.log").read_text().strip()
            source = ["frontend/src/shell/Navigation.tsx",
                      "frontend/src/shell/Navigation.keyboard.test.tsx",
                      "scripts/verify_navigation_keyboard.py"]
            summary["source_hashes"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source}
            before = snapshot(home)
            build = run(["npm", "run", "build"], FRONTEND, env, "build.log", 180)
            if build != 0 and "EACCES" in (out / "build.log").read_text():
                build = run(["npm", "run", "build", "--", "--configLoader", "runner"],
                            FRONTEND, env, "build-runner.log", 180)
                summary["build_workaround"] = "EACCES: supported configLoader runner; initial exit retained"
            assert build == 0, "Frontend build failed"
            browser_file = out / "journey.mjs"
            browser_file.write_text(BROWSER)
            argv = [sys.executable, "-m", "krellbot.cli", "workstation", "--dist", str(FRONTEND / "dist")]
            record = {"argv": argv, "cwd": str(ROOT), "log": str(out / "backend.log"),
                      "timeout_seconds": 190, "cleanup": "Owned process group terminated/reaped in finally"}
            summary["commands"].append(record)
            with (out / "backend.log").open("w") as log:
                proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=log,
                                        stderr=subprocess.STDOUT, start_new_session=True)
                record["pid"] = proc.pid
                try:
                    deadline = time.monotonic() + 20
                    url = None
                    while time.monotonic() < deadline:
                        match = re.search(r"Workstation running at (http://127\.0\.0\.1:\d+/)",
                                          (out / "backend.log").read_text())
                        if match:
                            url = match[1]
                            break
                        if proc.poll() is not None:
                            break
                        time.sleep(0.1)
                    assert url, "Backend startup deadline failed; see backend.log"
                    env["NAV_VERIFY_CONFIG"] = json.dumps({
                        "url": url, "out": str(out),
                        "executable": shutil.which("chromium") or shutil.which("chromium-browser"),
                    })
                    browser_exit = run(["node", str(browser_file)], ROOT, env, "browser.log", 150)
                    browser = json.loads((out / "browser.json").read_text())
                    for name in REQUIRED:
                        if name in browser["assertions"]:
                            summary["required_assertions"][name] = browser["assertions"][name] is True
                    summary["browser_version"] = browser["version"]
                    assert browser_exit == 0, browser["assertions"].get("failure", "Browser failed")
                finally:
                    record["exit"] = stop(proc)
                    record["reaped"] = proc.poll() is not None
                    after = snapshot(home)
                    (out / "storage-hashes.json").write_text(json.dumps({"before": before, "after": after}, indent=2))
                    summary["required_assertions"]["storage_unchanged"] = before == after
            summary["qualified"] = all(summary["required_assertions"].values()) and all(
                command.get("reaped") is True and command.get("exit") == 0
                for command in summary["commands"]
                if not (summary.get("build_workaround") and command["log"] == str(out / "build.log")))
    except (Exception, KeyboardInterrupt):
        summary["failure"] = traceback.format_exc()
    finally:
        summary["exit_code"] = 0 if summary["qualified"] else 1
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
