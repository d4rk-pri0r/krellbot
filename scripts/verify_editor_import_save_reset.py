#!/usr/bin/env python3
"""Qualify the editor import→Save reset journey on the real backend + Chromium.

Run: uv run --frozen python scripts/verify_editor_import_save_reset.py

A previously-saved revision is reopened from the real library, a JSON file is
imported through the real file input, and Save must create a NEW revision
(POST /api/v1/strategies/drafts) instead of silently editing the reopened one.
The no-previous-revision case and the invalid/unsupported import failure
surfaces are exercised too. No page.route/route.fulfill and no mocked client:
every response comes from the real loopback backend. Live execution stays
disabled and every probe has a deadline with cleanup in finally.
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
    "bootstrap_session_csrf",
    "seeded_revision_reopened",
    "import_clears_revision_identity",
    "form_derived_from_import",
    "import_save_creates_new_revision",
    "imported_bytes_saved_verbatim",
    "no_edit_on_loaded_revision",
    "keyboard_repeat_save_new_revision_only",
    "invalid_import_error_surface",
    "invalid_import_keeps_identity",
    "unsupported_import_preserved",
    "unsupported_save_creates",
    "library_empty_fresh",
    "no_previous_revision_create",
    "loopback_only",
    "no_browser_errors",
    "storage_seed_unchanged",
    "live_off_unarmed",
]

# Clearly-labelled LOCAL TEST ONLY fixtures: non-runnable draft packs with no
# exchange credentials, no orders and no fabricated performance data.
SEED_PACK = {
    "schema_version": 1,
    "id": "local-test-seed",
    "version": "1.0.0",
    "label": "LOCAL TEST ONLY seed revision",
    "author": "local workstation",
    "timeframe": "1h",
    "indicators": {"ma": {"fn": "sma", "src": "close", "len": 20}},
    "entry": ["close", ">", "ma"],
    "exit": ["close", "<", "ma"],
    "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
    "markets": [{"venue": "kraken", "pair": "XXBTZUSD"}],
}
IMPORTED_PACK = {
    "schema_version": 1,
    "id": "local-test-import",
    "version": "1.0.0",
    "label": "LOCAL TEST ONLY imported",
    "author": "local workstation",
    "timeframe": "4h",
    "indicators": {"ma": {"fn": "ema", "src": "close", "len": 36}},
    "entry": ["close", "crosses_above", "ma"],
    "exit": ["close", "crosses_below", "ma"],
    "risk": {"max_account_pct": 40, "stop": {"type": "pct", "pct": 6.5}},
    "markets": [{"venue": "kraken", "pair": "XXBTZUSD"}],
}
UNSUPPORTED_PACK = {
    "schema_version": 1,
    "id": "local-test-import-mix",
    "version": "1.2.0",
    "label": "LOCAL TEST ONLY unsupported import",
    "author": "someone else",
    "origin": "Imported from a file. Ownership not verified.",
    "timeframe": "4h",
    "indicators": {
        "fast": {"fn": "ema", "src": "close", "len": 12},
        "slow": {"fn": "sma", "src": "close", "len": 40},
    },
    "entry": {"all": [["close", "crosses_above", "fast"], ["close", ">", "slow"]]},
    "exit": ["close", "<", "slow"],
    "risk": {"max_account_pct": 10, "stop": {"type": "atr", "len": 14, "mult": 2}},
    "markets": [
        {"venue": "kraken", "pair": "XXBTZUSD"},
        {"venue": "coinbase", "pair": "BTC-USD"},
    ],
}

BROWSER = r'''
import { createRequire } from 'node:module';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const { chromium, expect } = require('@playwright/test');
const {url, out, scenario, seedRevision, files} = JSON.parse(process.env.EDITOR_VERIFY_CONFIG);
const results = {}, requests = [], errors = [];
let browser, page, version;
const id = name => page.getByTestId(name);
const drafts = '/api/v1/strategies/drafts';
const creates = () => requests.filter(r => r.method === 'POST' && r.path === drafts);
const edits = () => requests.filter(r => r.method === 'PUT' && r.path.startsWith(drafts + '/'));
const seedEdits = () => edits().filter(r => r.path === `${drafts}/${seedRevision}`);
async function check(name, action) { await action(); results[name] = true; }
async function settle() {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
async function openTechnical() {
  const details = id('editor-technical-section');
  // The open attribute serializes to "" (falsy); the DOM property is the truth.
  if (!(await details.evaluate(el => el.open))) await details.locator('summary').click();
  await expect.poll(() => details.evaluate(el => el.open)).toBe(true);
}
async function importFile(path) {
  await openTechnical();
  await page.locator('#kbot-strategy-editor-file').setInputFiles(path);
}
async function outcomeText() {
  const node = id('editor-save-outcome');
  await expect(node).toBeVisible();
  const text = await node.textContent();
  const match = /revision (\S+)/.exec(text || '');
  if (!match) throw new Error(`no revision id in outcome: ${text}`);
  return {text: (text || '').trim(), revision: match[1]};
}
async function tabTo(target) {
  for (let n = 0; n < 200; n++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Keyboard target not reachable');
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
  if (scenario === 'reopened') {
    const row = id('library-row').filter({hasText: seedRevision});
    await expect(row).toHaveCount(1);
    await row.getByRole('button', {name: 'Reopen'}).click();
    await check('seeded_revision_reopened', async () => {
      await expect(id('editor-revision-id')).toContainText(seedRevision);
    });
    await page.screenshot({path: `${out}/reopened.png`, fullPage: true});
    await importFile(files.supported);
    await check('import_clears_revision_identity', async () => {
      await expect(page.getByLabel(/raw json/i)).toHaveValue(files.supportedText);
      await expect(id('editor-revision-id')).toHaveCount(0);
      await expect(page.getByText(/no saved revision yet/i)).toBeVisible();
      await expect(page.getByRole('button', {name: 'Validate'})).toBeDisabled();
      await expect(page.getByRole('button', {name: 'Arm', exact: true})).toBeDisabled();
    });
    await check('form_derived_from_import', async () => {
      await expect(id('owned-strategy-form')).toBeVisible();
      await expect(page.getByLabel(/strategy name/i)).toHaveValue('LOCAL TEST ONLY imported');
      await expect(page.getByLabel(/average length \(bars\)/i)).toHaveValue('36');
      await expect(id('owned-strategy-form-unsupported')).toHaveCount(0);
    });
    await page.screenshot({path: `${out}/imported.png`, fullPage: true});
    await page.getByRole('button', {name: 'Save', exact: true}).click();
    const saved = await outcomeText();
    results['import_save_outcome'] = saved.text;
    results['import_save_revision'] = saved.revision;
    await check('import_save_creates_new_revision', async () => {
      expect(saved.text).toMatch(/^saved new revision \S+$/);
      expect(saved.revision).not.toBe(seedRevision);
      await expect(id('editor-revision-id')).toContainText(saved.revision);
      expect(creates()).toHaveLength(1);
      expect(creates()[0].csrf).toBe(true);
    });
    await page.screenshot({path: `${out}/saved-new-revision.png`, fullPage: true});
    await importFile(files.invalid);
    await check('invalid_import_error_surface', async () => {
      await expect(id('editor-import-error')).toBeVisible();
      await expect(id('editor-import-error')).toHaveText(/invalid json/i);
      expect(creates()).toHaveLength(1);
      expect(edits()).toHaveLength(0);
    });
    await check('invalid_import_keeps_identity', async () => {
      await expect(id('editor-revision-id')).toContainText(saved.revision);
      await expect(id('editor-save-outcome')).toHaveText(saved.text);
    });
    await page.screenshot({path: `${out}/invalid-import.png`, fullPage: true});
    await importFile(files.unsupported);
    await check('unsupported_import_preserved', async () => {
      await expect(page.getByLabel(/raw json/i)).toHaveValue(files.unsupportedText);
      await expect(id('owned-strategy-form-unsupported')).toBeVisible();
      await expect(id('owned-strategy-form')).toHaveCount(0);
      await expect.poll(() => id('editor-technical-section').evaluate(el => el.open)).toBe(true);
      await expect(id('editor-revision-id')).toHaveCount(0);
    });
    const saveButton = page.getByRole('button', {name: 'Save', exact: true});
    await tabTo(saveButton);
    await page.keyboard.press('Enter');
    const unsupportedSaved = await outcomeText();
    results['unsupported_save_outcome'] = unsupportedSaved.text;
    results['unsupported_save_revision'] = unsupportedSaved.revision;
    await check('unsupported_save_creates', async () => {
      expect(unsupportedSaved.text).toMatch(/^saved new revision \S+$/);
      expect(creates()).toHaveLength(2);
      expect(edits()).toHaveLength(0);
    });
    await check('keyboard_repeat_save_new_revision_only', async () => {
      await tabTo(saveButton);
      await page.keyboard.press('Enter');
      const repeat = await outcomeText();
      results['repeat_save_outcome'] = repeat.text;
      // The imported create set the new revision identity: the repeat Save
      // may edit only THAT revision (unchanged), never the reopened seed.
      expect(repeat.revision).toBe(unsupportedSaved.revision);
      expect(repeat.revision).not.toBe(seedRevision);
      expect(repeat.text).toMatch(/^(no change: revision \S+ kept|saved new revision \S+)$/);
      const putPaths = edits().map(r => r.path.replace(`${drafts}/`, ''));
      expect(putPaths.every(p => p !== seedRevision)).toBe(true);
      expect(creates()).toHaveLength(2);
    });
    await page.setViewportSize({width: 390, height: 844});
    await settle();
    await expect(saveButton).toBeVisible();
    await page.screenshot({path: `${out}/mobile.png`, fullPage: true});
    await page.setViewportSize({width: 1280, height: 900});
  } else {
    await check('library_empty_fresh', async () => {
      await expect(id('library-empty')).toBeVisible();
      await expect(id('editor-revision-id')).toHaveCount(0);
    });
    await importFile(files.supported);
    await expect(page.getByLabel(/raw json/i)).toHaveValue(files.supportedText);
    await expect(id('editor-revision-id')).toHaveCount(0);
    await page.getByRole('button', {name: 'Save', exact: true}).click();
    const saved = await outcomeText();
    results['no_previous_revision_outcome'] = saved.text;
    results['no_previous_revision_id'] = saved.revision;
    await check('no_previous_revision_create', async () => {
      expect(saved.text).toMatch(/^saved new revision \S+$/);
      await expect(id('editor-revision-id')).toContainText(saved.revision);
      expect(creates()).toHaveLength(1);
      expect(creates()[0].csrf).toBe(true);
    });
    await page.screenshot({path: `${out}/fresh-saved.png`, fullPage: true});
  }
  await check('no_edit_on_loaded_revision', async () => {
    // No PUT may ever target the previously-loaded (seeded) revision; edits
    // on revisions the journey itself created are the correct follow-up path.
    expect(seedEdits()).toHaveLength(0);
    const putPaths = edits().map(r => r.path.replace(`${drafts}/`, ''));
    expect(putPaths.every(p => p !== seedRevision)).toBe(true);
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
  results.draft_requests = {creates: creates().length, edits: edits().length,
    edit_paths: edits().map(r => r.path)};
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
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="editor-import-save-reset-"))
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
        "fixtures": ("Clearly-labelled LOCAL TEST ONLY non-runnable draft packs; "
                     "no exchange credentials, orders or fabricated performance"),
        "mechanism": "Real loopback backend + real headless Chromium; file import through the real input; "
                     "no page.route/route.fulfill and no mocked production client",
        "output_dir": str(out),
    }

    def run(argv: list[str], cwd: Path, env: dict[str, str], log: Path, timeout: int) -> int:
        record = {"argv": argv, "cwd": str(cwd), "log": str(log), "timeout_seconds": timeout}
        summary["commands"].append(record)
        with log.open("w") as stream:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            record["pid"] = proc.pid
            try:
                record["exit"] = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record["exit"] = 124
                stream.write("\nFinite command deadline exceeded\n")
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait(timeout=5)
                record["reaped"] = proc.poll() is not None
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
                  "frontend/src/features/strategies/Editor.importSaveReset.test.tsx",
                  "scripts/verify_editor_import_save_reset.py"]
        summary["source_hashes"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source}

        # Clearly-labelled import fixtures on disk for the real file input.
        supported_text = json.dumps(IMPORTED_PACK, indent=2) + "\n"
        unsupported_text = json.dumps(UNSUPPORTED_PACK, indent=2) + "\n"
        files = {
            "supported": str(out / "local-test-import.json"),
            "unsupported": str(out / "local-test-import-unsupported.json"),
            "invalid": str(out / "local-test-import-invalid.json"),
        }
        (out / "local-test-import.json").write_text(supported_text)
        (out / "local-test-import-unsupported.json").write_text(unsupported_text)
        (out / "local-test-import-invalid.json").write_text("{not json\n")

        browser_file = out / "journey.mjs"
        browser_file.write_text(BROWSER)

        with tempfile.TemporaryDirectory(prefix="krellbot-editor-build-") as build_home:
            assert run(["npm", "run", "build"], FRONTEND, clean_env(Path(build_home)),
                       out / "build.log", 240) == 0, "frontend build failed"

        for scenario in ("reopened", "fresh"):
            evidence = out / scenario
            evidence.mkdir(exist_ok=True)
            scenario_results[scenario] = {}
            with tempfile.TemporaryDirectory(prefix=f"krellbot-editor-{scenario}-") as temp:
                home = Path(temp)
                env = clean_env(home)
                seed_revision = None
                prior = dict(os.environ)
                try:
                    os.environ.clear()
                    os.environ.update(env)
                    paths.ensure_layout()
                    if scenario == "reopened":
                        service = StrategyDraftService(home)
                        seeded = service.create(SEED_PACK)
                        seed_revision = seeded["revision_id"]
                        assert seeded["outcome"] == "created"
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
                        "url": url, "out": str(evidence), "scenario": scenario,
                        "seedRevision": seed_revision,
                        "files": {**files, "supportedText": supported_text,
                                  "unsupportedText": unsupported_text},
                    })
                    code = run(["node", str(browser_file)], ROOT, env,
                               evidence / "browser.log", 240)
                    browser = json.loads((evidence / "browser.json").read_text())
                    scenario_results[scenario] = browser["results"]
                    summary.setdefault("browser_versions", []).append(browser["browserVersion"])
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
                # Every file that existed before the journey (the seeded
                # revision's rev+meta) must be byte-identical afterwards; only
                # new created revisions may appear.
                scenario_results[scenario]["storage_seed_unchanged"] = all(
                    after.get(name) == digest for name, digest in before.items())
                scenario_results[scenario]["live_off_unarmed"] = not config.load_config(home).armed

                if scenario == "reopened":
                    service = StrategyDraftService(home)
                    new_revision = scenario_results[scenario].get("import_save_revision")
                    created = service.get(new_revision)
                    assert created is not None, "created revision missing from storage"
                    # create path: no parent revision, exact imported pack bytes.
                    scenario_results[scenario]["imported_bytes_saved_verbatim"] = (
                        created["parent_revision_id"] is None
                        and created["pack"] == IMPORTED_PACK
                        and created["revision_id"] != seed_revision
                        and service.get(seed_revision)["pack"] == SEED_PACK)
                else:
                    fresh_revision = scenario_results[scenario].get("no_previous_revision_id")
                    created = StrategyDraftService(home).get(fresh_revision)
                    scenario_results[scenario]["imported_bytes_saved_verbatim"] = (
                        created is not None and created["pack"] == IMPORTED_PACK
                        and created["parent_revision_id"] is None)

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
