#!/usr/bin/env python3
"""Qualify the Editor raw-JSON invalid ARIA journey on the real backend + Chromium.

Run: uv run --frozen python scripts/verify_editor_json_invalid.py

A keyboard-only / screen-reader user opens Strategies -> Editor, types
malformed bytes into the Raw JSON textarea (data-testid surface
"kbot-strategy-editor-json") and clicks Import. The textarea itself must then
carry aria-invalid="true" with aria-describedby resolving to the existing
inline role=alert error paragraph (data-testid "editor-import-error") that
names the actual cause ("Invalid JSON"). Typing/pasting a valid minimal pack
afterwards must clear aria-invalid and remove the aria-describedby wiring,
and the Import/Save flow must keep working unchanged. Every response comes
from the real loopback backend through the real session/bootstrap/CSRF flow:
no page.route/route.fulfill and no mocked production client. Live execution
stays disabled; every probe has a deadline with cleanup in finally.
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

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
REQUIRED = [
    "bootstrap_session_csrf",
    "fresh_home_clean_textarea",
    "keyboard_typing_malformed_bytes",
    "invalid_marks_textarea",
    "invalid_error_names_cause",
    "describedby_resolves_to_alert_error",
    "error_alert_role_kept",
    "valid_edit_clears_invalid",
    "valid_edit_removes_describedby",
    "valid_edit_removes_error_node",
    "valid_import_stays_clean",
    "save_flow_unchanged",
    "existing_testids_present",
    "loopback_only",
    "no_browser_errors",
    "storage_before_unchanged",
    "live_off_unarmed",
]

# Clearly-labelled LOCAL TEST ONLY fixture: a complete, non-runnable draft
# pack with no exchange credentials, no orders and no fabricated performance.
VALID_MINIMAL_PACK = {
    "schema_version": 1,
    "id": "local-test-json-invalid",
    "version": "1.0.0",
    "label": "LOCAL TEST ONLY valid minimal pack",
    "author": "local workstation",
    "timeframe": "1h",
    "indicators": {"ma": {"fn": "sma", "src": "close", "len": 20}},
    "entry": ["close", ">", "ma"],
    "exit": ["close", "<", "ma"],
    "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
    "markets": [{"venue": "kraken", "pair": "XXBTZUSD"}],
}
MALFORMED_BYTES = '{"label": "broken", '

BROWSER = r'''
import { createRequire } from 'node:module';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const { chromium, expect } = require('@playwright/test');
const {url, out, malformed, validBytes} = JSON.parse(process.env.EDITOR_VERIFY_CONFIG);
const results = {}, requests = [], errors = [];
let browser, page, version;
const id = name => page.getByTestId(name);
const textarea = () => page.locator('#kbot-strategy-editor-json');
const errorNode = () => id('editor-import-error');
async function check(name, action) { await action(); results[name] = true; }
async function ariaState() {
  return textarea().evaluate(el => ({
    invalid: el.getAttribute('aria-invalid'),
    describedBy: el.getAttribute('aria-describedby'),
  }));
}
async function openTechnical() {
  const details = id('editor-technical-section');
  // The open attribute serializes to "" (falsy); the DOM property is the truth.
  if (!(await details.evaluate(el => el.open))) await details.locator('summary').click();
  await expect.poll(() => details.evaluate(el => el.open)).toBe(true);
}
try {
  browser = await chromium.launch({headless: true, timeout: 20000,
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {})});
  version = browser.version();
  const context = await browser.newContext({viewport: {width: 1280, height: 900}});
  await context.tracing.start({screenshots: true, snapshots: true, sources: false});
  page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.setDefaultNavigationTimeout(15000);
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => requests.push({path: new URL(request.url()).pathname,
    origin: new URL(request.url()).origin, method: request.method(),
    csrf: Boolean(request.headers()['x-krellbot-csrf'])}));
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('bootstrap_session_csrf', async () => {
    const response = await bootstrap;
    expect(response.status()).toBe(200);
    expect((await response.json()).csrf_token.length).toBeGreaterThan(0);
    expect((await context.cookies()).some(c => c.name === 'krellbot_session' && c.httpOnly)).toBe(true);
    await expect(id('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
  });
  await page.getByRole('navigation', {name: 'Workstation navigation'})
    .getByRole('button', {name: 'Strategies', exact: true}).click();
  await id('library-toggle').click();
  await expect(id('library-empty')).toBeVisible();

  await openTechnical();
  await check('fresh_home_clean_textarea', async () => {
    await expect(textarea()).toHaveValue('');
    const aria = await ariaState();
    expect(aria.invalid).toBeNull();
    expect(aria.describedBy).toBeNull();
    await expect(errorNode()).toHaveCount(0);
  });

  // Keyboard-only typing of the malformed bytes into the real textarea.
  await textarea().click();
  await page.keyboard.type(malformed);
  await check('keyboard_typing_malformed_bytes', async () => {
    await expect(textarea()).toHaveValue(malformed);
    await expect(textarea()).toBeFocused();
  });
  await page.getByRole('button', {name: 'Import', exact: true}).click();
  await check('invalid_marks_textarea', async () => {
    await expect(textarea()).toHaveAttribute('aria-invalid', 'true');
    await expect(textarea()).toHaveAttribute('aria-describedby', 'editor-import-error');
  });
  await check('invalid_error_names_cause', async () => {
    await expect(errorNode()).toBeVisible();
    await expect(errorNode()).toHaveText(/invalid json/i);
  });
  await check('error_alert_role_kept', async () => {
    await expect(errorNode()).toHaveAttribute('role', 'alert');
  });
  await check('describedby_resolves_to_alert_error', async () => {
    const link = await page.evaluate(() => {
      const field = document.getElementById('kbot-strategy-editor-json');
      const target = document.getElementById('editor-import-error');
      const ref = field ? field.getAttribute('aria-describedby') : null;
      return {fieldPresent: Boolean(field), targetPresent: Boolean(target),
              ref, resolves: Boolean(field && target && ref === 'editor-import-error'
                && document.getElementById(ref || '') === target),
              targetRole: target ? target.getAttribute('role') : null};
    });
    expect(link.fieldPresent).toBe(true);
    expect(link.targetPresent).toBe(true);
    expect(link.ref).toBe('editor-import-error');
    expect(link.resolves).toBe(true);
    expect(link.targetRole).toBe('alert');
  });
  await page.screenshot({path: `${out}/invalid-json.png`, fullPage: true});

  // Paste a valid minimal pack (keyboard select-all + delete, then insert).
  await textarea().click();
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Delete');
  await page.keyboard.insertText(validBytes);
  await check('valid_edit_clears_invalid', async () => {
    await expect(textarea()).toHaveValue(validBytes);
    await expect(textarea()).not.toHaveAttribute('aria-invalid');
    const aria = await ariaState();
    expect(aria.invalid).toBeNull();
  });
  await check('valid_edit_removes_describedby', async () => {
    const aria = await ariaState();
    expect(aria.describedBy).toBeNull();
    await expect(textarea()).not.toHaveAttribute('aria-describedby');
  });
  await check('valid_edit_removes_error_node', async () => {
    await expect(errorNode()).toHaveCount(0);
  });
  await page.screenshot({path: `${out}/valid-edit-clean.png`, fullPage: true});

  await page.getByRole('button', {name: 'Import', exact: true}).click();
  await check('valid_import_stays_clean', async () => {
    await expect(textarea()).not.toHaveAttribute('aria-invalid');
    await expect(textarea()).not.toHaveAttribute('aria-describedby');
    await expect(errorNode()).toHaveCount(0);
  });
  await page.getByRole('button', {name: 'Save', exact: true}).click();
  await check('save_flow_unchanged', async () => {
    await expect(id('editor-save-outcome')).toContainText(/saved new revision \S+/);
    const creates = requests.filter(r => r.method === 'POST'
      && r.path === '/api/v1/strategies/drafts');
    expect(creates).toHaveLength(1);
    expect(creates[0].csrf).toBe(true);
  });
  await page.screenshot({path: `${out}/saved.png`, fullPage: true});
  await check('existing_testids_present', async () => {
    await expect(id('editor-technical-section')).toBeVisible();
    await expect(id('editor-revision-id')).toBeVisible();
    await expect(id('editor-save-outcome')).toBeVisible();
    await expect(textarea()).toHaveId('kbot-strategy-editor-json');
  });
  await context.tracing.stop({path: `${out}/trace.zip`});
} catch (error) {
  results.error = String(error.stack || error);
  if (page) await page.screenshot({path: `${out}/failure.png`, fullPage: true}).catch(() => {});
  process.exitCode = 1;
} finally {
  results.loopback_only = requests.length > 0 &&
    requests.every(r => r.origin === new URL(url).origin);
  results.no_browser_errors = errors.length === 0;
  if (errors.length) results.page_errors = errors;
  const fs = await import('node:fs');
  fs.writeFileSync(`${out}/browser.json`, JSON.stringify({results, requests, browserVersion: version}, null, 2));
  if (browser) await browser.close();
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


def snapshot_drafts(home: Path) -> dict[str, str]:
    return {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((home / "drafts").rglob("*")) if p.is_file()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="editor-json-invalid-"))
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                               text=True, timeout=10).strip(),
        "source_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT,
                                                  text=True, timeout=10),
        "platform": platform.platform(),
        "qualified": False,
        "required_assertions": dict.fromkeys(REQUIRED, False),
        "commands": [],
        "fixtures": ("Clearly-labelled LOCAL TEST ONLY non-runnable draft pack; "
                     "no exchange credentials, orders or fabricated performance"),
        "mechanism": "Real loopback backend + real headless Chromium; keyboard typing and "
                     "paste into the real textarea; real session/bootstrap/CSRF; "
                     "no page.route/route.fulfill and no mocked production client",
        "output_dir": str(out),
    }

    def run(argv: list[str], cwd: Path, env: dict[str, str], log: Path, timeout: int) -> int:
        record = {"argv": argv, "cwd": str(cwd), "log": str(log), "timeout_seconds": timeout}
        summary["commands"].append(record)
        with subprocess.Popen(argv, cwd=cwd, env=env, stdout=log.open("w"),
                              stderr=subprocess.STDOUT) as proc:
            record["pid"] = proc.pid
            record["exit"] = proc.wait(timeout=timeout)
        return record["exit"]

    def launch_backend(home: Path, env: dict[str, str], log: Path) -> tuple[subprocess.Popen, dict]:
        argv = [sys.executable, "-m", "krellbot.cli", "workstation", "--dist", str(FRONTEND / "dist")]
        record = {"argv": argv, "cwd": str(ROOT), "log": str(log), "timeout_seconds": 20,
                  "cleanup": "terminate owned PID in finally, wait 10s, kill then wait 5s"}
        summary["commands"].append(record)
        proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=log.open("w"),
                                stderr=subprocess.STDOUT)
        record["pid"] = proc.pid
        return proc, record

    def wait_for_url(log: Path, proc: subprocess.Popen) -> str:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            match = re.search(r"Workstation running at (http://127\.0\.0\.1:\d+/)", log.read_text())
            if match:
                return match[1]
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        raise AssertionError(f"Backend startup deadline failed; see {log}")

    scenario_results: dict[str, dict] = {}
    try:
        source = ["frontend/src/features/strategies/Editor.tsx",
                  "frontend/src/features/strategies/Editor.jsonInvalid.test.tsx",
                  "scripts/verify_editor_json_invalid.py"]
        summary["source_hashes"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source}

        valid_bytes = json.dumps(VALID_MINIMAL_PACK, indent=2) + "\n"
        browser_file = out / "journey.mjs"
        browser_file.write_text(BROWSER)

        with tempfile.TemporaryDirectory(prefix="krellbot-editor-build-") as build_home:
            assert run(["npm", "run", "build"], FRONTEND, clean_env(Path(build_home)),
                       out / "build.log", 240) == 0, "frontend build failed"

        evidence = out / "fresh"
        evidence.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="krellbot-editor-json-invalid-") as temp:
            home = Path(temp)
            env = clean_env(home)
            prior = dict(os.environ)
            try:
                os.environ.clear()
                os.environ.update(env)
                paths.ensure_layout()
                assert not config.load_config(home).armed
                assert os.environ["KRELLBOT_ENABLE_LIVE"] == "0"
            finally:
                os.environ.clear()
                os.environ.update(prior)
            before = snapshot_drafts(home)

            proc, record = launch_backend(home, env, evidence / "backend.log")
            try:
                url = wait_for_url(evidence / "backend.log", proc)
                env["EDITOR_VERIFY_CONFIG"] = json.dumps({
                    "url": url, "out": str(evidence),
                    "malformed": MALFORMED_BYTES, "validBytes": valid_bytes,
                })
                code = run(["node", str(browser_file)], ROOT, env,
                           evidence / "browser.log", 240)
                browser = json.loads((evidence / "browser.json").read_text())
                scenario_results["fresh"] = browser["results"]
                summary["browser_versions"] = [browser["browserVersion"]]
                assert code == 0, browser["results"].get("error", "Browser failed")
            finally:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    record["exit"] = proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    record["exit"] = proc.wait(timeout=5)
                record["reaped"] = proc.poll() is not None

            after = snapshot_drafts(home)
            (evidence / "storage-hashes.json").write_text(
                json.dumps({"before": before, "after": after}, indent=2))
            # Nothing that existed before the journey may change: the fresh
            # home is empty, so any pre-existing file staying byte-identical
            # is the integrity bar for this journey.
            scenario_results["fresh"]["storage_before_unchanged"] = all(
                after.get(name) == digest for name, digest in before.items())
            scenario_results["fresh"]["live_off_unarmed"] = not config.load_config(home).armed

        for name in REQUIRED:
            applicable = [result[name] for result in scenario_results.values() if name in result]
            summary["required_assertions"][name] = bool(applicable) and all(v is True for v in applicable)
        summary["scenarios"] = scenario_results
        summary["qualified"] = all(summary["required_assertions"].values()) and all(
            command.get("exit") == 0 and command.get("reaped", True) is True
            for command in summary["commands"])
    except Exception:
        summary["scenarios"] = scenario_results
        summary["failure"] = traceback.format_exc()
    finally:
        summary["exit_code"] = 0 if summary["qualified"] else 1
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
