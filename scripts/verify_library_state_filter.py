#!/usr/bin/env python3
"""Qualify Library state filtering with the real loopback backend and Chromium.

Run: uv run --frozen python scripts/verify_library_state_filter.py
Only labelled local owned revisions are seeded through StrategyDraftService.
No credentials, live execution, intercepted responses or fake clients are used.
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

from krellbot import config, paths
from krellbot.application.strategy import StrategyDraftService

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
REQUIRED = [
    "bootstrap_session_csrf", "mounted_library", "exact_options_default_count",
    "draft_only_and_chips", "all_restores", "other_states", "state_then_search_empty",
    "escape_search_keeps_state", "clear_search_keeps_state", "keyboard_native_select",
    "mobile_control", "real_list_error_hides_filter", "session_recovery",
    "read_only_csrf_requests", "loopback_only", "no_browser_errors",
    "storage_unchanged", "live_off_unarmed",
]

BROWSER = r'''
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const {chromium, expect} = require('@playwright/test');
const {url, out, fixtures, executable} = JSON.parse(process.env.LIBRARY_VERIFY_CONFIG);
const assertions = {}, requests = [], errors = [], responses = [];
let browser, context, page, version;
const id = name => page.getByTestId(name);
const filter = () => id('library-state-filter');
const rows = () => id('library-row');
const total = fixtures.length;
async function check(name, action) { await action(); assertions[name] = true; }
async function count(n) { await expect(id('library-search-count')).toHaveText(`${n} of ${total} saved revisions`); }
async function stateRows(state) {
  const expected = fixtures.filter(row => state === 'all' || row.state === state);
  await expect(rows()).toHaveCount(expected.length);
  expect((await rows().evaluateAll(elements => elements.map(el => el.dataset.revisionId))).sort())
    .toEqual(expected.map(row => row.revision_id).sort());
  for (const row of expected) {
    const visible = page.locator(`[data-testid="library-row"][data-revision-id="${row.revision_id}"]`);
    await expect(visible.locator('[data-state]')).toHaveAttribute('data-state', row.state);
    await expect(visible).toContainText(row.label);
  }
  await count(expected.length);
}
async function tabTo(target) {
  for (let n = 0; n < 70; n++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Toolbar control not reachable with Tab');
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
    origin: new URL(request.url()).origin, method: request.method(),
    csrf: Boolean(request.headers()['x-krellbot-csrf'])}));
  page.on('response', response => responses.push({path: new URL(response.url()).pathname, status: response.status()}));
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('bootstrap_session_csrf', async () => {
    const response = await bootstrap;
    expect(response.status()).toBe(200);
    expect((await response.json()).csrf_token.length).toBeGreaterThan(0);
    expect((await context.cookies()).some(c => c.name === 'krellbot_session' && c.httpOnly)).toBe(true);
    await expect(id('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
  });
  const nav = page.getByRole('navigation', {name: 'Workstation navigation'});
  await tabTo(nav.getByRole('button', {name: 'Strategies', exact: true}));
  await page.keyboard.press('Enter');
  await tabTo(id('library-toggle'));
  await page.keyboard.press('Enter');
  await check('mounted_library', async () => {
    await expect(id('saved-strategy-library')).toBeVisible();
    await expect(filter()).toBeVisible();
    await expect(id('library-error')).toHaveCount(0);
    await expect(rows()).toHaveCount(total);
  });
  await check('exact_options_default_count', async () => {
    await expect(page.getByRole('combobox', {name: 'State', exact: true})).toHaveAttribute('id', 'library-state-filter');
    expect(await filter().evaluate(el => ({tag: el.tagName, toolbar: Boolean(el.closest('.kbot-strategy-library__toolbar'))})))
      .toEqual({tag: 'SELECT', toolbar: true});
    expect(await filter().locator('option').evaluateAll(options => options.map(o => [o.value, o.textContent])))
      .toEqual([['all', 'All states'], ['draft', 'Draft'], ['validated', 'Validated'], ['deployed', 'Deployed'], ['archived', 'Archived']]);
    await expect(filter()).toHaveValue('all');
    await stateRows('all');
  });
  await page.screenshot({path: `${out}/all-states.png`, fullPage: true});
  await filter().selectOption('draft');
  await check('draft_only_and_chips', () => stateRows('draft'));
  await page.screenshot({path: `${out}/draft-only.png`, fullPage: true});
  await filter().selectOption('all');
  await check('all_restores', () => stateRows('all'));
  await check('other_states', async () => {
    for (const state of ['validated', 'deployed', 'archived']) {
      await filter().selectOption(state);
      await stateRows(state);
    }
    await expect(id('library-search-empty')).toBeVisible();
  });
  await filter().selectOption('all');
  await id('library-search').fill('valid');
  await stateRows('validated');
  await filter().selectOption('draft');
  await check('state_then_search_empty', async () => {
    await expect(rows()).toHaveCount(0);
    await expect(id('library-search-empty')).toBeVisible();
    await count(0);
    await expect(filter()).toHaveValue('draft');
  });
  await page.screenshot({path: `${out}/combined-empty.png`, fullPage: true});
  await id('library-search').focus();
  await page.keyboard.press('Escape');
  await check('escape_search_keeps_state', async () => {
    await expect(id('library-search')).toHaveValue('');
    await expect(filter()).toHaveValue('draft');
    await stateRows('draft');
  });
  await id('library-search').fill('no-match-local-fixture');
  await id('library-search-clear').click();
  await check('clear_search_keeps_state', async () => {
    await expect(filter()).toHaveValue('draft');
    await stateRows('draft');
  });
  await check('keyboard_native_select', async () => {
    await id('library-search').focus();
    await page.keyboard.press('Tab');
    await expect(filter()).toBeFocused();
    await page.keyboard.press('Space');
    await page.keyboard.press('Escape');
    await expect(filter()).toHaveValue('draft');
    await page.keyboard.press('Enter');
    await page.keyboard.press('Escape');
    await page.keyboard.press('Home');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Tab');
    await expect(filter()).toHaveValue('validated');
    await stateRows('validated');
  });
  await check('mobile_control', async () => {
    await page.setViewportSize({width: 390, height: 844});
    await filter().scrollIntoViewIfNeeded();
    const box = await filter().boundingBox();
    expect(box.height).toBeGreaterThanOrEqual(44);
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(390);
    await filter().selectOption('draft');
    await stateRows('draft');
  });
  await page.screenshot({path: `${out}/mobile-draft.png`, fullPage: true});
  // Remove the real session cookie: the actual server must deny the next list.
  const cookies = await context.cookies();
  await context.clearCookies();
  try {
    await id('library-toggle').click();
    const denied = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/strategies/drafts');
    await id('library-toggle').click();
    await check('real_list_error_hides_filter', async () => {
      expect((await denied).status()).toBe(403);
      await expect(id('library-error')).toContainText('library list failed: 403');
      await expect(id('library-error')).toHaveAttribute('role', 'alert');
      await expect(filter()).toHaveCount(0);
      await expect(id('library-search')).toHaveCount(0);
      await expect(rows()).toHaveCount(0);
    });
    await page.screenshot({path: `${out}/real-session-error.png`, fullPage: true});
  } finally {
    await context.addCookies(cookies);
  }
  await id('library-toggle').click();
  await id('library-toggle').click();
  await check('session_recovery', async () => {
    await expect(filter()).toHaveValue('all');
    await stateRows('all');
    await expect(id('library-error')).toHaveCount(0);
  });
  await check('read_only_csrf_requests', async () => {
    const reads = requests.filter(r => r.path.startsWith('/api/v1/strategies/drafts'));
    expect(reads.length).toBeGreaterThanOrEqual(3);
    expect(reads.every(r => r.method === 'GET' && r.csrf)).toBe(true);
    expect(requests.filter(r => r.method !== 'GET' && r.path !== '/api/v1/session/bootstrap')).toHaveLength(0);
  });
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
  fs.writeFileSync(`${out}/browser.json`, JSON.stringify({assertions, requests, responses, errors, version}, null, 2));
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


def seed(home: Path, env: dict[str, str]) -> list[dict]:
    prior = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(env)
        paths.ensure_layout()
        service = StrategyDraftService(home)
        for strategy in ("alpha", "beta"):
            pack = {
                "schema_version": 1, "id": f"local-test-filter-{strategy}",
                "version": "1.0.0", "author": "local workstation",
                "label": f"LOCAL TEST ONLY {strategy} draft", "timeframe": "1h",
                "indicators": {"ma": {"fn": "sma", "src": "close", "len": 20}},
                "entry": ["close", ">", "ma"], "exit": ["close", "<", "ma"],
                "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
                "markets": [{"venue": "kraken", "pair": "XXBTZUSD"}],
            }
            draft = service.create(pack)["revision_id"]
            validated = service.edit(draft, {**pack, "label": f"LOCAL TEST ONLY {strategy} validated"})["revision_id"]
            assert service.validate(validated)["state"] == "validated"
            deployed = service.edit(validated, {**pack, "label": f"LOCAL TEST ONLY {strategy} deployed"})["revision_id"]
            assert service.validate(deployed)["state"] == "validated"
            # State-only local fixture; no paper/live arm command is executed.
            service.mark_deployed(deployed)
        assert not config.load_config(home).armed
        return service.list_owned_summaries()
    finally:
        os.environ.clear()
        os.environ.update(prior)


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
        # Only this exclusively owned process group can contain probe descendants.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="library-state-filter-w2-"))
    out.mkdir(parents=True, exist_ok=True)
    summary = {"qualified": False, "required_assertions": dict.fromkeys(REQUIRED, False),
               "commands": [], "output_dir": str(out), "platform": platform.platform(),
               "invocation": [sys.executable, *sys.argv],
               "mechanism": "Real loopback backend and Chromium; real session/CSRF; no response interception",
               "fixtures": "Six LOCAL TEST ONLY revisions, two strategies; deployed is state-only, not armed"}

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
        with tempfile.TemporaryDirectory(prefix="krellbot-library-filter-home-") as temp:
            home = Path(temp)
            env = clean_env(home)
            assert run(["git", "rev-parse", "HEAD"], ROOT, env, "source-sha.log", 10) == 0
            summary["source_sha"] = (out / "source-sha.log").read_text().strip()
            assert run(["git", "status", "--porcelain"], ROOT, env, "source-status.log", 10) == 0
            summary["source_status"] = (out / "source-status.log").read_text()
            source = ["frontend/src/features/strategies/SavedStrategyLibrary.tsx",
                      "frontend/src/features/strategies/SavedStrategyLibrary.stateFilter.test.tsx",
                      "scripts/verify_library_state_filter.py"]
            summary["source_hashes"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source}
            fixtures = seed(home, env)
            (out / "fixtures.json").write_text(json.dumps(fixtures, indent=2) + "\n")
            before = snapshot(home)
            build = run(["npm", "run", "build"], FRONTEND, env, "build.log", 120)
            if build != 0 and "EACCES" in (out / "build.log").read_text():
                build = run(["npm", "run", "build", "--", "--configLoader", "runner"],
                            FRONTEND, env, "build-runner.log", 120)
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
                    env["LIBRARY_VERIFY_CONFIG"] = json.dumps({
                        "url": url, "out": str(out), "fixtures": fixtures,
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
                    summary["required_assertions"]["live_off_unarmed"] = env["KRELLBOT_ENABLE_LIVE"] == "0" and not config.load_config(home).armed
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
