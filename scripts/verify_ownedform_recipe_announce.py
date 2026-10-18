#!/usr/bin/env python3
"""Exercise the saved owned-form recipe journey on real loopback + Chromium.

Run: uv run --frozen python scripts/verify_ownedform_recipe_announce.py
Evidence is retained outside the repository by default. This qualifies Linux
browser DOM/live-region mutations, not audible screen-reader or Windows output.
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

from krellbot import config

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
REQUIRED = [
    "bootstrap_session_csrf", "fresh_library", "saved_and_reopened",
    "initial_status", "non_recipe_no_mutation", "cross_status",
    "single_status", "repeat_cross_status", "repeat_single_status",
    "same_live_node", "keyboard_focus_preserved", "visually_hidden_accessible",
    "loopback_only", "no_browser_errors", "live_off_unarmed",
]

BROWSER = r'''
import { createRequire } from 'node:module';
import { writeFileSync } from 'node:fs';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const { chromium, expect } = require('@playwright/test');
const { url, out } = JSON.parse(process.env.RECIPE_VERIFY_CONFIG);
const results = {}, requests = [], errors = [], observations = [];
const single = 'Recipe: close versus one average. Enter and exit comparisons now mean close versus the single average. The Fast average length field is hidden.';
const cross = 'Recipe: two-average crossover. Enter and exit comparisons now mean fast average versus slow average. A Fast average length field has appeared.';
let browser, context, page, version;
const id = name => page.getByTestId(name);
const status = () => id('owned-strategy-form-recipe-status');
const recipe = () => page.locator('#kbot-owned-strategy-recipe');
async function check(name, action) { await action(); results[name] = true; }
async function settle() {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
async function tabTo(target) {
  await expect(target).toBeVisible();
  for (let n = 0; n < 160; n++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Keyboard target not reachable');
}
async function activate(target) { await tabTo(target); await page.keyboard.press('Enter'); }
async function assertState(value) {
  await expect(recipe()).toHaveValue(value);
  const node = status();
  await expect(node).toHaveCount(1);
  await expect(node).toHaveId('owned-strategy-form-recipe-status');
  await expect(node).toHaveAttribute('role', 'status');
  await expect(node).toHaveAttribute('aria-live', 'polite');
  await expect(node).toHaveAttribute('aria-atomic', 'true');
  expect(await node.evaluate(el => el.tagName)).toBe('P');
  expect(await node.textContent()).toBe(value === 'ma_cross' ? cross : single);
  await expect(page.locator('#kbot-owned-strategy-fastLength')).toHaveCount(value === 'ma_cross' ? 1 : 0);
  await expect(recipe()).not.toHaveAttribute('aria-invalid');
  await expect(recipe()).not.toHaveAttribute('aria-describedby');
  expect(await recipe().evaluate(el => el.parentElement.nextElementSibling.id)).toBe('owned-strategy-form-recipe-status');
  expect(await page.locator('label[for="kbot-owned-strategy-kind"] span').textContent())
    .toBe(value === 'ma_cross' ? 'Average type (both averages)' : 'Average type');
  for (const field of ['entryComparison', 'exitComparison']) {
    expect(await page.locator(`#kbot-owned-strategy-${field} option`).first().textContent())
      .toBe(value === 'ma_cross' ? 'fast average above slow' : 'close above');
  }
}
try {
  browser = await chromium.launch({headless: true, timeout: 20000,
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {})});
  version = browser.version();
  context = await browser.newContext({viewport: {width: 1280, height: 900}});
  await context.tracing.start({screenshots: true, snapshots: true, sources: false});
  page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.setDefaultNavigationTimeout(15000);
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => requests.push({path: new URL(request.url()).pathname,
    origin: new URL(request.url()).origin, method: request.method(),
    csrf: Boolean(request.headers()['x-krellbot-csrf'])}));
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'), {timeout: 15000});
  await page.goto(url);
  await check('bootstrap_session_csrf', async () => {
    const response = await bootstrap;
    expect(response.status()).toBe(200);
    expect((await response.json()).csrf_token.length).toBeGreaterThan(0);
    expect((await context.cookies()).some(c => c.name === 'krellbot_session' && c.httpOnly)).toBe(true);
    await expect(id('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
  });
  await activate(page.getByRole('navigation', {name: 'Workstation navigation'})
    .getByRole('button', {name: 'Strategies', exact: true}));
  await activate(id('library-toggle'));
  await check('fresh_library', async () => { await expect(id('library-empty')).toBeVisible(); });
  await activate(page.getByRole('button', {name: 'Create new owned strategy', exact: true}));
  await expect(id('owned-strategy-form')).toBeVisible();
  await activate(page.getByRole('button', {name: 'Save', exact: true}));
  await expect(id('editor-save-outcome')).toContainText(/saved new revision \S+/);
  await check('saved_and_reopened', async () => {
    const revision = (await id('editor-save-outcome').textContent()).match(/revision (\S+)/)[1];
    await activate(id('library-toggle'));
    await expect(id('saved-strategy-library')).toHaveCount(0);
    await activate(id('library-toggle'));
    const row = id('library-row').filter({hasText: revision});
    await activate(row.getByRole('button', {name: 'Reopen', exact: true}));
    await expect(id('editor-revision-id')).toContainText(revision);
    await expect(id('owned-strategy-form')).toBeVisible();
    const creates = requests.filter(r => r.method === 'POST' && r.path === '/api/v1/strategies/drafts');
    expect(creates).toHaveLength(1);
    expect(creates[0].csrf).toBe(true);
  });
  await settle();
  await check('initial_status', async () => { await assertState('close_vs_ma'); });
  await status().evaluate(el => {
    window.recipeStatusNode = el;
    window.recipeStatusMutations = [];
    window.recipeStatusObserver = new MutationObserver(records => {
      window.recipeStatusMutations.push(...records.map(r => ({type: r.type, text: el.textContent})));
    });
    window.recipeStatusObserver.observe(el, {childList: true, characterData: true, subtree: true});
  });
  await check('non_recipe_no_mutation', async () => {
    const name = page.locator('#kbot-owned-strategy-name');
    await tabTo(name);
    await page.keyboard.press('End');
    await page.keyboard.type(' edited');
    await settle();
    expect(await page.evaluate(() => window.recipeStatusMutations)).toEqual([]);
    await assertState('close_vs_ma');
  });
  await tabTo(recipe());
  for (const [name, value, key] of [
    ['cross_status', 'ma_cross', 'ArrowDown'],
    ['single_status', 'close_vs_ma', 'ArrowUp'],
    ['repeat_cross_status', 'ma_cross', 'ArrowDown'],
    ['repeat_single_status', 'close_vs_ma', 'ArrowUp'],
  ]) {
    const before = await page.evaluate(() => window.recipeStatusMutations.length);
    await page.keyboard.press(key);
    await check(name, async () => {
      await assertState(value);
      await settle();
      const mutations = await page.evaluate(() => window.recipeStatusMutations);
      expect(mutations.length).toBe(before + 1);
      expect(mutations.at(-1).text).toBe(value === 'ma_cross' ? cross : single);
    });
    await expect(recipe()).toBeFocused();
    expect(await status().evaluate(el => el === window.recipeStatusNode)).toBe(true);
    observations.push({name, value, text: await status().textContent(),
      mutations: await page.evaluate(() => window.recipeStatusMutations.slice()),
      aria: await status().ariaSnapshot()});
    await page.screenshot({path: `${out}/${name}.png`, fullPage: true});
  }
  results.same_live_node = true;
  results.keyboard_focus_preserved = true;
  await check('visually_hidden_accessible', async () => {
    const css = await status().evaluate(el => {
      const s = getComputedStyle(el);
      return {display: s.display, visibility: s.visibility, position: s.position,
        width: s.width, height: s.height, clip: s.clip, ariaHidden: el.getAttribute('aria-hidden')};
    });
    expect(css.display).not.toBe('none');
    expect(css.visibility).toBe('visible');
    expect(css.position).toBe('absolute');
    expect(css.width).toBe('1px');
    expect(css.height).toBe('1px');
    expect(css.clip).toBe('rect(0px, 0px, 0px, 0px)');
    expect(css.ariaHidden).toBeNull();
    expect(await status().ariaSnapshot()).toContain(single);
  });
} catch (error) {
  results.error = String(error.stack || error);
  if (page) await page.screenshot({path: `${out}/failure.png`, fullPage: true, timeout: 5000}).catch(() => {});
  process.exitCode = 1;
} finally {
  results.loopback_only = requests.length > 0 && requests.every(r => r.origin === new URL(url).origin);
  results.no_browser_errors = errors.length === 0;
  writeFileSync(`${out}/browser.json`, JSON.stringify({results, observations, requests, errors, browserVersion: version}, null, 2));
  if (page) await page.evaluate(() => window.recipeStatusObserver?.disconnect()).catch(() => {});
  try {
    if (context) await context.tracing.stop({path: `${out}/trace.zip`});
  } finally {
    if (browser) await browser.close();
  }
}
'''


def clean_env(home: Path) -> dict[str, str]:
    names = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "USERPROFILE",
             "LOCALAPPDATA", "PLAYWRIGHT_BROWSERS_PATH")
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update(KRELLBOT_HOME=str(home), KRELLBOT_ENABLE_LIVE="0",
               PYTHONUNBUFFERED="1", PYTHONPATH=str(ROOT / "src"),
               FRONTEND_PACKAGE=str(FRONTEND / "package.json"))
    chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    if chromium:
        env["CHROMIUM_EXECUTABLE"] = chromium
    return env


def stop(proc: subprocess.Popen) -> None:
    # Each subprocess owns a session; timeout cleanup includes its Chromium children.
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    elif proc.poll() is None:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="ownedform-recipe-announce-"))
    out.mkdir(parents=True, exist_ok=True)
    summary = {"qualified": False, "platform": platform.platform(), "output_dir": str(out),
               "required_assertions": dict.fromkeys(REQUIRED, False), "commands": [],
               "limits": "Browser DOM/accessibility evidence only; no audible AT or Windows qualification"}

    def run(argv: list[str], cwd: Path, env: dict[str, str], name: str, timeout: int) -> int:
        record = {"argv": argv, "cwd": str(cwd), "timeout_seconds": timeout, "log": str(out / name)}
        summary["commands"].append(record)
        with (out / name).open("w") as log:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            try:
                record["exit"] = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record["timed_out"] = True
                raise
            finally:
                stop(proc)
                record["exit"] = proc.returncode
                record["reaped"] = proc.poll() is not None
        return record["exit"]

    try:
        summary["source_sha"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()
        summary["source_status"] = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True, timeout=10)
        sources = ["frontend/src/features/strategies/OwnedStrategyForm.tsx",
                   "frontend/src/features/strategies/OwnedStrategyForm.signal.css",
                   "frontend/src/features/strategies/OwnedStrategyForm.recipeAnnounce.test.tsx",
                   "scripts/verify_ownedform_recipe_announce.py"]
        summary["source_hashes"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources}
        browser_file = out / "journey.mjs"
        browser_file.write_text(BROWSER)
        with tempfile.TemporaryDirectory(prefix="krellbot-recipe-home-") as temp:
            home = Path(temp)
            env = clean_env(home)
            assert not config.load_config(home).armed
            assert run(["npm", "run", "build"], FRONTEND, env, "build.log", 180) == 0, "Build failed"
            argv = [sys.executable, "-m", "krellbot.cli", "workstation", "--dist", str(FRONTEND / "dist")]
            record = {"argv": argv, "cwd": str(ROOT), "log": str(out / "backend.log"),
                      "startup_timeout_seconds": 20, "journey_timeout_seconds": 180}
            summary["commands"].append(record)
            with (out / "backend.log").open("w") as log:
                proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                        start_new_session=True)
                try:
                    deadline = time.monotonic() + 20
                    url = None
                    while time.monotonic() < deadline and proc.poll() is None:
                        match = re.search(r"Workstation running at (http://127\.0\.0\.1:\d+/)",
                                          (out / "backend.log").read_text())
                        if match:
                            url = match[1]
                            break
                        time.sleep(0.1)
                    assert url, "Backend startup failed; see backend.log"
                    env["RECIPE_VERIFY_CONFIG"] = json.dumps({"url": url, "out": str(out)})
                    code = run(["node", str(browser_file)], ROOT, env, "browser.log", 180)
                    browser = json.loads((out / "browser.json").read_text())
                    summary["browser_version"] = browser.get("browserVersion")
                    summary["browser_results"] = browser["results"]
                    for name in REQUIRED:
                        summary["required_assertions"][name] = browser["results"].get(name) is True
                    assert code == 0, browser["results"].get("error", "Browser failed")
                    assert proc.poll() is None, "Backend exited during journey"
                    record["alive_after_journey"] = True
                finally:
                    stop(proc)
                    record["exit"] = proc.returncode
                    record["reaped"] = proc.poll() is not None
            summary["required_assertions"]["live_off_unarmed"] = (
                env["KRELLBOT_ENABLE_LIVE"] == "0" and not config.load_config(home).armed)
        summary["qualified"] = all(summary["required_assertions"].values()) and all(
            c.get("reaped") and not c.get("timed_out") and
            (c.get("alive_after_journey") or c.get("exit") == 0) for c in summary["commands"])
    except Exception:
        summary["failure"] = traceback.format_exc()
    finally:
        summary["exit_code"] = 0 if summary["qualified"] else 1
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
