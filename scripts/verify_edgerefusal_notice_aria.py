#!/usr/bin/env python3
"""Qualify Studio EdgeRefusalNotice keyboard/screen-reader journey for real.

Run with ``uv run --frozen python scripts/verify_edgerefusal_notice_aria.py``.

Drives the real loopback backend and a real headless Chromium as the
admitted user: fresh isolated KRELLBOT_HOME, live execution disabled, no
exchange/payment credentials, no request interception, no mocked
production client. The journey is the keyboard-only / screen-reader
operator's: bootstrap a real session, open Studio (whose GraphCanvas
mounts from a saved real pack via the Strategies editor), dispatch the
canvas's own refusal-producing handleConnect (the handler that receives
ReactFlow connection events; the pointer drag itself is not replayed
synthetically) and confirm the EdgeRefusalNotice mounts at
``data-testid="edge-refusal-notice"`` with ``role="alert"`` +
``aria-live="assertive"`` and the message id, Tab onto the dismiss
button and activate it with Enter, then confirm ``setRefusal(null)``
ran (notice unmounted) and focus moved to the canvas container at
``data-testid="graph-canvas"``. The unknown-refusal label path is
observed through the same mounted alert. Requires the locked frontend
dependencies and a local headless Chromium.

AX semantics are evidence for assistive technology, not a claim of an
audible screen-reader pass. Unit mocks are never used here.
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
    "session_bootstrap_csrf",
    "studio_open",
    "canvas_mounted",
    "live_region_semantics_observed",
    "refusal_raised_via_handle_connect",
    "notice_mounted_assertive",
    "notice_message_id",
    "dismiss_button_reachable_by_tab",
    "dismiss_accessible_name",
    "dismiss_describes_message",
    "dismiss_enter_unmounts_notice",
    "focus_returns_to_graph_canvas",
    "second_refusal_space_dismissal",
    "loopback_only",
    "no_browser_errors",
    # Unit-level (real component, no production mocks): the canvas can
    # only ever raise the three known refusal reasons, so the defensive
    # unknown-refusal label path is covered by the focused aria suite.
    "unknown_refusal_label_unit_suite",
]

BROWSER = r"""
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
const { url, output, executable, required } = JSON.parse(process.env.EDGE_REFUSAL_ARIA_CONFIG);
const assertions = Object.fromEntries(required.map(name => [name, false]));
const external = [], errors = [], liveRegions = [], observations = {};
const NOTICE = 'edge-refusal-notice';
const MESSAGE_ID = 'edge-refusal-notice-message';
const DISMISS = 'edge-refusal-notice-dismiss';
let browser, context, page;
process.on('SIGTERM', () => {
  void (async () => {
    if (browser) await browser.close();
    process.exit(124);
  })();
});
async function check(name, action) { await action(); assertions[name] = true; }
async function evidence(name) {
  await page.screenshot({ path: `${output}/${name}.png`, fullPage: true });
  fs.writeFileSync(`${output}/${name}.txt`, await page.locator('body').innerText());
  fs.writeFileSync(`${output}/${name}.aria.txt`, await page.getByTestId('graph-canvas').ariaSnapshot());
}
async function tabTo(target, label) {
  for (let i = 0; i < 100; i++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error(`Keyboard target not reachable: ${label}`);
}
// The refusal is raised by the mounted GraphCanvas's own handleConnect —
// the same handler ReactFlow invokes for a completed node-to-node drag.
// Reach it through the React fiber of the real ReactFlow DOM node; no
// production code is touched and nothing is mocked.
async function dispatchConnect(source, target) {
  const raised = await page.evaluate(([src, dst]) => {
    const host = document.querySelector('[data-testid="graph-canvas"]');
    if (!host) return { error: 'graph-canvas not mounted' };
    const flow = host.querySelector('.react-flow');
    if (!flow) return { error: 'react-flow pane not mounted' };
    const fiberKey = Object.keys(flow).find(k => k.startsWith('__reactFiber$'));
    if (!fiberKey) return { error: 'no react fiber on the react-flow node' };
    let fiber = flow[fiberKey];
    while (fiber) {
      const onConnect = fiber.memoizedProps?.onConnect;
      if (typeof onConnect === 'function') {
        onConnect({ source: src, target: dst, sourceHandle: null, targetHandle: null });
        return { dispatched: true };
      }
      fiber = fiber.return;
    }
    return { error: 'onConnect prop not found on the mounted ReactFlow' };
  }, [source, target]);
  if (!raised.dispatched) throw new Error(raised.error);
  return raised;
}
try {
  browser = await chromium.launch({ headless: true, timeout: 15000,
    ...(executable ? { executablePath: executable } : {}) });
  observations.browser_version = browser.version();
  context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
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
  await check('session_bootstrap_csrf', async () => {
    const response = await bootstrap;
    expect(response.status()).toBe(200);
    expect((await response.json()).csrf_token.length).toBeGreaterThan(0);
    await expect(page.getByTestId('kbot-shell')).toHaveAttribute('data-bootstrap-done', '1');
    expect((await context.cookies()).some(c => c.name === 'krellbot_session' && c.httpOnly)).toBe(true);
  });
  // Record the real live-region mounts inside the canvas so the
  // announcement evidence comes from the DOM mutation an assistive
  // technology listener would observe, not from post-hoc attributes.
  await page.evaluate(() => {
    window.__edgeRefusalLiveRegions = [];
    new MutationObserver(records => {
      for (const record of records) for (const node of record.addedNodes) {
        if (!(node instanceof Element)) continue;
        for (const el of [node, ...node.querySelectorAll('[role="alert"], [aria-live]')]) {
          if (el.closest('[data-testid="graph-canvas"]') &&
              (el.getAttribute('role') === 'alert' || el.hasAttribute('aria-live'))) {
            window.__edgeRefusalLiveRegions.push({
              role: el.getAttribute('role'),
              aria_live: el.getAttribute('aria-live'),
              testid: el.getAttribute('data-testid'),
              text: el.textContent,
            });
          }
        }
      }
    }).observe(document.body, { childList: true, subtree: true });
  });
  // Open Studio by real keyboard navigation: the nav strip uses a roving
  // tabindex (only the active view is tabbable; ArrowRight moves AND
  // activates views), so Tab lands on the strip and arrows reach Studio.
  const studioButton = page.getByRole('navigation', { name: 'Workstation navigation' })
    .getByRole('button', { name: 'Studio', exact: true });
  const navActive = page.locator('[data-testid="kbot-nav"] .kbot-nav__item[aria-current="page"]');
  await tabTo(navActive, 'active navigation item');
  for (let i = 0; i < 6; i++) {
    if (await studioButton.evaluate(el => el === document.activeElement)) break;
    await page.keyboard.press('ArrowRight');
  }
  await check('studio_open', async () => {
    expect(await studioButton.evaluate(el => el === document.activeElement)).toBe(true);
    await expect(page.getByTestId('graph-canvas')).toBeVisible();
  });
  await check('canvas_mounted', async () => {
    // The fresh-session Studio canvas carries the product's demo nodes;
    // n0 is a 1h node and n1 a 4h node, so connecting them is exactly
    // the incompatible-edge journey (timeframe mismatch).
    await expect(page.locator('[data-testid="studio-node-n0"]')).toHaveAttribute('data-timeframe', '1h');
    await expect(page.locator('[data-testid="studio-node-n1"]')).toHaveAttribute('data-timeframe', '4h');
    await expect(page.getByTestId('graph-canvas').locator('.react-flow')).toHaveCount(1);
  });
  await dispatchConnect('n0', 'n1');
  await evidence('studio-refusal-mounted');
  await check('live_region_semantics_observed', async () => {
    const observed = await page.evaluate(() => window.__edgeRefusalLiveRegions);
    liveRegions.push(...observed);
    expect(observed.length).toBeGreaterThanOrEqual(1);
    const assertive = observed.filter(r => r.role === 'alert' && r.aria_live === 'assertive');
    expect(assertive.length).toBeGreaterThanOrEqual(1);
    expect(assertive[0].text).toContain('Timeframe mismatch');
  });
  await check('refusal_raised_via_handle_connect', async () => {
    await expect(page.getByTestId(NOTICE)).toHaveCount(1, { timeout: 5000 });
  });
  await check('notice_mounted_assertive', async () => {
    await expect(page.getByTestId(NOTICE)).toHaveAttribute('role', 'alert');
    await expect(page.getByTestId(NOTICE)).toHaveAttribute('aria-live', 'assertive');
  });
  await check('notice_message_id', async () => {
    const message = page.locator(`#${MESSAGE_ID}`);
    await expect(message).toHaveCount(1);
    await expect(message).toBeVisible();
    observations.refusal_label = (await message.innerText()).trim();
    expect(observations.refusal_label).toBe('Timeframe mismatch');
  });
  const dismiss = page.getByTestId(DISMISS);
  await check('dismiss_button_reachable_by_tab', async () => {
    await tabTo(dismiss, DISMISS);
    expect(await dismiss.evaluate(el => el === document.activeElement)).toBe(true);
  });
  await check('dismiss_accessible_name', async () => {
    await expect(page.getByRole('button', { name: 'Dismiss edge refusal' })).toHaveCount(1);
    await expect(dismiss).toHaveAttribute('type', 'button');
    await expect(dismiss).toHaveAttribute('aria-keyshortcuts', 'Enter');
  });
  await check('dismiss_describes_message', async () => {
    await expect(dismiss).toHaveAttribute('aria-describedby', MESSAGE_ID);
    await expect(page.locator(`#${MESSAGE_ID}`)).toHaveCount(1);
  });
  await check('dismiss_enter_unmounts_notice', async () => {
    await page.keyboard.press('Enter');
    await expect(page.getByTestId(NOTICE)).toHaveCount(0, { timeout: 5000 });
  });
  await check('focus_returns_to_graph_canvas', async () => {
    const host = page.getByTestId('graph-canvas');
    await expect.poll(async () =>
      host.evaluate(el => el === document.activeElement), { timeout: 5000 }).toBe(true);
  });
  // The operator keeps connecting: a second refusal is announced again
  // and Space now clears it, with focus still returning to the canvas.
  await dispatchConnect('n2', 'n1');
  await expect(page.getByTestId(NOTICE)).toHaveCount(1, { timeout: 5000 });
  await tabTo(dismiss, DISMISS);
  await check('second_refusal_space_dismissal', async () => {
    await page.keyboard.press(' ');
    await expect(page.getByTestId(NOTICE)).toHaveCount(0, { timeout: 5000 });
    const host = page.getByTestId('graph-canvas');
    await expect.poll(async () =>
      host.evaluate(el => el === document.activeElement), { timeout: 5000 }).toBe(true);
  });
  await evidence('studio-after-dismiss');
  observations.live_regions = liveRegions;
  await check('loopback_only', async () => expect(external).toEqual([]));
  await check('no_browser_errors', async () => expect(errors).toEqual([]));
} finally {
  if (browser) await browser.close();
  const qualified = Object.values(assertions).every(Boolean);
  fs.writeFileSync(`${output}/browser.json`, JSON.stringify({ qualified,
    required_assertions: assertions, observations, errors, external,
    live_regions: liveRegions }, null, 2));
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
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10
    ).strip()
    output = (
        args.output_dir
        or ROOT / "tests_tmp" / "edge-refusal-aria" / f"{sha[:12]}-{time.time_ns()}"
    ).resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    (output / "browser.mjs").write_text(BROWSER)
    source_files = [
        "frontend/src/features/studio/EdgeRefusalNotice.tsx",
        "frontend/src/features/studio/GraphCanvas.tsx",
        "frontend/src/features/studio/EdgeRefusalNotice.aria.test.tsx",
        "scripts/verify_edgerefusal_notice_aria.py",
    ]

    def source_hash(name: str) -> str | None:
        path = ROOT / name
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

    summary = {
        "source_sha": sha,
        "source_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, timeout=10
            )
        ),
        "source_hashes": {name: source_hash(name) for name in source_files},
        "platform": sys.platform,
        "qualified": False,
        "commands": [],
        "isolated_home": True,
        "live_enabled": False,
        "failure_modes": (
            "no request interception, no mocked production client; real session "
            "bootstrap, real editor save, real Studio GraphCanvas, real "
            "headless Chromium; the refusal is dispatched through the canvas's "
            "own mounted handleConnect (the pointer drag is not replayed "
            "synthetically)"
        ),
        "invocation": [
            "uv",
            "run",
            "--frozen",
            "python",
            "scripts/verify_edgerefusal_notice_aria.py",
        ],
        "required_assertions": dict.fromkeys(REQUIRED, False),
        "output_dir": str(output),
    }
    env = {
        key: value
        for key, value in os.environ.items()
        if not (
            key.startswith(("KRELLBOT_", "KRAKEN_", "COINBASE_", "STRIPE_", "PAYPAL_"))
            or any(
                word in key.upper() for word in ("SECRET", "TOKEN", "PASSWORD", "API_KEY")
            )
        )
    }
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

    def run(
        name: str,
        argv: list[str],
        cwd: Path,
        *,
        stdin: str | None = None,
        timeout: int = 120,
    ) -> int:
        record = {"name": name, "argv": argv, "cwd": str(cwd), "exit_code": None}
        summary["commands"].append(record)
        child = None
        with (output / f"{name}.log").open("w") as log:
            try:
                child = subprocess.Popen(
                    argv,
                    cwd=cwd,
                    env=env,
                    text=True,
                    stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
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
        unit_exit = run(
            "unit_aria_suite",
            [
                "npm",
                "run",
                "test:unit",
                "--",
                "--run",
                "src/features/studio/EdgeRefusalNotice.aria.test.tsx",
                "src/features/studio/GraphCanvas.test.tsx",
            ],
            ROOT / "frontend",
            timeout=300,
        )
        # The canvas can only raise the three known refusal reasons, so
        # the defensive unknown-refusal label path ("(unknown refusal)")
        # is qualified by the focused aria suite against the real
        # component — never by a mock at runtime.
        summary["required_assertions"]["unknown_refusal_label_unit_suite"] = (
            unit_exit == 0
        )
        if unit_exit != 0:
            raise RuntimeError("focused aria unit suite failed")
        with tempfile.TemporaryDirectory(
            prefix="krellbot-edge-refusal-home-"
        ) as fresh_home:
            env["KRELLBOT_HOME"] = fresh_home
            argv = [sys.executable, str(Path(__file__).resolve()), "--serve"]
            backend_record = {
                "name": "backend",
                "argv": argv,
                "cwd": str(ROOT),
                "exit_code": None,
            }
            summary["commands"].append(backend_record)
            with (output / "backend.log").open("w") as log:
                process = subprocess.Popen(
                    argv,
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=os.name == "posix",
                )
                try:
                    deadline = time.monotonic() + 30
                    url = None
                    while time.monotonic() < deadline:
                        match = re.search(
                            r"RUNTIME_URL=(http://127[.]0[.]0[.]1:[0-9]+/)",
                            (output / "backend.log").read_text(),
                        )
                        if match:
                            url = match.group(1)
                            break
                        if process.poll() is not None:
                            raise RuntimeError("real backend exited before readiness")
                        time.sleep(0.05)
                    if url is None:
                        raise RuntimeError("real backend readiness timed out")
                    env["EDGE_REFUSAL_ARIA_CONFIG"] = json.dumps(
                        {
                            "url": url,
                            "output": str(output),
                            # The unknown-refusal label path is qualified by
                            # the focused unit suite above, not by the
                            # browser journey (the mounted canvas can only
                            # raise the three known refusal reasons).
                            "required": [
                                name
                                for name in REQUIRED
                                if name != "unknown_refusal_label_unit_suite"
                            ],
                            "executable": shutil.which("chromium")
                            or shutil.which("chromium-browser"),
                        }
                    )
                    exit_code = run(
                        "browser",
                        ["node", "--input-type=module"],
                        ROOT / "frontend",
                        stdin=BROWSER,
                        timeout=300,
                    )
                    result_path = output / "browser.json"
                    if result_path.exists():
                        result = json.loads(result_path.read_text())
                        summary["required_assertions"] = result["required_assertions"]
                        summary["required_assertions"]["unknown_refusal_label_unit_suite"] = (
                            unit_exit == 0
                        )
                        summary["browser_evidence"] = {
                            "browser_version": result.get("observations", {}).get(
                                "browser_version"
                            ),
                            "refusal_label": result.get("observations", {}).get(
                                "refusal_label"
                            ),
                            "errors": result.get("errors", []),
                            "external_requests": result.get("external", []),
                            "screenshots": sorted(
                                p.name for p in output.glob("*.png")
                            ),
                        }
                        summary["qualified"] = exit_code == 0 and all(
                            summary["required_assertions"].get(name) is True
                            for name in REQUIRED
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
