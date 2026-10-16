#!/usr/bin/env python3
"""Real-backend/Chromium Load result qualification; local private artifacts, Linux only.

A labelled CSV FIFO holds the real runner in ingestion until explicitly released. No
runner/client/server/HTTP responses are replaced. Session removal produces a
real 403; Chromium offline mode produces a real network failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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
from krellbot.application.strategy import StrategyDraftService
from krellbot.data.cache import write_cache
from krellbot.pack.model import Candle

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
REQUIRED = (
    "bootstrap_session_csrf", "run_validation", "real_job_failure", "active_real_job",
    "network_failure_visible", "network_failure_preserves_job", "http_failure_visible",
    "http_failure_preserves_job", "real_engine_result", "narrow_keyboard_retry",
    "success_clears_error_and_stores_result", "manual_success_resets_selection",
    "no_browser_exceptions", "loopback_only", "only_research_mutations", "live_off_unarmed",
)
BROWSER = r'''
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const { chromium, expect } = require('@playwright/test');
const [url, fixtureFile, out] = process.argv.slice(2);
const fixture = JSON.parse(fs.readFileSync(fixtureFile, 'utf8'));
const assertions = {}, requests = [], responses = [], errors = [], observed = {};
let browser, context, page, version;
const id = name => page.getByTestId(`research-${name}`);
const warning = ' — outcome unknown: the command may not have been sent or applied — check state before retrying';
async function check(name, action) { await action(); assertions[name] = true; }
async function tabTo(target) {
  for (let i = 0; i < 100; i++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Keyboard target unreachable');
}
async function snapshotJob(jobId, cookies = []) {
  const headers = cookies.length ? {Cookie: cookies.map(c => `${c.name}=${c.value}`).join('; ')} : {};
  const response = await context.request.get(`${url}api/v1/jobs/${jobId}`, {headers, timeout: 10000});
  expect(response.status()).toBe(200);
  return await response.json();
}
async function preservesJob(jobId) {
  await expect(id('job-id')).toContainText(jobId);
  await expect(id('cancel')).toBeEnabled();
  await expect(id('load-result')).toBeEnabled();
  await expect(id('job-status')).toContainText('Waiting');
  await expect(id('job-error')).toHaveCount(0);
  await expect(id('result')).toHaveCount(0);
  expect((await snapshotJob(jobId)).state).toBe('running');
}
try {
  browser = await chromium.launch({headless: true, timeout: 15000,
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {})});
  version = browser.version();
  context = await browser.newContext({viewport: {width: 1100, height: 900}});
  await context.tracing.start({screenshots: true, snapshots: true, sources: false});
  page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.setDefaultNavigationTimeout(15000);
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', r => requests.push({path: new URL(r.url()).pathname,
    origin: new URL(r.url()).origin, method: r.method(), csrf: !!r.headers()['x-krellbot-csrf']}));
  page.on('response', r => responses.push({path: new URL(r.url()).pathname, status: r.status()}));
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('bootstrap_session_csrf', async () => {
    const response = await bootstrap;
    expect(response.status()).toBe(200);
    expect((await response.json()).csrf_token.length).toBeGreaterThan(0);
    expect((await context.cookies()).some(c => c.name === 'krellbot_session' && c.httpOnly)).toBe(true);
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
  });
  await page.getByRole('navigation', {name: 'Workstation navigation'})
    .getByRole('button', {name: 'Research', exact: true}).click();
  await check('run_validation', async () => {
    await id('runbar').getByRole('button', {name: 'Run', exact: true}).click();
    await expect(page.getByRole('alert')).toHaveText('Fee basis points must be a nonnegative integer');
    await expect(id('job-id')).toHaveCount(0);
  });
  await page.getByLabel(/pack path/i).fill(fixture.pack_path);
  await page.getByLabel(/dataset path/i).fill(fixture.missing_csv);
  await page.getByLabel(/fee basis points/i).fill('40');
  await page.getByLabel(/^from$/i).fill('0');
  await page.getByLabel(/^to$/i).fill(String(19 * 3600000));
  await id('runbar').getByRole('button', {name: 'Run', exact: true}).click();
  await check('real_job_failure', async () => {
    await expect(id('job-error')).toBeVisible();
    await expect(id('result')).toHaveCount(0);
    observed.job_failure = await id('job-error').innerText();
    await page.screenshot({path: `${out}/job-failure.png`, fullPage: true});
  });
  await page.getByLabel(/dataset path/i).fill(fixture.fifo);
  const submitted = page.waitForResponse(r => r.url().endsWith('/api/v1/research/jobs') && r.status() === 200);
  await id('runbar').getByRole('button', {name: 'Run', exact: true}).click();
  const job = await (await submitted).json();
  observed.job_id = job.id;
  await check('active_real_job', async () => { await preservesJob(job.id); });

  await context.setOffline(true);
  await check('network_failure_visible', async () => {
    await id('load-result').click();
    await expect(id('load-result-error')).toHaveAttribute('role', 'alert');
    await expect(id('load-result-error')).toHaveText(`Load result failed: Failed to fetch${warning}`);
    expect(await id('runbar').getByTestId('research-load-result-error').count()).toBe(1);
    observed.network_error = await id('load-result-error').innerText();
    await page.screenshot({path: `${out}/network-failure.png`, fullPage: true});
  });
  await context.setOffline(false);
  await check('network_failure_preserves_job', async () => { await preservesJob(job.id); });

  const cookies = await context.cookies();
  await context.clearCookies();
  const denied = page.waitForResponse(r => r.url().endsWith(`/jobs/${job.id}/result`) && r.status() === 403);
  await id('load-result').click();
  await denied;
  await check('http_failure_visible', async () => {
    await expect(id('load-result-error')).toHaveText(`Load result failed: request failed: 403${warning}`);
    observed.http_error = await id('load-result-error').innerText();
    await page.screenshot({path: `${out}/http-failure.png`, fullPage: true});
  });
  await context.addCookies(cookies);
  await check('http_failure_preserves_job', async () => { await preservesJob(job.id); });
  await context.clearCookies();

  // Keep the real auto-poll unauthorized while the real engine finishes the fixture.
  fs.writeFileSync(`${out}/release-fixture`, 'release real CSV reader');
  await check('real_engine_result', async () => {
    await expect.poll(async () => (await snapshotJob(job.id, cookies)).state, {timeout: 15000}).toBe('succeeded');
    observed.final_job = await snapshotJob(job.id, cookies);
    await expect(id('result')).toHaveCount(0);
    await expect(id('load-result-error')).toBeVisible();
  });
  await page.setViewportSize({width: 390, height: 844});
  await check('narrow_keyboard_retry', async () => {
    await tabTo(id('load-result'));
    await expect(id('load-result')).toBeFocused();
    await expect(id('load-result-error')).toBeVisible();
    await page.screenshot({path: `${out}/narrow-failure.png`, fullPage: true});
    await context.addCookies(cookies);
    const success = page.waitForResponse(r => r.url().endsWith(`/jobs/${job.id}/result`) && r.status() === 200);
    await page.keyboard.press('Enter');
    observed.result = await (await success).json();
    fs.writeFileSync(`${out}/real-result.json`, JSON.stringify(observed.result, null, 2));
    expect(observed.result.trace.length).toBe(20);
  });
  await check('success_clears_error_and_stores_result', async () => {
    await expect(id('load-result-error')).toHaveCount(0);
    await expect(id('result')).toBeVisible();
    await expect(id('trace-count')).toHaveText('20');
    await expect(id('job-id')).toContainText(job.id);
    await expect(id('cancel')).toBeEnabled();
    await expect(id('job-status')).toHaveCount(0);
    await page.screenshot({path: `${out}/successful-retry.png`, fullPage: true});
  });
  await check('manual_success_resets_selection', async () => {
    await id('trace-scroll').getByRole('button').first().click();
    await expect(id('bar-detail')).toBeVisible();
    const success = page.waitForResponse(r => r.url().endsWith(`/jobs/${job.id}/result`) && r.status() === 200);
    await id('load-result').click();
    await success;
    await expect(id('bar-detail')).toHaveCount(0);
    await expect(id('result')).toBeVisible();
    await expect(id('load-result-error')).toHaveCount(0);
  });
  await check('no_browser_exceptions', async () => { expect(errors).toEqual([]); });
  await check('loopback_only', async () => { expect(requests.every(r => r.origin === new URL(url).origin)).toBe(true); });
  await check('only_research_mutations', async () => {
    const mutations = requests.filter(r => r.method !== 'GET');
    expect(mutations.map(r => r.path)).toEqual([
      '/api/v1/session/bootstrap', '/api/v1/research/jobs', '/api/v1/research/jobs']);
    expect(mutations.filter(r => r.path !== '/api/v1/session/bootstrap').every(r => r.csrf)).toBe(true);
  });
} catch (error) {
  observed.error = String(error.stack || error);
  if (page) await page.screenshot({path: `${out}/failure.png`, fullPage: true}).catch(() => {});
  process.exitCode = 1;
} finally {
  fs.writeFileSync(`${out}/browser.json`, JSON.stringify({assertions, observed, requests, responses, errors, version}, null, 2));
  if (context) await context.tracing.stop({path: `${out}/trace.zip`}).catch(() => {});
  if (browser) await browser.close();
}
'''


def clean_env(home: Path) -> dict[str, str]:
    names = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "PLAYWRIGHT_BROWSERS_PATH")
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update(KRELLBOT_HOME=str(home), KRELLBOT_ENABLE_LIVE="0", PYTHONUNBUFFERED="1",
               PYTHONPATH=str(ROOT / "src"), FRONTEND_PACKAGE=str(FRONTEND / "package.json"))
    chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    if chromium:
        env["CHROMIUM_EXECUTABLE"] = chromium
    return env


def seed(home: Path) -> tuple[dict, int]:
    pack = {
        "schema_version": 1, "id": "local-load-fixture-only", "version": "1.0.0",
        "label": "LOCAL LOAD RESULT FIXTURE ONLY", "author": "Krellbot runtime verifier",
        "timeframe": "1h", "origin": "Synthetic offline load-result fixture, not investment evidence",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"], "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    service = StrategyDraftService(home)
    revision = service.create(pack)
    candles = [Candle.from_dict(dict(ts_ms=i * 3600000, open=100+i, high=101+i,
                                    low=99+i, close=100+i, volume=100)) for i in range(20)]
    csv_path, digest = write_cache(home, "kraken", "SUIUSD", "1h", candles)
    fifo = home / "LOCAL-LOAD-RESULT-FIXTURE-ONLY.csv.fifo"
    os.mkfifo(fifo, 0o600)
    # The production runner reads real CSV bytes but waits for this writer's EOF.
    fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
    try:
        body = csv_path.read_bytes()
        assert os.write(fd, body) == len(body), "Fixture exceeds FIFO capacity"
    except BaseException:
        os.close(fd)
        raise
    return {"pack_path": str(service.revision_path(revision["revision_id"])), "fifo": str(fifo),
            "missing_csv": str(home / "LOCAL-MISSING-FIXTURE-ONLY.csv"), "csv_sha256": digest,
            "label": pack["label"]}, fd


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
    # A timed-out Node child cannot run its Chromium finally block.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="research-load-result-error-"))
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    out.chmod(0o700)
    summary = {"qualified": False, "platform": sys.platform, "required_assertions": dict.fromkeys(REQUIRED, False),
               "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip(),
               "source_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True, timeout=10),
               "commands": [], "limits": "Linux only; no platform/release/live trading qualification"}
    for name in ("browser.json", "release-fixture"):
        (out / name).unlink(missing_ok=True)
    fd = None

    def run(argv: list[str], cwd: Path, env: dict[str, str], log: Path, timeout: int) -> int:
        nonlocal fd
        record = {"argv": argv, "cwd": str(cwd), "log": str(log), "timeout_seconds": timeout, "exit": None}
        summary["commands"].append(record)
        with log.open("w") as stream:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic() + timeout
                while proc.poll() is None:
                    if fd is not None and (out / "release-fixture").exists():
                        os.close(fd)
                        fd = None
                    if time.monotonic() >= deadline:
                        record["timed_out"] = True
                        raise TimeoutError(f"Deadline exceeded: {argv}")
                    time.sleep(0.05)
                record["exit"] = proc.returncode
            finally:
                stop(proc)
                record["exit"] = proc.returncode
        return record["exit"]

    try:
        assert sys.platform.startswith("linux"), "FIFO runtime probe only qualifies Linux"
        files = ["frontend/src/features/research/ResearchView.tsx",
                 "frontend/src/features/research/ResearchView.loadResultError.test.tsx",
                 "scripts/verify_research_load_result_error.py"]
        summary["source_hashes"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}
        (out / "journey.mjs").write_text(BROWSER)
        with tempfile.TemporaryDirectory(prefix="krellbot-load-result-isolated-") as temp:
            home = Path(temp)
            home.chmod(0o700)
            env = clean_env(home)
            fixture, fd = seed(home)
            (out / "fixture.json").write_text(json.dumps(fixture, indent=2))
            assert run(["npm", "run", "build"], FRONTEND, env, out / "build.log", 120) == 0, "Frontend build failed"
            argv = [sys.executable, "-m", "krellbot.cli", "workstation", "--dist", str(FRONTEND / "dist")]
            record = {"argv": argv, "cwd": str(ROOT), "log": str(out / "backend.log"), "exit": None,
                      "timeout_seconds": 150, "cleanup": "owned process group TERM/wait/KILL in finally"}
            summary["commands"].append(record)
            with (out / "backend.log").open("w") as stream:
                proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    deadline = time.monotonic() + 25
                    url = None
                    while time.monotonic() < deadline:
                        match = re.search(r"Workstation running at (http://127\.0\.0\.1:\d+/)", (out / "backend.log").read_text())
                        if match:
                            url = match[1]
                            break
                        if proc.poll() is not None:
                            break
                        time.sleep(0.1)
                    assert url, "Real loopback backend did not start"
                    code = run(["node", str(out / "journey.mjs"), url, str(out / "fixture.json"), str(out)],
                               ROOT, env, out / "browser.log", 100)
                    data = json.loads((out / "browser.json").read_text())
                    summary["browser"] = data
                    for name in REQUIRED:
                        summary["required_assertions"][name] = data["assertions"].get(name) is True
                    summary["required_assertions"]["live_off_unarmed"] = (
                        env["KRELLBOT_ENABLE_LIVE"] == "0" and not config.load_config(home).armed)
                    assert code == 0, data["observed"].get("error", "Chromium failed")
                finally:
                    if fd is not None:
                        os.close(fd)
                        fd = None
                    stop(proc)
                    record["exit"] = proc.returncode
            summary["qualified"] = (all(summary["required_assertions"].values())
                                    and all(c["exit"] == 0 for c in summary["commands"]))
    except Exception:
        summary["error"] = traceback.format_exc()
    finally:
        if fd is not None:
            os.close(fd)
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps({"qualified": summary["qualified"], "artifact": str(out / "summary.json"),
                          "error": summary.get("error")}, indent=2))
    return 0 if summary["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
