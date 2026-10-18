#!/usr/bin/env python3
"""Exercise the mounted palette with the real loopback backend and Chromium.

Run with uv run --frozen python scripts/verify_palette_keyshortcuts.py.
Artifacts default to a fresh private temporary directory. DOM/AX evidence does
not qualify audible screen-reader output, macOS, or Windows.
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
REQUIRED = (
    "session_bootstrap_csrf", "tab_reaches_trigger", "trigger_shortcuts",
    "visible_glyph_unchanged", "ctrl_k_opens", "dialog_escape_shortcut",
    "hint_unchanged", "input_focus", "escape_closes_returns_focus",
    "meta_k_opens", "enter_opens", "ax_shortcuts", "loopback_only",
    "no_trading_requests", "no_new_browser_or_api_errors", "live_disabled_unarmed",
)
SERVER = r'''
import os, signal, threading
from pathlib import Path
from krellbot import config
from krellbot.api.serve import WorkstationServer
home = Path(os.environ['KRELLBOT_HOME'])
assert os.environ['KRELLBOT_ENABLE_LIVE'] == '0'
assert not config.load_config(home).armed
stopped = threading.Event()
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda *_: stopped.set())
server = WorkstationServer(home, dist_dir=Path(os.environ['FRONTEND_DIST']))
try:
    server.start()
    print('RUNTIME_URL=' + server.url, flush=True)
    stopped.wait(timeout=150)
finally:
    server.stop()
assert not config.load_config(home).armed
print('LIVE_DISABLED_UNARMED', flush=True)
'''
BROWSER = r'''
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require = createRequire(process.env.FRONTEND_PACKAGE);
const {chromium, expect} = require('@playwright/test');
const [url, out] = process.argv.slice(2);
const results = {}, observations = {}, requests = [], errors = [], apiErrors = [];
let browser, context, page;
const id = name => page.getByTestId(name);
async function check(name, action) { await action(); results[name] = true; }
async function ax(name, role, accessibleName, shortcut) {
  const cdp = await context.newCDPSession(page);
  try {
    const tree = await cdp.send('Accessibility.getFullAXTree');
    fs.writeFileSync(`${out}/${name}-ax.json`, JSON.stringify(tree, null, 2));
    const node = tree.nodes.find(n => !n.ignored && n.role?.value === role && n.name?.value === accessibleName);
    expect(node?.properties?.find(p => p.name === 'keyshortcuts')?.value.value).toBe(shortcut);
  } finally { await cdp.detach(); }
}
try {
  browser = await chromium.launch({headless:true, timeout:20000,
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath:process.env.CHROMIUM_EXECUTABLE} : {})});
  observations.browser_version = browser.version();
  observations.executable = process.env.CHROMIUM_EXECUTABLE || 'Playwright bundled Chromium';
  context = await browser.newContext({viewport:{width:1280,height:900}});
  await context.tracing.start({screenshots:true, snapshots:true, sources:false});
  page = await context.newPage();
  page.setDefaultTimeout(8000);
  page.setDefaultNavigationTimeout(15000);
  page.on('pageerror', e => errors.push(String(e)));
  page.on('request', r => requests.push({origin:new URL(r.url()).origin,
    path:new URL(r.url()).pathname, method:r.method()}));
  page.on('response', r => {
    if (new URL(r.url()).pathname.startsWith('/api/') && r.status() >= 400)
      apiErrors.push({path:new URL(r.url()).pathname, status:r.status()});
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
  const trigger = id('kbot-shell-palette-hint'), dialog = id('command-palette');
  await check('tab_reaches_trigger', async () => {
    for (let i=0; i<60; i++) {
      if (await trigger.evaluate(el => el === document.activeElement)) break;
      await page.keyboard.press('Tab');
    }
    await expect(trigger).toBeFocused();
    await expect(trigger).toHaveAccessibleName('Open command palette');
  });
  await check('trigger_shortcuts', () => expect(trigger).toHaveAttribute('aria-keyshortcuts', 'Control+K Meta+K'));
  await check('visible_glyph_unchanged', async () => {
    const keys = trigger.locator('.kbot-shell__palette-keys');
    await expect(keys).toBeVisible();
    expect(await keys.textContent()).toBe('⌘K');
    await expect(keys).toHaveAttribute('aria-hidden', 'true');
  });
  observations.trigger_html = await trigger.evaluate(el => el.outerHTML);
  await page.screenshot({path:`${out}/trigger-focused.png`});
  await ax('trigger', 'button', 'Open command palette', 'Control+K Meta+K');
  await check('ctrl_k_opens', async () => {
    await page.keyboard.press('Control+k');
    await expect(dialog).toBeVisible();
  });
  await check('dialog_escape_shortcut', () => expect(dialog).toHaveAttribute('aria-keyshortcuts', 'Escape'));
  await check('hint_unchanged', async () => {
    expect(await dialog.locator('.kbot-shell__palette-hint').textContent()).toBe('Press Esc to close · Ctrl+K from anywhere');
  });
  await check('input_focus', () => expect(page.locator('#kbot-palette-input')).toBeFocused());
  observations.dialog_html = await dialog.evaluate(el => el.outerHTML);
  await page.screenshot({path:`${out}/palette-open.png`});
  await check('ax_shortcuts', () => ax('dialog', 'dialog', 'Command palette', 'Escape'));
  await check('escape_closes_returns_focus', async () => {
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
  await check('meta_k_opens', async () => {
    await page.keyboard.press('Meta+k');
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAttribute('aria-keyshortcuts', 'Escape');
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
  await check('enter_opens', async () => {
    await page.keyboard.press('Enter');
    await expect(dialog).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
  await page.screenshot({path:`${out}/closed-focus-returned.png`});
  await check('loopback_only', async () => expect(requests.every(r => r.origin === new URL(url).origin)).toBe(true));
  await check('no_trading_requests', async () => {
    expect(requests.filter(r => r.method !== 'GET').map(r => [r.method,r.path])).toEqual([['POST','/api/v1/session/bootstrap']]);
  });
  await check('no_new_browser_or_api_errors', async () => {
    expect(errors).toEqual([]);
    // The frozen production sources also return this startup read's 403.
    expect(apiErrors.filter(e => !(e.path === '/api/v1/operations' && e.status === 403))).toEqual([]);
  });
} catch (error) {
  observations.failure = String(error.stack || error);
} finally {
  if (page) await page.screenshot({path:`${out}/final.png`}).catch(() => {});
  if (context) await context.tracing.stop({path:`${out}/trace.zip`}).catch(() => {});
  if (browser) await browser.close();
  fs.writeFileSync(`${out}/browser.json`, JSON.stringify({results, observations, requests, errors, apiErrors}, null, 2));
  process.exitCode = observations.failure ? 1 : 0;
}
'''


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


def clean_env(home: Path) -> dict[str, str]:
    names = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "USERPROFILE",
             "LOCALAPPDATA", "PLAYWRIGHT_BROWSERS_PATH")
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update(KRELLBOT_HOME=str(home), KRELLBOT_ENABLE_LIVE="0", PYTHONUNBUFFERED="1",
               PYTHONPATH=str(ROOT / "src"), FRONTEND_PACKAGE=str(FRONTEND / "package.json"),
               FRONTEND_DIST=str(FRONTEND / "dist"))
    executable = shutil.which("chromium") or shutil.which("chromium-browser")
    if executable:
        env["CHROMIUM_EXECUTABLE"] = executable
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="palette-keyshortcuts-"))
    if out.is_relative_to(ROOT):
        parser.error("output directory must be outside the checkout")
    out.mkdir(parents=True, mode=0o700, exist_ok=True)
    summary = {"qualified": False, "required_assertions": dict.fromkeys(REQUIRED, False),
               "platform": platform.platform(), "commands": [], "output_dir": str(out),
               "invocation": ["uv", "run", "--frozen", "python", "scripts/verify_palette_keyshortcuts.py"],
               "limits": "Actual host Chromium DOM/AX only; no audible AT, Windows or macOS qualification",
               "inherited_api_debt": "Startup GET /api/v1/operations 403 reproduced with frozen base production bytes; retained, not fixed or whole-shell qualification"}

    def launch(argv, cwd, env, log, timeout):
        record = {"argv": argv, "cwd": str(cwd), "log": str(log), "timeout_seconds": timeout}
        summary["commands"].append(record)
        with log.open("w") as stream:
            child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream,
                                     stderr=subprocess.STDOUT, start_new_session=os.name == "posix")
        record["pid"] = child.pid
        return child, record

    def run(argv, cwd, env, log, timeout):
        child, record = launch(argv, cwd, env, log, timeout)
        try:
            return child.wait(timeout=timeout)
        finally:
            stop(child)
            record.update(exit=child.returncode, reaped=child.poll() is not None)

    try:
        for key, argv in (("source_sha", ["git", "rev-parse", "HEAD"]),
                          ("source_status", ["git", "status", "--porcelain"])):
            summary[key] = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                                          check=True, timeout=10).stdout.strip()
        sources = ("frontend/src/shell/WorkstationShell.tsx", "frontend/src/shell/CommandPalette.tsx",
                   "frontend/src/shell/WorkstationShell.paletteKeyshortcuts.test.tsx",
                   "scripts/verify_palette_keyshortcuts.py")
        summary["source_hashes"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources}
        journey = out / "journey.mjs"
        journey.write_text(BROWSER)
        with tempfile.TemporaryDirectory(prefix="krellbot-palette-home-") as temp:
            home = Path(temp)
            env = clean_env(home)
            assert run(["npm", "run", "build"], FRONTEND, env, out / "build.log", 240) == 0, "build failed"
            backend, record = launch([sys.executable, "-c", SERVER], ROOT, env, out / "backend.log", 150)
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
                summary["loopback_url"] = url
                code = run(["node", str(journey), url, str(out)], ROOT, env, out / "browser.log", 110)
                data = json.loads((out / "browser.json").read_text())
                for name in REQUIRED:
                    summary["required_assertions"][name] = data["results"].get(name) is True
                summary["browser_evidence"] = str(out / "browser.json")
                summary["observed_api_errors"] = data["apiErrors"]
                assert code == 0, data["observations"].get("failure", "browser failed")
            finally:
                stop(backend)
                record.update(exit=backend.returncode, reaped=backend.poll() is not None)
            summary["required_assertions"]["live_disabled_unarmed"] = (
                env["KRELLBOT_ENABLE_LIVE"] == "0" and
                "LIVE_DISABLED_UNARMED" in (out / "backend.log").read_text())
        summary["qualified"] = all(summary["required_assertions"].values()) and all(
            c["exit"] == 0 and c["reaped"] for c in summary["commands"])
    except Exception:
        summary["failure"] = traceback.format_exc()
    finally:
        summary["exit_code"] = 0 if summary["qualified"] else 1
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps({"qualified": summary["qualified"], "artifact": str(out / "summary.json"),
                          "failure": summary.get("failure")}, indent=2))
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
