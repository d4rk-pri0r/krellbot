#!/usr/bin/env python3
"""Check repeat preflight submissions in Chromium against the real loopback shell.

Build frontend first. HTTP/network failures are explicitly injected at the browser
transport boundary; successful and refused verdicts come from the real dry-run API.
Artifacts contain screenshots and assertions, never session tokens or credentials.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

from krellbot.api.serve import WorkstationServer

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "bootstrap", "sandbox_success", "pending_flush", "fresh_refusal",
    "refusal_flush", "HTTP_failure", "network_failure", "retry_clears_error",
    "mobile_keyboard", "mobile_touch_targets", "live_disabled", "request_contract", "loopback_only",
    "no_browser_errors",
]

BROWSER = r"""
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
const { url, output, executable } = JSON.parse(process.env.PREFLIGHT_VERIFY_CONFIG);
const assertions = {}, requests = [], errors = [], external = [];
let browser, page, release, arrived, pending;
const id = name => page.getByTestId(`live-preflight-${name}`);
async function check(name, action) { await action(); assertions[name] = true; }
async function fill(account, revision, mode) {
  await id('account').fill(account);
  await id('revision').fill(revision);
  await id('mode').selectOption(mode);
}
async function runSuccess(revision) {
  await fill('sandbox-default', revision, 'sandbox');
  await id('submit').click();
  await expect(id('result')).toContainText('ok: true');
  await expect(id('result')).toContainText(`revision_id: ${revision}`);
  await expect(id('submit')).toBeEnabled();
}
async function hold(kind) {
  pending = new Promise(resolve => { arrived = resolve; });
  const held = new Promise(resolve => { release = resolve; });
  await page.route('**/api/v1/commands', async route => {
    arrived();
    await held;
    if (kind === 'HTTP') await route.fulfill({status: 503, body: 'Injected verifier outage'});
    else if (kind === 'network') await route.abort('failed');
    else await route.fulfill({response: await route.fetch()});
  }, {times: 1});
}
async function expectPending() {
  await pending;
  await expect(id('submit')).toBeDisabled();
  await expect(id('result')).toHaveCount(0);
  await expect(id('error')).toHaveCount(0);
  await page.waitForTimeout(150);
  await expect(id('result')).toHaveCount(0);
}
try {
  browser = await chromium.launch({headless: true, ...(executable ? {executablePath: executable} : {})});
  const context = await browser.newContext({viewport: {width: 1280, height: 900}});
  await context.route('**/*', route => {
    if (new URL(route.request().url()).origin !== new URL(url).origin) {
      external.push(route.request().url());
      return route.abort();
    }
    return route.continue();
  });
  page = await context.newPage();
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => {
    if (request.method() !== 'GET') requests.push({
      path: new URL(request.url()).pathname, method: request.method(),
      csrf: Boolean(request.headers()['x-krellbot-csrf']),
      body: request.url().endsWith('/commands') ? request.postDataJSON() : null,
    });
  });
  const bootstrap = page.waitForResponse(r => r.url().endsWith('/api/v1/session/bootstrap'));
  await page.goto(url);
  await check('bootstrap', async () => {
    expect((await bootstrap).status()).toBe(200);
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
    expect((await context.cookies()).some(c => c.name === 'krellbot_session' && c.httpOnly)).toBe(true);
  });
  const nav = page.getByRole('navigation', {name: 'Workstation navigation'});
  await nav.getByRole('button', {name: 'Deploy', exact: true}).focus();
  await page.keyboard.press('Enter');
  await expect(id('panel')).toBeVisible();
  await check('sandbox_success', () => runSuccess('local-old-revision'));
  await page.screenshot({path: `${output}/initial-success.png`, fullPage: true});

  await fill('local-new-account', 'local-new-revision', 'live');
  await hold('real');
  await id('submit').click();
  await check('pending_flush', expectPending);
  await page.screenshot({path: `${output}/pending.png`, fullPage: true});
  release();
  await check('fresh_refusal', async () => {
    await expect(id('result')).toContainText('code: Account mismatch');
    await expect(id('result')).toContainText('ok: false');
    await expect(id('result')).toContainText('account_id: local-new-account');
    await expect(id('result')).toContainText('revision_id: local-new-revision');
    await expect(id('result')).not.toContainText('local-old-revision');
    await expect(id('error')).toHaveCount(0);
    await expect(id('submit')).toBeEnabled();
  });
  await page.screenshot({path: `${output}/fresh-refusal.png`, fullPage: true});
  await hold('real');
  await fill('sandbox-default', 'local-refusal-retry', 'sandbox');
  await id('submit').click();
  await check('refusal_flush', expectPending);
  release();
  await expect(id('result')).toContainText('ok: true');

  for (const kind of ['HTTP', 'network']) {
    await runSuccess(`local-before-${kind}`);
    await fill(`local-failure-${kind}`, `local-failure-revision-${kind}`, 'live');
    await hold(kind);
    await id('submit').click();
    await expectPending();
    release();
    await check(`${kind}_failure`, async () => {
      await expect(id('error')).toHaveText('Preflight request failed');
      await expect(id('result')).toHaveCount(0);
      await expect(id('submit')).toBeEnabled();
    });
    await page.screenshot({path: `${output}/${kind}-failure.png`, fullPage: true});
    await hold('real');
    await fill('sandbox-default', `local-after-${kind}`, 'sandbox');
    await id('submit').click();
    await expectPending();
    release();
    await check('retry_clears_error', async () => {
      await expect(id('result')).toContainText(`revision_id: local-after-${kind}`);
      await expect(id('error')).toHaveCount(0);
    });
  }
  await check('mobile_keyboard', async () => {
    await page.setViewportSize({width: 390, height: 844});
    await fill('sandbox-default', 'local-mobile-live', 'live');
    await id('mode').focus();
    await page.keyboard.press('Tab');
    await expect(id('submit')).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(id('result')).toContainText('code: Mode not sandbox');
    await expect(id('result')).toContainText('revision_id: local-mobile-live');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path: `${output}/mobile-live-refusal.png`, fullPage: true});
  });
  await check('live_disabled', async () => {
    const state = await page.evaluate(async () => (await fetch('/api/v1/operations')).json());
    expect(state.live.live_enabled).toBe(false);
    expect(state.deployments).toEqual([]);
  });
  await check('request_contract', async () => {
    const commands = requests.filter(r => r.path === '/api/v1/commands');
    expect(commands.length).toBe(10);
    for (const r of commands) {
      expect(r.method).toBe('POST');
      expect(r.csrf).toBe(true);
      expect(r.body.schema_version).toBe('1');
      expect(r.body.command).toBe('live.preflight');
      expect(Object.keys(r.body).sort()).toEqual(['command', 'payload', 'schema_version']);
    }
    expect(commands[1].body.payload).toEqual({account_id: 'local-new-account', revision_id: 'local-new-revision', mode: 'live'});
    expect(requests.every(r => ['/api/v1/session/bootstrap', '/api/v1/commands'].includes(r.path))).toBe(true);
  });
  await check('loopback_only', async () => expect(external).toEqual([]));
  await check('no_browser_errors', async () => expect(errors).toEqual([]));
  await check('mobile_touch_targets', async () => {
    const heights = {};
    for (const name of ['account', 'revision', 'mode', 'submit']) {
      heights[name] = (await id(name).boundingBox()).height;
    }
    fs.writeFileSync(`${output}/mobile-control-heights.json`, JSON.stringify(heights, null, 2));
    for (const height of Object.values(heights)) expect(height).toBeGreaterThanOrEqual(44);
  });
} catch (error) {
  errors.push(String(error.stack || error));
  process.exitCode = 1;
} finally {
  if (release) release();
  if (browser) await browser.close();
  fs.writeFileSync(`${output}/browser.json`, JSON.stringify({assertions, requests, errors, external}, null, 2));
}
"""


def main() -> int:
    output = Path(tempfile.mkdtemp(prefix="krellbot-preflight-evidence-"))
    summary = {"source_sha": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
    ).strip(), "required_assertions": dict.fromkeys(REQUIRED, False),
        "qualified": False, "output_dir": str(output),
        "failure_injection": "Browser-only HTTP 503 and network abort; real backend verdicts otherwise"}
    server = None
    try:
        for key in list(os.environ):
            if key.startswith(("KRELLBOT_", "KRAKEN_", "COINBASE_")):
                del os.environ[key]
        os.environ["KRELLBOT_ENABLE_LIVE"] = "0"
        with tempfile.TemporaryDirectory(prefix="krellbot-preflight-home-") as home:
            os.environ["KRELLBOT_HOME"] = home
            server = WorkstationServer(Path(home), dist_dir=ROOT / "frontend" / "dist")
            server.start()
            env = os.environ.copy()
            env["PREFLIGHT_VERIFY_CONFIG"] = json.dumps({
                "url": server.url, "output": str(output),
                "executable": shutil.which("chromium") or shutil.which("chromium-browser"),
            })
            with (output / "browser.log").open("w") as log:
                result = subprocess.run(
                    ["node", "--input-type=module"], input=BROWSER, text=True,
                    cwd=ROOT / "frontend", env=env, stdout=log, stderr=subprocess.STDOUT,
                    timeout=120, check=False,
                )
            summary["browser_exit"] = result.returncode
            browser = json.loads((output / "browser.json").read_text())
            summary["required_assertions"].update(browser["assertions"])
            summary["qualified"] = result.returncode == 0 and all(
                summary["required_assertions"].get(name) is True for name in REQUIRED
            )
            server.stop()
            server = None
    except Exception:
        summary["failure"] = traceback.format_exc()
    finally:
        if server is not None:
            server.stop()
        summary["exit_code"] = 0 if summary["qualified"] else 1
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
    return summary["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
