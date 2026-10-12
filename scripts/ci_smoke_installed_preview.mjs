// Exercise the actual standalone payload after per-user installation.
// No simulated trading, exchange credentials, billing or production state.
import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const windows = process.platform === 'win32';
const [payloadArg, evidenceArg] = process.argv.slice(2);
if (!payloadArg || !evidenceArg) throw new Error('Usage: node scripts/ci_smoke_installed_preview.mjs PAYLOAD EVIDENCE');
const payload = path.resolve(payloadArg);
const evidence = path.resolve(evidenceArg);
mkdirSync(evidence, {recursive: true});
const scratch = path.join(evidence, 'isolated user with spaces');
const extracted = path.join(scratch, 'extracted program');
const home = path.join(scratch, 'data');
mkdirSync(home, {recursive: true});
cpSync(payload, extracted, {recursive: true});
const exeName = windows ? 'krellbot.exe' : 'krellbot';
const magic = readFileSync(path.join(extracted, exeName)).subarray(0, 4);
if (windows ? magic.subarray(0, 2).toString() !== 'MZ' : magic.toString('hex') !== '7f454c46') {
  throw new Error('Payload is not the actual native executable image');
}
const report = {platform: process.platform, sourceSha: process.env.GITHUB_SHA || null, checks: [], requests: [], pageErrors: [], httpErrors: [], screenshots: [], defaultBrowserCaptureOverride: true, liveEnabled: false};
function check(name, condition) {
  report.checks.push({name, passed: !!condition});
  if (!condition) throw new Error(name);
}
function run(command, args, env) {
  // cmd.exe parses its own /c quotes; Node's normal Windows argv escaping
  // turns the doubly quoted path into a different command (a UNC-like path).
  const result = spawnSync(command, args, {env, cwd: scratch, encoding: 'utf8', timeout: 120000, windowsVerbatimArguments: windows && path.basename(command).toLowerCase() === 'cmd.exe'});
  if (result.error || result.status !== 0) throw new Error(`${command} failed: ${result.error || result.status}\n${result.stdout || ''}\n${result.stderr || ''}`);
  return result.stdout;
}
const env = {...process.env, KRELLBOT_HOME: home, KRELLBOT_ENABLE_LIVE: '0', KRELLBOT_LIVE: '0', PYTHONUNBUFFERED: '1'};
for (const key of Object.keys(env)) {
  if (/^(KRAKEN_|COINBASE_|GITHUB_TOKEN|GH_TOKEN|DISCORD_|OH_SESSION_)/.test(key)) delete env[key];
}
// Remove developer Python from PATH: the installed binary must use its runtime.
const pathKey = Object.keys(env).find(key => key.toLowerCase() === 'path') || 'PATH';
env[pathKey] = (env[pathKey] || '').split(path.delimiter).filter(entry => !/python|\.venv|setup-uv|uv-tool/i.test(entry)).join(path.delimiter);
delete env.PYTHONPATH;
let installed;
if (windows) {
  const ps = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  installed = run(ps, ['-NoProfile', '-Command', "[Environment]::GetFolderPath('LocalApplicationData')"], env).trim();
  installed = path.join(installed, 'Krellbot');
} else {
  env.HOME = scratch;
  env.XDG_DATA_HOME = path.join(scratch, '.local', 'share');
  env.XDG_CONFIG_HOME = path.join(scratch, '.config');
  installed = path.join(env.XDG_DATA_HOME, 'Krellbot');
}
function install() {
  if (windows) {
    const cmd = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'cmd.exe');
    return run(cmd, ['/d', '/s', '/c', `""${path.join(extracted, 'Install-Krellbot.cmd')}""`], env);
  }
  return run('/bin/bash', [path.join(extracted, 'install-krellbot.sh')], env);
}
let child;
let browser;
let url;
try {
  const sentinel = path.join(home, 'owner-data-sentinel.txt');
  writeFileSync(sentinel, 'preserve this isolated test data\n');
  install();
  check('Per-user native installation', existsSync(path.join(installed, exeName)));
  check('Bundled runtime installed', existsSync(path.join(installed, '_internal')));
  const hash = file => createHash('sha256').update(readFileSync(file)).digest('hex');
  check('Installed executable equals frozen payload', hash(path.join(installed, exeName)) === hash(path.join(extracted, exeName)));
  check('Install preserves data', readFileSync(sentinel, 'utf8') === 'preserve this isolated test data\n');
  install();
  check('Reinstall preserves data', readFileSync(sentinel, 'utf8') === 'preserve this isolated test data\n');
  if (windows) {
    const ps = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
    const shortcut = JSON.parse(run(ps, ['-NoProfile', '-Command', "$p=Join-Path ([Environment]::GetFolderPath('Programs')) 'Krellbot.lnk';$s=(New-Object -ComObject WScript.Shell).CreateShortcut($p);@{exists=(Test-Path -LiteralPath $p);target=$s.TargetPath;arguments=$s.Arguments;workingDirectory=$s.WorkingDirectory}|ConvertTo-Json -Compress"], env));
    check('Start-menu shortcut targets installed binary without arguments', shortcut.exists && path.resolve(shortcut.target).toLowerCase() === path.join(installed, exeName).toLowerCase() && shortcut.arguments === '');
  } else {
    check('Application launcher installed', existsSync(path.join(env.XDG_DATA_HOME, 'applications', 'krellbot.desktop')));
  }
  check('Installed version command runs without developer Python', /^0\.9\.5\s*$/.test(run(path.join(installed, exeName), ['--version'], env)));
  const capturedUrl = path.join(evidence, 'opened-url.txt');
  const captureScript = path.join(evidence, 'capture-browser.mjs');
  writeFileSync(captureScript, `import {writeFileSync} from 'node:fs'; writeFileSync(${JSON.stringify(capturedUrl)}, process.argv[2]);\n`);
  // Prevent the default browser from consuming the one-time bootstrap token.
  // Still exercise the program's real webbrowser.open call and capture its URL.
  env.BROWSER = `"${process.execPath}" "${captureScript}" %s`;
  child = spawn(path.join(installed, exeName), [], {env, cwd: scratch, stdio: ['ignore', 'pipe', 'pipe']});
  let output = '';
  url = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('No-argument installed launch did not report a loopback URL')), 30000);
    const onData = data => {
      output += data.toString();
      const match = output.match(/Workstation running at (http:\/\/127\.0\.0\.1:\d+\/)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('exit', code => { clearTimeout(timer); reject(new Error(`Installed launcher exited ${code} before readiness`)); });
  });
  report.launch = {binary: path.join(installed, exeName), argv: [], url, cwdOutsideSource: scratch, pid: child.pid};
  await expect.poll(() => existsSync(capturedUrl), {timeout: 10000}).toBe(true);
  check('Automatic browser-open dispatch receives exactly the loopback URL', readFileSync(capturedUrl, 'utf8') === url);
  browser = await chromium.launch({headless: true});
  const context = await browser.newContext({viewport: {width: 1600, height: 1000}});
  const page = await context.newPage();
  page.on('pageerror', error => report.pageErrors.push(String(error)));
  page.on('request', request => report.requests.push({method: request.method(), path: new URL(request.url()).pathname}));
  page.on('response', response => {
    if (response.status() >= 400) report.httpErrors.push({path: new URL(response.url()).pathname, status: response.status()});
  });
  // Readiness/meta/bootstrap/CSRF/Host/origin are never mocked or bypassed.
  const response = await page.goto(url);
  check('Installed shell serves HTML, not shell_not_built', response.status() === 200);
  await expect(page.getByTestId('app-home')).toBeVisible();
  await expect(page.getByTestId('app-home-card-strategies')).toBeVisible();
  check('Home clearly labels local preview and disabled live', (await page.getByTestId('app-home-availability').innerText()).includes('Live trading unavailable'));
  const navigation = page.getByTestId('kbot-nav');
  for (const [view, label] of [['strategies', 'Strategies'], ['research', 'Research'], ['studio', 'Studio'], ['workstation', 'Workstation'], ['operations', 'Operations']]) {
    await navigation.getByRole('button', {name: 'Home', exact: true}).click();
    await page.getByTestId(`app-home-card-${view}`).click();
    await expect(navigation.getByRole('button', {name: label, exact: true})).toHaveAttribute('aria-pressed', 'true');
    check(`Home card opens ${label}`, true);
  }
  await navigation.getByRole('button', {name: 'Deploy', exact: true}).click();
  await expect(navigation.getByRole('button', {name: 'Deploy', exact: true})).toHaveAttribute('aria-pressed', 'true');
  check('Deploy navigation reachable', true);
  await navigation.getByRole('button', {name: 'Home', exact: true}).click();
  await page.screenshot({path: path.join(evidence, 'installed-home-desktop.png'), fullPage: true});
  report.screenshots.push('installed-home-desktop.png');
  await page.setViewportSize({width: 390, height: 844});
  await expect(page.getByTestId('app-home-card-strategies')).toBeVisible();
  await page.getByTestId('app-home-card-strategies').focus();
  await page.keyboard.press('Enter');
  await expect(navigation.getByRole('button', {name: 'Strategies', exact: true})).toHaveAttribute('aria-pressed', 'true');
  check('Mobile keyboard navigation works', true);
  await navigation.getByRole('button', {name: 'Home', exact: true}).click();
  await page.screenshot({path: path.join(evidence, 'installed-home-mobile.png'), fullPage: true});
  report.screenshots.push('installed-home-mobile.png');
  check('No uncaught JavaScript errors', report.pageErrors.length === 0);
  check('No product commands or external requests', report.requests.every(request => request.path === '/api/v1/session/bootstrap' || request.method === 'GET'));
  await context.close();
  await browser.close();
  browser = null;
} catch (error) {
  report.failure = String(error.stack || error);
  throw error;
} finally {
  if (browser) await browser.close();
  if (child && child.exitCode === null) {
    if (windows) spawnSync('taskkill', ['/pid', String(child.pid), '/t', '/f'], {encoding: 'utf8'});
    else child.kill('SIGINT');
    await Promise.race([new Promise(resolve => child.once('exit', resolve)), new Promise(resolve => setTimeout(resolve, 10000))]);
    if (child.exitCode === null) child.kill('SIGKILL');
  }
  if (url) {
    try { await fetch(url, {signal: AbortSignal.timeout(2000)}); report.listenerClosed = false; }
    catch { report.listenerClosed = true; }
  }
  writeFileSync(path.join(evidence, 'installed-preview.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}
if (!report.listenerClosed) throw new Error('Installed launcher left its loopback listener alive after stop');
