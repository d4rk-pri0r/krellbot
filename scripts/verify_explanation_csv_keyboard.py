#!/usr/bin/env python3
"""Real backend/Chromium qualification; no interception or substitute client.

Run: uv run --frozen python scripts/verify_explanation_csv_keyboard.py
DOM/AX evidence is not audible screen-reader or Windows qualification.
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
import threading
import time
import traceback
from pathlib import Path

from krellbot import config
from krellbot.api.serve import WorkstationServer

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
REQUIRED = [
    "session_bootstrap_csrf", "fresh_disabled_cause", "disabled_enter_space_noop",
    "saved_revision_reopened", "availability_flip", "accessible_artifact_description",
    "synthetic_enter_once", "trusted_enter_once", "space_once", "held_keys_once",
    "focus_retained", "click_equal_bytes_mime_filename", "download_announcement",
    "static_rerender_silent", "disabled_flip_cause", "repeat_export_after_edit",
    "loopback_only", "no_browser_or_api_errors", "live_disabled_unarmed",
]
PACK = {
    "schema_version": 1, "id": "local-test-explanation-keyboard", "version": "1.0.0",
    "label": "LOCAL TEST ONLY explanation keyboard", "author": "local workstation",
    "timeframe": "1h", "indicators": {"ma": {"fn": "sma", "src": "close", "len": 20}},
    "entry": ["close", ">", "ma"], "exit": ["close", "<", "ma"],
    "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
    "markets": [{"venue": "kraken", "pair": "XXBTZUSD"}],
}
BROWSER = r'''
import {createRequire} from 'node:module';
import fs from 'node:fs';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const {chromium, expect} = require('@playwright/test');
const {url, out, pack, required} = JSON.parse(process.env.EXPLANATION_VERIFY_CONFIG);
const assertions = Object.fromEntries(required.map(n => [n, false]));
const requests = [], apiErrors = [], errors = [], observations = {}, downloads = [];
let browser, context, page;
const id = name => page.getByTestId(name);
const button = () => id('strategies-explanation-csv-export');
const status = () => id('strategies-explanation-csv-status');
const raw = () => page.locator('#kbot-strategy-editor-json');
async function check(name, action) { await action(); assertions[name] = true; }
async function settle() {
  await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
}
async function tabTo(target) {
  for (let i = 0; i < 180; i++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Keyboard target unreachable');
}
async function activate(target) { await tabTo(target); await page.keyboard.press('Enter'); }
async function technical() {
  const details = id('editor-technical-section');
  if (!(await details.evaluate(el => el.open))) await activate(details.locator('summary'));
}
async function evidence(name) {
  await page.screenshot({path: `${out}/${name}.png`, fullPage: true});
  fs.writeFileSync(`${out}/${name}.aria.txt`, await id('strategy-explanation').ariaSnapshot());
}
async function oneDownload(name, action) {
  await tabTo(button());
  const before = downloads.length;
  const count = await page.evaluate(() => window.csvProbe.blobs.length);
  const pending = page.waitForEvent('download');
  await action();
  const download = await pending;
  await download.saveAs(`${out}/${name}.csv`);
  expect(await download.failure()).toBeNull();
  await settle();
  await page.waitForTimeout(200);
  expect(downloads.length).toBe(before + 1);
  expect(await page.evaluate(() => window.csvProbe.blobs.length)).toBe(count + 1);
  await expect(button()).toBeFocused();
  await expect(status()).toHaveText('Strategy explanation CSV download started');
  expect(download.suggestedFilename()).toMatch(/^strategy-explanation-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.csv$/);
  return fs.readFileSync(`${out}/${name}.csv`);
}
try {
  browser = await chromium.launch({headless: true, timeout: 20000,
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {})});
  observations.browser_version = browser.version();
  context = await browser.newContext({viewport: {width: 1280, height: 900}, acceptDownloads: true});
  await context.tracing.start({screenshots: true, snapshots: true, sources: false});
  await context.addInitScript(() => {
    window.csvProbe = {blobs: [], revoked: [], announcements: []};
    const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = blob => {
      const url = create(blob);
      window.csvProbe.blobs.push({type: blob.type, size: blob.size, url});
      return url;
    };
    URL.revokeObjectURL = url => { window.csvProbe.revoked.push(url); return revoke(url); };
    new MutationObserver(records => {
      const region = document.querySelector('[data-testid="strategies-explanation-csv-status"]');
      if (region && records.some(r => r.target === region || region.contains(r.target))) {
        window.csvProbe.announcements.push(region.textContent);
      }
    }).observe(document, {subtree: true, childList: true, characterData: true});
  });
  page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.setDefaultNavigationTimeout(15000);
  page.on('pageerror', e => errors.push(String(e)));
  page.on('download', d => downloads.push(d.suggestedFilename()));
  page.on('request', r => requests.push({origin: new URL(r.url()).origin,
    path: new URL(r.url()).pathname, method: r.method(), csrf: Boolean(r.headers()['x-krellbot-csrf'])}));
  page.on('response', r => {
    if (new URL(r.url()).pathname.startsWith('/api/') && r.status() >= 400)
      apiErrors.push({path: new URL(r.url()).pathname, status: r.status()});
  });
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('session_bootstrap_csrf', async () => {
    const response = await bootstrap;
    expect(response.status()).toBe(200);
    expect((await response.json()).csrf_token.length).toBeGreaterThan(0);
    expect((await context.cookies()).some(c => c.name === 'krellbot_session' && c.httpOnly)).toBe(true);
    await expect(id('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
  });
  const navigation = page.getByRole('navigation', {name: 'Workstation navigation'});
  await tabTo(navigation.locator('button[tabindex="0"]'));
  await page.keyboard.press('Home');
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await expect(navigation.getByRole('button', {name: 'Strategies', exact: true})).toBeFocused();
  await check('fresh_disabled_cause', async () => {
    await expect(button()).toBeDisabled();
    await expect(button()).toHaveAttribute('aria-disabled', 'true');
    await expect(status()).toHaveAttribute('aria-live', 'polite');
    await expect(status()).toHaveText('Export unavailable: no exportable rows in this explanation');
  });
  await check('disabled_enter_space_noop', async () => {
    for (const key of ['Enter', ' '])
      await button().dispatchEvent('keydown', {key, bubbles: true, cancelable: true});
    await settle();
    expect(downloads).toHaveLength(0);
    expect(await page.evaluate(() => window.csvProbe.blobs)).toHaveLength(0);
  });
  await evidence('disabled');
  await technical();
  await tabTo(raw());
  await page.keyboard.insertText(JSON.stringify(pack, null, 2));
  await activate(page.getByRole('button', {name: 'Import', exact: true}));
  await activate(page.getByRole('button', {name: 'Save', exact: true}));
  await expect(id('editor-save-outcome')).toContainText(/saved new revision \S+/);
  const revisionText = await id('editor-revision-id').textContent();
  const revision = revisionText.match(/revision: (\S+)/)[1];
  await activate(id('library-toggle'));
  await expect(id('library-row')).toHaveCount(1);
  await activate(id('library-new-owned-strategy'));
  await expect(button()).toBeDisabled();
  await check('saved_revision_reopened', async () => {
    await activate(id('library-row').getByRole('button', {name: 'Reopen', exact: true}));
    await expect(id('editor-revision-id')).toHaveText(revisionText);
    await expect(id('strategy-explanation-revision')).toContainText(revision.trim());
    expect(requests.some(r => r.method === 'POST' && r.path === '/api/v1/strategies/drafts' && r.csrf)).toBe(true);
    expect(requests.some(r => r.method === 'GET' && r.path.includes('/strategies/drafts/') && r.csrf)).toBe(true);
  });
  await check('availability_flip', async () => {
    await expect(button()).toBeEnabled();
    await expect(status()).toHaveText('Export now available');
    expect(await page.evaluate(() => window.csvProbe.announcements)).toContain('Export now available');
  });
  await check('accessible_artifact_description', async () => {
    await expect(button()).toHaveAccessibleName('Export explanation: strategy explanation CSV');
    await expect(button()).toHaveAccessibleDescription(/strategy-explanation-YYYY-MM-DDTHH-MM-SS\.csv.*same CSV bytes as clicking/);
    await expect(button()).toHaveAttribute('aria-disabled', 'false');
    const cdp = await context.newCDPSession(page);
    try {
      const tree = await cdp.send('Accessibility.getFullAXTree');
      fs.writeFileSync(`${out}/enabled-ax.json`, JSON.stringify(tree, null, 2));
      const node = tree.nodes.find(n => n.role?.value === 'button' && n.name?.value === 'Export explanation: strategy explanation CSV');
      expect(node?.ignored).toBe(false);
      expect(node.description.value).toContain('strategy-explanation-YYYY-MM-DDTHH-MM-SS.csv');
      expect(tree.nodes.some(n => n.role?.value === 'status' && n.properties?.some(p => p.name === 'live' && p.value.value === 'polite'))).toBe(true);
    } finally { await cdp.detach(); }
  });
  await evidence('enabled');
  let keyboardBytes;
  await check('synthetic_enter_once', async () => {
    keyboardBytes = await oneDownload('synthetic-enter', () => button().dispatchEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true}));
  });
  await check('trusted_enter_once', async () => {
    await oneDownload('trusted-enter', () => page.keyboard.press('Enter'));
  });
  await check('space_once', async () => {
    await oneDownload('space', () => page.keyboard.press('Space'));
  });
  await check('held_keys_once', async () => {
    for (const key of ['Enter', 'Space']) {
      await oneDownload(`held-${key}`, async () => {
        await page.keyboard.down(key);
        await page.keyboard.down(key);
        await page.keyboard.down(key);
        await button().dispatchEvent('keydown', {key: key === 'Space' ? ' ' : key, repeat: true, bubbles: true, cancelable: true});
        await page.keyboard.up(key);
      });
    }
  });
  await check('focus_retained', async () => { await expect(button()).toBeFocused(); });
  await check('click_equal_bytes_mime_filename', async () => {
    const clickBytes = await oneDownload('click', () => button().click());
    expect(clickBytes.equals(keyboardBytes)).toBe(true);
    expect(clickBytes.toString()).toContain('metadata,label,LOCAL TEST ONLY explanation keyboard');
    const probe = await page.evaluate(() => window.csvProbe);
    expect(probe.blobs.every(b => b.type === 'text/csv;charset=utf-8')).toBe(true);
    expect(probe.revoked).toEqual(probe.blobs.map(b => b.url));
  });
  await check('download_announcement', async () => {
    await expect(status()).toHaveText('Strategy explanation CSV download started');
    const messages = await page.evaluate(() => window.csvProbe.announcements);
    expect(messages.filter(m => m === 'Strategy explanation CSV download started')).toHaveLength(downloads.length);
  });
  await technical();
  await check('static_rerender_silent', async () => {
    await page.evaluate(() => { window.beforeAnnouncements = window.csvProbe.announcements.length; });
    await tabTo(raw());
    await page.keyboard.press('End');
    await page.keyboard.insertText(' ');
    await settle();
    expect(await page.evaluate(() => window.csvProbe.announcements.length === window.beforeAnnouncements)).toBe(true);
  });
  await check('repeat_export_after_edit', async () => {
    const edited = {...pack, label: 'LOCAL TEST ONLY edited explanation'};
    await tabTo(raw());
    await page.keyboard.press('ControlOrMeta+A');
    await page.keyboard.insertText(JSON.stringify(edited, null, 2));
    await activate(page.getByRole('button', {name: 'Save', exact: true}));
    await expect(id('strategy-explanation-metadata')).toContainText(edited.label);
    const bytes = await oneDownload('edited-enter', () => page.keyboard.press('Enter'));
    expect(bytes.toString()).toContain(edited.label);
  });
  await check('disabled_flip_cause', async () => {
    await activate(id('library-new-owned-strategy'));
    await expect(button()).toBeDisabled();
    await expect(status()).toHaveText('Export unavailable: no exportable rows in this explanation');
    const before = downloads.length;
    await button().dispatchEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true});
    await settle();
    expect(downloads.length).toBe(before);
    await expect(button()).toHaveAccessibleDescription(/Export unavailable: no exportable rows/);
  });
  await evidence('disabled-again');
  await check('loopback_only', async () => {
    expect(requests.length).toBeGreaterThan(0);
    expect(requests.every(r => r.origin === new URL(url).origin)).toBe(true);
  });
  await check('no_browser_or_api_errors', async () => {
    expect(errors).toEqual([]);
    expect(apiErrors).toEqual([]);
    await expect(page.getByRole('alert')).toHaveCount(0);
  });
} catch (error) {
  observations.failure = String(error.stack || error);
  if (page) await evidence('failure').catch(() => {});
} finally {
  if (page) observations.probe = await page.evaluate(() => window.csvProbe).catch(() => null);
  if (context) await context.tracing.stop({path: `${out}/trace.zip`}).catch(() => {});
  if (browser) await browser.close();
  const qualified = required.filter(n => n !== 'live_disabled_unarmed').every(n => assertions[n]);
  fs.writeFileSync(`${out}/browser.json`, JSON.stringify({qualified, required_assertions: assertions,
    observations, requests, apiErrors, errors, downloads}, null, 2));
  process.exitCode = qualified ? 0 : 1;
}
'''


def clean_env(home: Path) -> dict[str, str]:
    names = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "USERPROFILE",
             "LOCALAPPDATA", "PLAYWRIGHT_BROWSERS_PATH")
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update(KRELLBOT_HOME=str(home), KRELLBOT_ENABLE_LIVE="0", PYTHONUNBUFFERED="1",
               PYTHONPATH=str(ROOT / "src"), FRONTEND_PACKAGE=str(FRONTEND / "package.json"))
    executable = shutil.which("chromium") or shutil.which("chromium-browser")
    if executable:
        env["CHROMIUM_EXECUTABLE"] = executable
    return env


def serve() -> int:
    home = Path(os.environ["KRELLBOT_HOME"])
    assert os.environ["KRELLBOT_ENABLE_LIVE"] == "0"
    assert not config.load_config(home).armed
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    server = WorkstationServer(home, dist_dir=FRONTEND / "dist")
    try:
        server.start()
        print(f"RUNTIME_URL={server.url}", flush=True)
        stopped.wait(timeout=240)
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
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    out = (args.output_dir or ROOT / "tests_tmp" / "explanation-csv-keyboard" / f"{sha[:12]}-{time.time_ns()}").resolve()
    out.mkdir(parents=True, mode=0o700, exist_ok=True)
    summary = {
        "source_sha": sha, "source_status": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True),
        "platform": platform.platform(), "qualified": False, "commands": [],
        "invocation": ["uv", "run", "--frozen", "python", "scripts/verify_explanation_csv_keyboard.py"],
        "required_assertions": dict.fromkeys(REQUIRED, False), "output_dir": str(out),
        "limits": "Linux Chromium DOM/AX and actual downloads; no audible AT or Windows qualification",
        "fixture": "LOCAL TEST ONLY saved draft; no performance, credentials or orders",
    }
    sources = ["frontend/src/features/strategies/StrategyExplanationCsvExport.tsx",
               "frontend/src/features/strategies/StrategyExplanationCsvExport.keyboard.test.tsx",
               "scripts/verify_explanation_csv_keyboard.py"]
    summary["source_hashes"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources}

    def launch(argv: list[str], cwd: Path, env: dict[str, str], log: Path):
        record = {"argv": argv, "cwd": str(cwd), "log": str(log)}
        summary["commands"].append(record)
        with log.open("w") as stream:
            child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream,
                                     stderr=subprocess.STDOUT, start_new_session=os.name == "posix")
        record["pid"] = child.pid
        return child, record

    def run(argv: list[str], cwd: Path, env: dict[str, str], log: Path, timeout: int):
        child, record = launch(argv, cwd, env, log)
        try:
            return child.wait(timeout=timeout)
        finally:
            stop(child)
            record.update(exit=child.returncode, reaped=child.poll() is not None)

    try:
        journey = out / "journey.mjs"
        journey.write_text(BROWSER)
        with tempfile.TemporaryDirectory(prefix="krellbot-explanation-keyboard-") as temp:
            home = Path(temp)
            env = clean_env(home)
            assert run(["npm", "run", "build"], FRONTEND, env, out / "build.log", 240) == 0, "build failed"
            assert not config.load_config(home).armed
            backend, record = launch([sys.executable, str(Path(__file__).resolve()), "--serve"],
                                     ROOT, env, out / "backend.log")
            try:
                deadline = time.monotonic() + 20
                url = None
                while time.monotonic() < deadline:
                    match = re.search(r"RUNTIME_URL=(http://127\.0\.0\.1:\d+/)", (out / "backend.log").read_text())
                    if match:
                        url = match[1]
                        break
                    if backend.poll() is not None:
                        break
                    time.sleep(0.1)
                assert url, "real backend failed to start; see backend.log"
                env["EXPLANATION_VERIFY_CONFIG"] = json.dumps({"url": url, "out": str(out), "pack": PACK, "required": REQUIRED})
                code = run(["node", str(journey)], ROOT, env, out / "browser.log", 200)
                browser = json.loads((out / "browser.json").read_text())
                summary["required_assertions"].update(browser["required_assertions"])
                summary["browser_evidence"] = str(out / "browser.json")
                assert code == 0, browser["observations"].get("failure", "browser assertions failed")
            finally:
                stop(backend)
                record.update(exit=backend.returncode, reaped=backend.poll() is not None)
            summary["required_assertions"]["live_disabled_unarmed"] = (
                env["KRELLBOT_ENABLE_LIVE"] == "0" and not config.load_config(home).armed)
        summary["qualified"] = all(summary["required_assertions"].values()) and all(
            c["exit"] == 0 and c["reaped"] for c in summary["commands"])
    except Exception:
        summary["failure"] = traceback.format_exc()
    finally:
        summary["exit_code"] = 0 if summary["qualified"] else 1
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
