#!/usr/bin/env python3
"""Offline loopback/Chromium verification. Retained artifacts are private session evidence."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import traceback

from krellbot import config
from verify_research_trace_virtual_keyboard import clean_env, seed

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BASE = "3e32b86512e92bb3de5a96bc1c70a10d7b705304"
SOURCE = "frontend/src/features/research/ResearchView.tsx"
ASSERTIONS = (
    "existing_detail_source_intact", "live_status_source_sibling", "existing_testids_byte_equal",
    "visible_source_literals_unchanged", "existing_readers_and_change_guard", "bootstrap_session_csrf",
    "empty_copy_unchanged", "real_persisted_trace", "status_semantics_and_sibling",
    "keyboard_tab_enter_first_bar", "row_0_announcement", "row_2_announcement", "row_4_announcement",
    "same_row_no_reannouncement", "stale_rerender_no_reannouncement", "visible_selected_bar_detail_unchanged",
    "clear_selection_announcement", "reselect_after_clear", "visible_result_literals_unchanged",
    "loopback_only", "no_trading_requests", "live_trading_disabled",
)
BROWSER = r'''
import fs from 'node:fs';
import {createRequire} from 'node:module';
const {chromium, expect} = createRequire(process.env.FRONTEND_PACKAGE)('@playwright/test');
const [url, home, out] = process.argv.slice(2);
const results = {}, requests = [], observed = {};
let browser, context, page;
const id = name => page.getByTestId(`research-${name}`);
const row = i => id('trace-scroll').getByRole('button', {name: String(i * 3600000), exact: true});
async function check(name, action) { await action(); results[name] = true; }
async function tabTo(target) {
  for (let i = 0; i < 180; i++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Tab target unreachable');
}
try {
  browser = await chromium.launch({headless: true,
    args: ['--enable-experimental-web-platform-features', '--force-prefers-reduced-motion'],
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {})});
  context = await browser.newContext({viewport: {width: 1100, height: 900}, reducedMotion: 'reduce'});
  await context.tracing.start({screenshots: true, snapshots: true, sources: false});
  page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.setDefaultNavigationTimeout(15000);
  page.on('request', r => requests.push({path: new URL(r.url()).pathname,
    origin: new URL(r.url()).origin, method: r.method(), csrf: !!r.headers()['x-krellbot-csrf']}));
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('bootstrap_session_csrf', async () => {
    const response = await bootstrap;
    expect(response.status()).toBe(200);
    expect((await response.json()).csrf_token.length).toBeGreaterThan(0);
    expect((await context.cookies()).some(c => c.httpOnly && c.name === 'krellbot_session')).toBe(true);
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
  });
  const navigation = page.getByRole('navigation', {name: 'Workstation navigation'});
  await tabTo(navigation.getByRole('button', {name: 'Home', exact: true}));
  for (const name of ['Workstation', 'Strategies', 'Research']) {
    await page.keyboard.press('ArrowRight');
    await expect(navigation.getByRole('button', {name, exact: true})).toBeFocused();
  }
  await page.keyboard.press('Enter');
  await check('empty_copy_unchanged', async () => {
    await expect(id('state-empty')).toContainText('No research run yet. Submit a window to populate this view.');
    await expect(id('local-preview')).toHaveText('Local preview only — live trading unavailable');
  });
  await page.getByLabel(/pack path/i).fill(`${home}/LOCAL-KEYBOARD-FIXTURE.json`);
  await page.getByLabel(/dataset path/i).fill(`${home}/LOCAL-KEYBOARD-FIXTURE.csv`);
  await page.getByLabel(/fee basis points/i).fill('40');
  await page.getByLabel(/^from$/i).fill('0');
  await page.getByLabel(/^to$/i).fill(String(199 * 3600000));
  const response = page.waitForResponse(r => /\/api\/v1\/jobs\/[^/]+\/result$/.test(r.url()) && r.status() === 200);
  await tabTo(page.getByRole('button', {name: 'Run', exact: true}));
  await page.keyboard.press('Enter');
  const stored = await (await response).json();
  fs.writeFileSync(`${out}/real-result.json`, JSON.stringify(stored, null, 2));
  await check('real_persisted_trace', async () => {
    await expect(id('result')).toBeVisible();
    expect(stored.trace.length).toBe(200);
    await expect(id('trace-count')).toHaveText('200');
    const reload = page.waitForResponse(r => /\/api\/v1\/jobs\/[^/]+\/result$/.test(r.url()) && r.status() === 200);
    await id('load-result').click(); await reload;
    await expect(id('bar-detail-live')).toHaveText('');
    await expect(id('bar-detail')).toHaveCount(0);
  });
  await check('status_semantics_and_sibling', async () => {
    await expect(id('bar-detail-live')).toHaveAttribute('role', 'status');
    await expect(id('bar-detail-live')).toHaveAttribute('aria-live', 'polite');
    await expect(id('bar-detail-live')).toHaveAttribute('aria-atomic', 'true');
    expect(await id('bar-detail-live').evaluate(el => {
      const s = getComputedStyle(el);
      return s.position === 'absolute' && s.clipPath === 'inset(50%)' && s.display !== 'none' && s.visibility !== 'hidden';
    })).toBe(true);
  });
  await id('bar-detail-live').evaluate(el => {
    window.liveProbe = {node: el, mutations: []};
    window.liveProbe.observer = new MutationObserver(records => window.liveProbe.mutations.push({text: el.textContent, count: records.length}));
    window.liveProbe.observer.observe(el, {childList: true, characterData: true, subtree: true});
  });
  const announcement = i => `Selected bar ${stored.trace[i].bar_ts} close ${stored.trace[i].input.close}`;
  const count = () => page.evaluate(() => window.liveProbe.mutations.length);
  await tabTo(row(0));
  await check('keyboard_tab_enter_first_bar', async () => {
    await expect(row(0)).toBeFocused(); await page.keyboard.press('Enter');
    await expect(id('bar-detail-live')).toHaveText(announcement(0));
  });
  for (const i of [0, 2, 4]) await check(`row_${i}_announcement`, async () => {
    await row(i).click(); await expect(id('bar-detail-live')).toHaveText(announcement(i));
    (observed.announcements ??= []).push(await id('bar-detail-live').textContent());
  });
  await check('same_row_no_reannouncement', async () => {
    const before = await count(); await row(4).click(); await row(4).click();
    await page.waitForTimeout(150); expect(await count()).toBe(before);
    await expect(id('bar-detail-live')).toHaveText(announcement(4));
  });
  await check('stale_rerender_no_reannouncement', async () => {
    const before = await count(); await page.getByLabel(/fee basis points/i).fill('41');
    await page.waitForTimeout(150); expect(await count()).toBe(before);
    await expect(id('bar-detail-live')).toHaveText(announcement(4));
  });
  await check('visible_selected_bar_detail_unchanged', async () => {
    await expect(id('bar-detail').locator('p').first()).toHaveText('Selected bar detail');
    await expect(id('bar-detail').locator('p').nth(1)).toHaveText(`close: ${stored.trace[4].input.close}`);
    for (const condition of stored.trace[4].conditions) await expect(id('bar-detail')).toContainText(condition.path);
    expect(await id('bar-detail-live').evaluate(el => el.parentElement === document.querySelector('[data-testid="research-bar-detail"]').parentElement && window.liveProbe.node === el)).toBe(true);
    await page.screenshot({path: `${out}/selected-row-4.png`, fullPage: true});
  });
  await check('visible_result_literals_unchanged', async () => {
    for (const label of ['Equity', 'Max drawdown', 'Total return (%)', 'Fee basis points', 'Trade count', 'Data manifest sha256'])
      await expect(id('result').getByText(label, {exact: true}).first()).toBeVisible();
    for (const name of ['Run', 'Cancel', 'Load result', 'Export result'])
      await expect(page.getByRole('button', {name, exact: true})).toBeVisible();
    await expect(page.getByRole('button', {name: /^Export trace CSV for run /})).toBeVisible();
    await expect(id('receipt-detail').locator('summary')).toHaveText('Raw stored result (JSON, exactly as stored)');
    await id('receipt-detail').locator('summary').click();
    await expect(id('export')).toHaveText(JSON.stringify(stored));
  });
  await check('clear_selection_announcement', async () => {
    await id('load-result').click(); await expect(id('bar-detail-live')).toHaveText('Selected bar cleared');
    await expect(id('bar-detail')).toHaveCount(0);
  });
  await check('reselect_after_clear', async () => {
    await row(4).click(); await expect(id('bar-detail-live')).toHaveText(announcement(4));
  });
  observed.polite_region_mutations = await page.evaluate(() => window.liveProbe.mutations);
  await check('loopback_only', async () => expect(requests.every(r => r.origin === new URL(url).origin)).toBe(true));
  await check('no_trading_requests', async () => {
    expect(requests.filter(r => r.method !== 'GET').map(r => r.path)).toEqual(['/api/v1/session/bootstrap', '/api/v1/research/jobs']);
    expect(requests.filter(r => r.path === '/api/v1/research/jobs').every(r => r.csrf)).toBe(true);
  });
} catch (error) {
  results.error = String(error.stack || error);
  if (page) await page.screenshot({path: `${out}/failure.png`, fullPage: true}).catch(() => {});
  process.exitCode = 1;
} finally {
  fs.writeFileSync(`${out}/browser.json`, JSON.stringify({results, observed, requests}, null, 2));
  if (context) await context.tracing.stop({path: `${out}/trace.zip`}).catch(() => {});
  if (browser) await browser.close();
}
'''


def source_probe(summary: dict) -> None:
    source = (ROOT / SOURCE).read_text()
    baseline = subprocess.check_output(["git", "show", f"{BASE}:{SOURCE}"], cwd=ROOT, text=True)
    checks = summary["required_assertions"]
    pattern = r'        \{selectedBar \? \(\n.*?        \) : null\}'
    old, new = re.search(pattern, baseline, re.S), re.search(pattern, source, re.S)
    assert old and new and old.group() == new.group(), "Existing detail JSX changed"
    summary["detail_start_lines"] = {"base": baseline[:old.start()].count("\n") + 1, "candidate": source[:new.start()].count("\n") + 1}
    assert abs(summary["detail_start_lines"]["candidate"] - summary["detail_start_lines"]["base"]) <= 80
    checks["existing_detail_source_intact"] = True
    live_pattern = r'        <div\n          role="status"\n          aria-live="polite"\n          aria-atomic="true"\n          data-testid="research-bar-detail-live".*?        </div>\n'
    live = re.search(live_pattern, source, re.S)
    assert live and live.start() == new.end() + 1, "Expected following same-parent sibling"
    assert source.count('data-testid="research-bar-detail-live"') == 1
    checks["live_status_source_sibling"] = True
    id_pattern = r'^\s*(?:data-testid=|testId: )"(research-[a-z0-9-]+)"'
    old_ids, new_ids = Counter(re.findall(id_pattern, baseline, re.M)), Counter(re.findall(id_pattern, source, re.M))
    del new_ids["research-bar-detail-live"]
    assert new_ids == old_ids, "Existing anchored literal IDs changed"
    summary["existing_testids"] = sorted(old_ids)
    summary["brief_ids_absent_at_frozen_base"] = [name for name in (
        "research-bar-close", "research-conditions", "research-condition", "research-condition-path",
        "research-condition-outcome", "research-trace-empty", "research-trace-error", "research-trace-loading",
    ) if f'"{name}"' not in baseline]
    checks["existing_testids_byte_equal"] = True
    hook_pattern = r'  const \[barAnnouncement, setBarAnnouncement\] = useState<.*?  \}, \[selectedBar, trace\]\);\n\n'
    without_hook, n = re.subn(hook_pattern, "", source, count=1, flags=re.S)
    assert n == 1
    without_additions, n = re.subn(live_pattern, "", without_hook, count=1, flags=re.S)
    assert n == 1 and without_additions == baseline, "Changes outside bounded hook and AT sibling"
    checks["visible_source_literals_unchanged"] = True
    for marker in ("readBarTs(selectedBar, trace.indexOf(selectedBar))", "if (previous.barTs === barTs) return previous;",
                   "`Selected bar ${barTs} close ${readBarClose(selectedBar)}`", '"Selected bar cleared"',
                   "{barAnnouncement.message}", "message: string | null", "{ barTs: null, message: null }"):
        assert marker in source, f"Missing marker: {marker}"
    checks["existing_readers_and_change_guard"] = True
    summary["source_sha256"] = hashlib.sha256(source.encode()).hexdigest()


def stop(proc: subprocess.Popen) -> int:
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        code = proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        code = proc.wait(timeout=5)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return code


def run(argv: list[str], cwd: Path, env: dict[str, str], log: Path, summary: dict) -> int:
    record = {"argv": argv, "cwd": str(cwd), "log": str(log), "exit": None}
    summary["commands"].append(record)
    with log.open("w") as stream:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            record["exit"] = proc.wait(timeout=180)
        finally:
            record["exit"] = stop(proc)
    return record["exit"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="research-bar-detail-live-evidence-"))
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o700)
    summary = {"qualified": False, "required_assertions": {name: False for name in ASSERTIONS}, "commands": [],
               "base_sha": BASE,
               "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "source_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True),
               "qualification_scope": "Linux Chromium DOM/mutation evidence only; not actual screen reader or Windows qualification",
               "fixture": "LOCAL KEYBOARD FIXTURE ONLY: 200 synthetic hourly bars; real engine/storage/API; no keys/orders"}
    try:
        source_probe(summary)
        browser_file = out / "journey.mjs"
        browser_file.write_text(BROWSER)
        with tempfile.TemporaryDirectory(prefix="krellbot-bar-detail-isolated-") as temp:
            home = Path(temp)
            home.chmod(0o700)
            env = clean_env(home)
            seed(home)
            summary["required_assertions"]["live_trading_disabled"] = env["KRELLBOT_ENABLE_LIVE"] == "0" and not config.load_config(home).armed
            assert run(["npm", "run", "build"], FRONTEND, env, out / "build.log", summary) == 0
            argv = [sys.executable, "-m", "krellbot.cli", "workstation", "--dist", str(FRONTEND / "dist")]
            record = {"argv": argv, "cwd": str(ROOT), "log": str(out / "backend.log"), "exit": None}
            summary["commands"].append(record)
            with (out / "backend.log").open("w") as stream:
                proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    deadline, url = time.monotonic() + 25, None
                    while time.monotonic() < deadline:
                        match = re.search(r"Workstation running at (http://127\.0\.0\.1:\d+/)", (out / "backend.log").read_text())
                        if match:
                            url = match[1]
                            break
                        if proc.poll() is not None:
                            break
                        time.sleep(0.1)
                    assert url, "Real backend failed to start"
                    code = run(["node", str(browser_file), url, str(home), str(out)], ROOT, env, out / "browser.log", summary)
                    data = json.loads((out / "browser.json").read_text())
                    summary["browser"] = data
                    for name in ASSERTIONS:
                        if name in data["results"]:
                            summary["required_assertions"][name] = data["results"][name] is True
                    assert code == 0, data["results"].get("error", "Browser failed")
                finally:
                    record["exit"] = stop(proc)
            summary["qualified"] = all(summary["required_assertions"].values()) and all(c["exit"] == 0 for c in summary["commands"])
    except Exception:
        summary["error"] = traceback.format_exc()
    finally:
        (out / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps({"qualified": summary["qualified"], "artifact": str(out / "results.json"), "error": summary.get("error")}, indent=2))
    return 0 if summary["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
