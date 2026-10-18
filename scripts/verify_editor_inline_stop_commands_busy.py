#!/usr/bin/env python3
"""Qualify Editor inline-stop busy behavior against the real loopback workstation.

Run with python3 scripts/verify_editor_inline_stop_commands_busy.py.
Requires the locked frontend dependencies, installed Python application dependencies,
uv and a local headless Chromium. Does not sync or install dependencies.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = [f"{intent}_{key}" for key in ("Enter", "Space")
            for intent in ("pause", "resume", "disarm", "refresh", "apply")] + [
    "bootstrap", "live_disabled", "mounted_armed", "raise_stop_refused", "invalid_stop",
    "successful_disarm", "loopback_only", "no_browser_errors",
]
BROWSER = r"""
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
const {url, output, executable, required, home} = JSON.parse(process.env.INLINE_BUSY_CONFIG);
const assertions = Object.fromEntries(required.map(key => [key, false]));
const observations = {}, requests = [], errors = [], external = [];
let browser, context, page;
const intents = [
  ['pause', 'Pause entries', 'Pausing…', 'paper.pause_entries'],
  ['resume', 'Resume entries', 'Resuming…', 'paper.resume_entries'],
  ['disarm', 'Disarm', 'Disarming…', 'paper.disarm'],
  ['refresh', 'Refresh status', 'Refreshing…', 'refresh'],
  ['apply', 'Apply new stop', 'Applying…', 'paper.raise_stop'],
];
async function check(name, fn) { await fn(); assertions[name] = true; }
const panel = () => page.getByTestId('editor-inline-stop');
const buttonFor = id => page.getByTestId(`editor-inline-stop-${id}`);
const live = () => panel().getByRole('status');
async function evidence(name) {
  await page.screenshot({path: `${output}/${name}.png`, fullPage: true});
  fs.writeFileSync(`${output}/${name}.txt`, await panel().innerText());
  fs.writeFileSync(`${output}/${name}.aria.txt`, await panel().ariaSnapshot());
}
async function tabTo(button) {
  for (let n = 0; n < 180; n++) {
    if (await button.evaluate(el => document.activeElement === el)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Tab target unreachable');
}
const count = command => requests.filter(r => command === 'refresh'
  ? r.path === '/api/v1/paper/status' && r.method === 'GET'
  : r.command === command && r.method === 'POST').length;
async function drive(id, activation, {refused = null, disarmed = false} = {}) {
  const [, idle, active, wire] = intents.find(i => i[0] === id);
  const button = buttonFor(id);
  const name = `${id}-${activation}-${refused ? 'refused' : 'ok'}`;
  await expect(button).toBeEnabled();
  await expect(button).toHaveText(idle);
  await expect(button).toHaveAttribute('aria-busy', 'false');
  await expect(button).toHaveAttribute('aria-keyshortcuts', 'Enter Space');
  await tabTo(button);
  await expect(button).toBeFocused();
  const unrelated = page.getByRole('button', {name: /^(Save|Validate)$/});
  await expect(unrelated).toHaveCount(2);
  const unrelatedBefore = await unrelated.evaluateAll(els => els.map(el => el.disabled));
  const before = count(wire);
  const readsBefore = count('refresh');
  const responsePromise = page.waitForResponse(r => wire === 'refresh'
    ? new URL(r.url()).pathname === '/api/v1/paper/status'
    : new URL(r.url()).pathname === '/api/v1/commands' && r.request().postDataJSON().command === wire);
  const started = Date.now();
  await page.keyboard.press(activation);
  await expect(button).toHaveAttribute('aria-busy', 'true');
  await expect(button).toHaveText(active);
  await expect(button).toBeDisabled();
  await expect(live()).toHaveAttribute('aria-live', 'polite');
  await expect(live()).toHaveText(active);
  for (const [otherId] of intents) {
    await expect(buttonFor(otherId)).toBeDisabled();
    if (otherId !== id) await expect(buttonFor(otherId)).toHaveAttribute('aria-busy', 'false');
  }
  expect(await unrelated.evaluateAll(els => els.map(el => el.disabled))).toEqual(unrelatedBefore);
  observations[name] = await button.evaluate(el => ({
    busy: el.getAttribute('aria-busy'), disabled: el.disabled, text: el.textContent,
    focusedWhileDisabled: el === document.activeElement,
  }));
  const box = await button.boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await button.evaluate(el => el.click());
  await page.keyboard.down(activation); await page.keyboard.down(activation); await page.keyboard.up(activation);
  await evidence(`${name}-busy`);
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const result = await response.json();
  expect(Date.now() - started).toBeGreaterThanOrEqual(1500);
  if (wire !== 'refresh') expect(result.ok).toBe(refused === null);
  if (refused) {
    expect(result.message).toBe(refused);
    await expect(page.getByTestId('inline-stop-caption')).toHaveText(`Refused: ${refused}`);
  }
  // The same intent remains visibly busy throughout the real follow-up GET.
  if (wire !== 'refresh' && id !== 'disarm' && !refused) {
    await expect(button).toHaveAttribute('aria-busy', 'true');
    await expect(live()).toHaveText(active);
  }
  await expect(button).toHaveAttribute('aria-busy', 'false');
  await expect(button).toHaveText(idle);
  await expect(live()).toBeEmpty();
  if (disarmed) {
    await expect(button).toBeDisabled();
    await expect(page.getByTestId('inline-stop-caption')).toHaveText('Disarmed');
    await expect(buttonFor('apply')).toHaveCount(0);
    await expect(buttonFor('refresh')).toHaveCount(0);
  } else {
    await expect(button).toBeEnabled();
  }
  await page.waitForTimeout(100);
  expect(count(wire)).toBe(before + 1);
  expect(count('refresh')).toBe(readsBefore + (wire === 'refresh' || (!refused && id !== 'disarm') ? 1 : 0));
  observations[`${name}-settled`] = {before, after: count(wire), response: result,
    caption: await page.getByTestId('inline-stop-caption').textContent()};
  await evidence(`${name}-settled`);
}
try {
  browser = await chromium.launch({headless: true, ...(executable ? {executablePath: executable} : {})});
  context = await browser.newContext({viewport: {width: 1280, height: 900}});
  await context.tracing.start({screenshots: true, snapshots: true});
  page = await context.newPage(); page.setDefaultTimeout(10000);
  page.on('pageerror', e => errors.push(String(e)));
  page.on('request', r => {
    const u = new URL(r.url());
    if (u.origin !== new URL(url).origin) external.push(r.url());
    requests.push({path: u.pathname, method: r.method(),
      command: r.method() === 'POST' && u.pathname === '/api/v1/commands' ? r.postDataJSON().command : null});
  });
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('bootstrap', async () => {
    expect((await bootstrap).status()).toBe(200);
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
  });
  await check('live_disabled', async () => {
    const state = await page.evaluate(async () => (await fetch('/api/v1/operations')).json());
    expect(state.live.live_enabled).toBe(false);
  });
  const nav = page.getByRole('navigation', {name: 'Workstation navigation'});
  await tabTo(nav.getByRole('button', {name: 'Home', exact: true}));
  for (let n = 0; n < 10; n++) {
    if (await nav.getByRole('button', {name: 'Strategies', exact: true}).evaluate(el => el === document.activeElement)) break;
    await page.keyboard.press('ArrowRight');
  }
  await expect(nav.getByRole('button', {name: 'Strategies', exact: true})).toBeFocused();
  await page.keyboard.press('Enter');
  await check('mounted_armed', async () => {
    await expect(panel()).toBeVisible();
    await expect(page.getByTestId('inline-stop-caption')).toHaveText('Armed at kraken SUIUSD · Entries active');
  });
  const input = page.getByTestId('editor-inline-stop-new-stop');
  await check('invalid_stop', async () => {
    await expect(input).toHaveValue('');
    await expect(input).toHaveAttribute('aria-invalid', 'true');
    await expect(buttonFor('apply')).toBeDisabled();
    await expect(buttonFor('apply')).toHaveAttribute('aria-busy', 'false');
    await expect(buttonFor('apply')).toHaveAttribute('aria-keyshortcuts', 'Enter Space');
    const before = count('paper.raise_stop');
    await buttonFor('apply').evaluate(el => el.click());
    expect(count('paper.raise_stop')).toBe(before);
  });
  let nextStop = 2;
  for (const key of ['Enter', 'Space']) {
    await input.fill(String(nextStop++));
    await check(`pause_${key}`, () => drive('pause', key));
    await expect(page.getByTestId('editor-inline-stop-entries')).toHaveText('Entries paused');
    await expect(page.getByTestId('inline-stop-caption')).toHaveText(key === 'Enter' ? 'Armed at kraken SUIUSD · Entries paused' : 'Stop raised to 2');
    await check(`resume_${key}`, () => drive('resume', key));
    await expect(page.getByTestId('editor-inline-stop-entries')).toHaveText('Entries active');
    await expect(page.getByTestId('inline-stop-caption')).toHaveText(key === 'Enter' ? 'Armed at kraken SUIUSD · Entries active' : 'Stop raised to 2');
    // A real persisted-state change yields a real stale-control refusal.
    const configPath = `${home}/config.json`, saved = fs.readFileSync(configPath);
    try {
      fs.writeFileSync(configPath, JSON.stringify({armed: [], live_first_armed: false}));
      await check(`disarm_${key}`, () => drive('disarm', key, {refused: 'not armed: kraken SUIUSD'}));
    } finally { fs.writeFileSync(configPath, saved); }
    await check(`refresh_${key}`, () => drive('refresh', key));
    await check(`apply_${key}`, () => drive('apply', key));
  }
  await input.fill('1');
  await check('raise_stop_refused', () => drive('apply', 'Enter', {refused: 'new stop must be strictly above the current stop'}));
  await check('successful_disarm', () => drive('disarm', 'Space', {disarmed: true}));
  await check('loopback_only', async () => expect(external).toEqual([]));
  await check('no_browser_errors', async () => expect(errors).toEqual([]));
  observations.browser_version = browser.version();
} catch (error) {
  observations.failure = String(error.stack || error);
  if (page) await evidence('failure').catch(() => {});
} finally {
  if (context) await context.tracing.stop({path: `${output}/trace.zip`}).catch(() => {});
  if (browser) await browser.close();
  const qualified = required.every(key => assertions[key] === true);
  fs.writeFileSync(`${output}/browser.json`, JSON.stringify({qualified, required_assertions: assertions, observations, requests, errors, external}, null, 2));
  process.exitCode = qualified ? 0 : 1;
}
"""


class DelayCommandResponse:
    """Latency injection only: forward the real app's status, headers and body."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def delayed_send(message):
            if (scope["type"] == "http" and scope["path"] in ("/api/v1/commands", "/api/v1/paper/status") and message["type"] == "http.response.start"):
                print(f"DELAYED_COMMAND status={message['status']}", flush=True)
                await asyncio.sleep(2)
            await send(message)
        await self.app(scope, receive, delayed_send)


def serve() -> int:
    # Third-party/backend imports live only in the sync-free uv child.
    from decimal import Decimal

    import uvicorn
    from krellbot import config
    from krellbot.api.app import create_app

    home = Path(os.environ["KRELLBOT_HOME"])
    config.save_config(home, config.Config(armed=[config.ArmedPack(
        pack_path="LOCAL-INLINE-STOP-BUSY-FIXTURE.json", pack_sha256="local-runtime-fixture",
        pack_id="LOCAL-INLINE-STOP-BUSY-FIXTURE", pack_version="1.0.0", venue="kraken",
        pair="SUIUSD", cap=Decimal("25"), stop=Decimal("1"), mode="paper",
        starting_cash=Decimal("1000"), requires_license=False, armed_at_ts=int(time.time()),
    )]))
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    # Match the production launcher's single pre-bound loopback socket and real
    # app factory; only response transmission latency is added by this harness.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        port = sock.getsockname()[1]
        app = create_app(home, port=port, bootstrap_token=secrets.token_urlsafe(32),
                         dist_dir=ROOT / "frontend" / "dist")
        server = uvicorn.Server(uvicorn.Config(DelayCommandResponse(app), log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        try:
            thread.start()
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("real backend failed readiness")
                time.sleep(0.02)
            print(f"RUNTIME_URL=http://127.0.0.1:{port}/", flush=True)
            stopped.wait(timeout=180)
        finally:
            server.should_exit = True
            thread.join(timeout=5)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        return serve()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()
    output = (args.output_dir or ROOT / "tests_tmp" / "editor-inline-stop-commands-busy" / f"{sha[:12]}-{time.time_ns()}").resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    (output / "browser.mjs").write_text(BROWSER)
    source_files = [
        "frontend/src/features/strategies/EditorInlineStopControl.tsx",
        "frontend/src/features/strategies/EditorInlineStopControl.busy.test.tsx",
        "frontend/src/features/strategies/EditorInlineStopControl.signal.css",
        "scripts/verify_editor_inline_stop_commands_busy.py",
    ]
    summary = {
        "source_sha": sha, "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, timeout=10)),
        "source_hashes": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_files
        },
        "platform": sys.platform, "qualified": False, "commands": [],
        "isolated_home": True, "live_enabled": False,
        "qualification_scope": "Linux Chromium local journey only; not CI, platform or operator acceptance",
        "limits": [
            "Native Chromium clears focus when disabled becomes true; pre-activation focus and busy attributes on the same button are verified separately.",
            "Successful disarm retains disabled row buttons and unmounts Refresh/Apply; no status re-read on that existing path.",
            "Refresh is one GET, not a POST. No reason field exists; empty New stop remains disabled.",
            "DOM/live semantics verified, not audible screen-reader speech.",
        ],
        "failure_modes": "real domain refusals and 2s ASGI response latency; no replacement responses or request interception",
        "invocation": [sys.executable, "scripts/verify_editor_inline_stop_commands_busy.py"],
        "fixture_scope": "fresh isolated home; clearly labelled LOCAL-INLINE-STOP-BUSY-FIXTURE persisted paper record, no ticks or orders",
        "required_assertions": dict.fromkeys(REQUIRED, False),
        "output_dir": str(output),
    }
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH") if key in os.environ}
    env["PYTHONPATH"] = str(ROOT / "src")
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

    def run(name: str, argv: list[str], cwd: Path, *, stdin: str | None = None) -> int:
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
                child.communicate(input=stdin, timeout=180)
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
        specs = ["EditorInlineStopControl.busy", "Editor", "EditorInlineStopControl",
                 "EditorInlineStopControl.signal", "EditorInlineStopControl.persist",
                 "EditorInlineStopControl.postArmRefresh", "EditorInlineStopControl.raiseStop",
                 "EditorInlineStopControl.refreshSignal"]
        if run("frontend-harness", ["npm", "run", "test:unit", "--", "--run", *[
            f"src/features/strategies/{name}.test.tsx" for name in specs
        ]], ROOT / "frontend") != 0:
            raise RuntimeError("frontend control harness failed")
        if run("build", ["npm", "run", "build"], ROOT / "frontend") != 0:
            raise RuntimeError("current frontend build failed")
        with tempfile.TemporaryDirectory(prefix="krellbot-inline-stop-busy-home-") as fresh_home:
            env["KRELLBOT_HOME"] = fresh_home
            argv = ["uv", "run", "--no-project", "--no-sync", "--python", sys.executable,
                    str(Path(__file__).resolve()), "--serve"]
            backend_record = {"name": "backend", "argv": argv, "cwd": str(ROOT), "exit_code": None}
            summary["commands"].append(backend_record)
            with (output / "backend.log").open("w") as log:
                process = subprocess.Popen(
                    argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=os.name == "posix",
                )
                try:
                    deadline = time.monotonic() + 20
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
                    env["INLINE_BUSY_CONFIG"] = json.dumps({
                        "url": url, "output": str(output), "required": REQUIRED, "home": fresh_home,
                        "executable": shutil.which("chromium") or shutil.which("chromium-browser"),
                    })
                    exit_code = run("browser", ["node", "--input-type=module"], ROOT / "frontend", stdin=BROWSER)
                    result_path = output / "browser.json"
                    if result_path.exists():
                        result = json.loads(result_path.read_text())
                        summary["required_assertions"] = result["required_assertions"]
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
