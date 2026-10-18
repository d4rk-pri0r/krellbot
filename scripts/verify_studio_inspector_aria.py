#!/usr/bin/env python3
"""Qualify Studio inspector aria-invalid honesty against the real workstation.

Run with uv run --frozen python scripts/verify_studio_inspector_aria.py.

Drives the real loopback backend and a real headless Chromium as the
admitted user: fresh isolated KRELLBOT_HOME, live execution disabled, no
exchange/payment credentials, no request interception. The journey is the
keyboard/screen-reader operator's: bootstrap a session, save a real pack
in Strategies, open Studio, select the sma2 indicator node, type a bad
length (1) and confirm the mounted input is aria-invalid="true" with
aria-describedby pointing at the per-field error node, then fix it (14)
and confirm aria-invalid clears to "false" and describedby returns to the
persistent helper hint. Requires the locked frontend dependencies and a
local headless Chromium.
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
import threading
import time
import traceback
from pathlib import Path

from krellbot.api.serve import WorkstationServer

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = [
    "session_bootstrap",
    "pack_saved",
    "studio_open",
    "indicator_node_selected",
    "helper_hint_mounted",
    "valid_state_describes_helper",
    "bad_input_marks_invalid",
    "bad_input_describes_error",
    "error_message_read",
    "apply_disabled_while_invalid",
    "fixed_input_clears_invalid",
    "fixed_input_describes_helper",
    "error_node_removed",
    "apply_enabled_after_fix",
    "status_text_invalid_then_valid",
    "export_control_unchanged",
    "loopback_only",
    "no_browser_errors",
]

BROWSER = r"""
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
const { url, output, executable, required } = JSON.parse(process.env.STUDIO_ARIA_VERIFY_CONFIG);
const assertions = Object.fromEntries(required.map(name => [name, false]));
const external = [], errors = [], observations = {};
const PACK_TEXT = JSON.stringify({
  schema_version: 1,
  id: "ns20-aria",
  version: "1.0.0",
  label: "Studio aria honesty",
  author: "aria-verify",
  timeframe: "1h",
  indicators: { sma2: { fn: "sma", src: "close", len: 2 } },
  entry: ["close", "crosses_above", "sma2"],
  exit: ["close", "crosses_below", "sma2"],
  risk: { max_account_pct: 100, stop: { type: "pct", pct: 50 } },
  markets: [{ venue: "kraken", pair: "SUIUSD" }],
}, null, 2);
const ERROR_ID = 'studio-node-inspector-len-error';
const HINT_ID = 'studio-indicator-len-hint';
let browser, context, page;
process.on('SIGTERM', () => {
  void (async () => {
    if (browser) await browser.close();
    process.exit(124);
  })();
});
async function check(name, action) { await action(); assertions[name] = true; }
async function evidence(name) {
  await page.screenshot({path: `${output}/${name}.png`, fullPage: true});
  fs.writeFileSync(`${output}/${name}.txt`, await page.locator('body').innerText());
}
async function lenInput() { return page.getByTestId('studio-indicator-len'); }
async function describedBy(input) {
  const ids = ((await input.getAttribute('aria-describedby')) ?? '').trim();
  if (ids === '') return null;
  for (const id of ids.split(/\s+/)) {
    const el = await page.locator(`#${id}`).count() ? page.locator(`#${id}`) : null;
    if (el) return el;
  }
  return null;
}
try {
  browser = await chromium.launch({headless: true, timeout: 15000,
    ...(executable ? {executablePath: executable} : {})});
  context = await browser.newContext({viewport: {width: 1280, height: 900}});
  context.setDefaultTimeout(10000);
  context.setDefaultNavigationTimeout(20000);
  page = await context.newPage();
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => {
    const parsed = new URL(request.url());
    if (parsed.origin !== new URL(url).origin) external.push(request.url());
  });
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('session_bootstrap', async () => {
    expect((await bootstrap).status()).toBe(200);
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
    expect((await context.cookies()).some(c => c.name === 'krellbot_session' && c.httpOnly)).toBe(true);
  });
  // Save a real pack through the real Strategies editor so Studio mounts
  // the inspector from a saved revision (the operator's own journey).
  await page.getByRole('navigation', {name: 'Workstation navigation'})
    .getByRole('button', {name: 'Strategies', exact: true}).click();
  const technical = page.getByTestId('editor-technical-section');
  if ((await technical.getAttribute('open')) === null) {
    await technical.locator('summary').click();
  }
  await page.getByLabel(/raw json/i).fill(PACK_TEXT);
  await page.getByRole('button', {name: /^save$/i}).click();
  await check('pack_saved', async () => {
    await expect(page.getByTestId('editor-revision-id')).toContainText('revision:', {timeout: 15000});
  });
  await page.getByRole('navigation', {name: 'Workstation navigation'})
    .getByRole('button', {name: 'Studio', exact: true}).click();
  await check('studio_open', async () => {
    await expect(page.getByTestId('studio-pack-id')).toHaveText('ns20-aria');
    await expect(page.getByTestId('studio-indicator-len')).toBeHidden();
  });
  // ReactFlow nodes sit in an absolutely positioned viewport; the DOM
  // click event is what its onNodeClick handler listens for (same as the
  // committed ns20 studio spec).
  await page.getByTestId('studio-node-sma2').evaluate(el => el.click());
  await page.waitForTimeout(300);
  await check('indicator_node_selected', async () => {
    await expect(page.getByTestId('studio-indicator-len')).toBeVisible();
    await expect(page.getByTestId('studio-node-inspector-title')).toHaveText('sma2');
  });
  await evidence('studio-node-selected');
  await check('helper_hint_mounted', async () => {
    await expect(page.locator(`#${HINT_ID}`)).toHaveText('Whole number between 2 and 600');
  });
  const input0 = await lenInput();
  await check('valid_state_describes_helper', async () => {
    await expect(input0).toHaveAttribute('aria-invalid', 'false');
    await expect(input0).toHaveAttribute('aria-describedby', HINT_ID);
    const described = await describedBy(input0);
    expect(described, 'describedby must resolve to a mounted element').not.toBeNull();
    await expect(described).toHaveAttribute('id', HINT_ID);
  });
  // Keyboard-only path: focus the input and type the bad value 1.
  await input0.focus();
  await input0.fill('1');
  await input0.blur();
  const input1 = await lenInput();
  await evidence('studio-invalid-1');
  await check('bad_input_marks_invalid', async () => {
    await expect(input1).toHaveAttribute('aria-invalid', 'true');
  });
  await check('bad_input_describes_error', async () => {
    await expect(input1).toHaveAttribute('aria-describedby', ERROR_ID);
    const described = await describedBy(input1);
    expect(described, 'describedby must resolve to the mounted error node').not.toBeNull();
    await expect(described).toHaveAttribute('id', ERROR_ID);
    await expect(described).toHaveAttribute('role', 'alert');
  });
  await check('error_message_read', async () => {
    await expect(page.getByTestId(ERROR_ID))
      .toHaveText('Enter a whole number between 2 and 600.');
  });
  await check('apply_disabled_while_invalid', async () => {
    await expect(page.getByTestId('studio-node-inspector-apply')).toBeDisabled();
  });
  // Fix the value: aria-invalid clears, describedby returns to the hint.
  await input1.focus();
  await input1.fill('14');
  await input1.blur();
  const input2 = await lenInput();
  await evidence('studio-valid-14');
  await check('fixed_input_clears_invalid', async () => {
    await expect(input2).toHaveAttribute('aria-invalid', 'false');
  });
  await check('fixed_input_describes_helper', async () => {
    await expect(input2).toHaveAttribute('aria-describedby', HINT_ID);
    const described = await describedBy(input2);
    expect(described, 'describedby must resolve to the mounted hint').not.toBeNull();
    await expect(described).toHaveAttribute('id', HINT_ID);
  });
  await check('error_node_removed', async () => {
    await expect(page.getByTestId(ERROR_ID)).toHaveCount(0);
  });
  await check('apply_enabled_after_fix', async () => {
    await expect(page.getByTestId('studio-node-inspector-apply')).toBeEnabled();
  });
  await check('status_text_invalid_then_valid', async () => {
    // Re-drive the summary text through the same input to prove the
    // existing visible status stays honest alongside the aria wiring.
    await input2.fill('1');
    await expect(page.getByTestId('studio-node-inspector-status')).toHaveText('Invalid');
    await input2.fill('14');
    await expect(page.getByTestId('studio-node-inspector-status')).toHaveText('Valid');
  });
  await check('export_control_unchanged', async () => {
    await expect(page.getByTestId('studio-indicator-spec-export')).toBeVisible();
  });
  await check('loopback_only', async () => expect(external).toEqual([]));
  await check('no_browser_errors', async () => expect(errors).toEqual([]));
  observations.browser_version = browser.version();
} catch (error) {
  observations.failure = String(error.stack || error);
  if (page) await evidence('failure').catch(() => {});
} finally {
  if (browser) await browser.close();
  const qualified = Object.values(assertions).every(Boolean);
  fs.writeFileSync(`${output}/browser.json`, JSON.stringify({qualified,
    required_assertions: assertions, observations, errors, external}, null, 2));
  process.exitCode = qualified ? 0 : 1;
}
"""


def serve() -> int:
    home = Path(os.environ["KRELLBOT_HOME"])
    server = WorkstationServer(home, dist_dir=ROOT / "frontend" / "dist")
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    try:
        server.start()
        print(f"RUNTIME_URL={server.url}", flush=True)
        stopped.wait(timeout=180)
    finally:
        server.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        return serve()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()
    output = (args.output_dir or ROOT / "tests_tmp" / "studio-inspector-aria" / f"{sha[:12]}-{time.time_ns()}").resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    (output / "browser.mjs").write_text(BROWSER)
    source_files = [
        "frontend/src/features/studio/StudioNodeInspector.tsx",
        "frontend/src/features/studio/StudioNodeInspector.aria.test.tsx",
        "scripts/verify_studio_inspector_aria.py",
    ]

    def source_hash(name: str) -> str | None:
        path = ROOT / name
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

    summary = {
        "source_sha": sha, "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, timeout=10)),
        "source_hashes": {name: source_hash(name) for name in source_files},
        "platform": sys.platform, "qualified": False, "commands": [],
        "isolated_home": True, "live_enabled": False,
        "failure_modes": "no request interception, no mocked production client; real session bootstrap, real editor save, real Studio canvas",
        "invocation": ["uv", "run", "--frozen", "python", "scripts/verify_studio_inspector_aria.py"],
        "required_assertions": dict.fromkeys(REQUIRED, False),
        "output_dir": str(output),
    }
    env = {key: value for key, value in os.environ.items() if not (
        key.startswith(("KRELLBOT_", "KRAKEN_", "COINBASE_", "STRIPE_", "PAYPAL_"))
        or any(word in key.upper() for word in ("SECRET", "TOKEN", "PASSWORD", "API_KEY"))
    )}
    env["KRELLBOT_ENABLE_LIVE"] = "0"
    env["PYTHONUNBUFFERED"] = "1"
    process = None

    def stop(child: subprocess.Popen) -> None:
        if child.poll() is not None:
            return
        if os.name == "posix":
            os.killpg(child.pid, signal.SIGTERM)
        else:
            child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(child.pid, signal.SIGKILL)
            else:
                child.kill()
            child.wait(timeout=5)

    def run(name: str, argv: list[str], cwd: Path, *, stdin: str | None = None, timeout: int = 120) -> int:
        record = {"name": name, "argv": argv, "cwd": str(cwd), "exit_code": None}
        summary["commands"].append(record)
        child = None
        with (output / f"{name}.log").open("w") as log:
            try:
                child = subprocess.Popen(
                    argv, cwd=cwd, env=env, text=True,
                    stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=os.name == "posix",
                )
                child.communicate(input=stdin, timeout=timeout)
                record["exit_code"] = child.returncode
            except subprocess.TimeoutExpired:
                record["exit_code"] = 124
            except OSError as error:
                log.write(str(error))
                record["exit_code"] = 127
            finally:
                if child is not None:
                    stop(child)
                    if child.stdin is not None:
                        child.stdin.close()
        return record["exit_code"]

    try:
        if run("build", ["npm", "run", "build"], ROOT / "frontend", timeout=300) != 0:
            raise RuntimeError("current frontend build failed")
        with tempfile.TemporaryDirectory(prefix="krellbot-studio-aria-home-") as fresh_home:
            env["KRELLBOT_HOME"] = fresh_home
            argv = [sys.executable, str(Path(__file__).resolve()), "--serve"]
            backend_record = {"name": "backend", "argv": argv, "cwd": str(ROOT), "exit_code": None}
            summary["commands"].append(backend_record)
            with (output / "backend.log").open("w") as log:
                process = subprocess.Popen(
                    argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=os.name == "posix",
                )
                try:
                    deadline = time.monotonic() + 30
                    url = None
                    while time.monotonic() < deadline:
                        match = re.search(r"RUNTIME_URL=(http://127[.]0[.]0[.]1:[0-9]+/)", (output / "backend.log").read_text())
                        if match:
                            url = match.group(1)
                            break
                        if process.poll() is not None:
                            raise RuntimeError("real backend exited before readiness")
                        time.sleep(0.05)
                    if url is None:
                        raise RuntimeError("real backend readiness timed out")
                    env["STUDIO_ARIA_VERIFY_CONFIG"] = json.dumps({
                        "url": url, "output": str(output), "required": REQUIRED,
                        "executable": shutil.which("chromium") or shutil.which("chromium-browser"),
                    })
                    exit_code = run("browser", ["node", "--input-type=module"], ROOT / "frontend", stdin=BROWSER, timeout=300)
                    result_path = output / "browser.json"
                    if result_path.exists():
                        result = json.loads(result_path.read_text())
                        summary["required_assertions"] = result["required_assertions"]
                        summary["browser_evidence"] = {
                            "browser_version": result.get("observations", {}).get("browser_version"),
                            "errors": result.get("errors", []),
                            "external_requests": result.get("external", []),
                            "screenshots": sorted(p.name for p in output.glob("*.png")),
                        }
                        summary["qualified"] = exit_code == 0 and all(
                            summary["required_assertions"].get(name) is True for name in REQUIRED
                        )
                finally:
                    stop(process)
                    backend_record["exit_code"] = process.returncode
                    if process.returncode != 0:
                        summary["qualified"] = False
    except Exception:
        summary["failure"] = traceback.format_exc()
        summary["qualified"] = False
    finally:
        summary["exit_code"] = 0 if summary["qualified"] else 1
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["qualified"] else 1


if __name__ == "__main__":
    sys.exit(main())
