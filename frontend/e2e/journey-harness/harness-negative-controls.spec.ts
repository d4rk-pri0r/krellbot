import { test, expect, chromium } from "@playwright/test";
import { createServer } from "node:http";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { attachNetworkGuard, assertNoOffLoopback } from "./network-guard";
import { attachCommandLog, assertNoLiveOrderCommands } from "./command-log";
import { createSharedCommandLog, runGuardedCli, sanitizedJourneyEnv } from "./spawn-layer";

// These are negative controls, not product scenarios. All test-server traffic
// is physically loopback; the deliberately non-loopback hostname is mapped
// to 127.0.0.1 before the browser starts. No internet request can escape even
// when testing the old, broken guard implementation.
async function localTrap() {
  const requests: string[] = [];
  const server = createServer((req, res) => {
    requests.push(`${req.method} ${req.url}`);
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.end("local guard control");
  });
  server.on("upgrade", (_req, socket) => { requests.push("WEBSOCKET"); socket.destroy(); });
  await new Promise<void>((done) => server.listen(0, "127.0.0.1", done));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("missing local port");
  const browser = await chromium.launch({ args: ["--host-resolver-rules=MAP blocked.invalid 127.0.0.1", "--no-proxy-server"] });
  const context = await browser.newContext({ serviceWorkers: "block" });
  const page = await context.newPage();
  return { requests, page, port: address.port, close: async () => {
    await browser.close();
    server.closeAllConnections();
    await new Promise<void>((done) => server.close(() => done()));
  }};
}

test("safety: browser outbound HTTP is blocked before initial navigation", async () => {
  const trap = await localTrap();
  try {
    const guard = await attachNetworkGuard(trap.page);
    await trap.page.goto(`http://blocked.invalid:${trap.port}/outbound`).catch(() => undefined);
    expect(trap.requests).toEqual([]);
    expect(() => assertNoOffLoopback(guard)).toThrow(/non-loopback/);
  } finally { await trap.close(); }
});

test("safety: browser outbound WebSocket never reaches a server", async () => {
  const trap = await localTrap();
  try {
    const guard = await attachNetworkGuard(trap.page);
    await trap.page.goto(`http://127.0.0.1:${trap.port}/`);
    trap.requests.length = 0;
    await trap.page.evaluate((url) => new Promise<void>((done) => {
      const ws = new WebSocket(url); ws.onerror = () => done(); ws.onclose = () => done();
      setTimeout(done, 1000);
    }), `ws://blocked.invalid:${trap.port}/outbound`);
    expect(trap.requests.filter((r) => r === "WEBSOCKET")).toEqual([]);
    expect(() => assertNoOffLoopback(guard)).toThrow(/non-loopback/);
  } finally { await trap.close(); }
});

test("safety: live HTTP command is refused before send", async () => {
  const trap = await localTrap();
  try {
    const log = await attachCommandLog(trap.page);
    await trap.page.goto(`http://127.0.0.1:${trap.port}/`);
    trap.requests.length = 0;
    await trap.page.evaluate(() => fetch("/api/v1/commands", {
      method: "POST", headers: {"content-type": "application/json"},
      body: JSON.stringify({command: "live.order", args: {mode: "live"}}),
    }).then(() => undefined).catch(() => undefined));
    expect(trap.requests.filter((r) => r.includes("/api/v1/commands"))).toEqual([]);
    expect(() => assertNoLiveOrderCommands(log)).toThrow(/live-order/);
  } finally { await trap.close(); }
});

test("safety: live argv forms are refused before spawning harmless code", () => {
  const home = mkdtempSync(join(tmpdir(), "journey-argv-control-"));
  mkdirSync(join(home, "support"));
  const commandLog = createSharedCommandLog(home);
  try {
    for (const flag of ["--live", "--mode=live", "--live=true", "trade"]) {
      expect(() => runGuardedCli(["-c", "print('harmless sentinel')", flag], {home, commandLog})).toThrow(/refused/);
    }
    expect(commandLog.commands).toEqual([]);
  } finally { rmSync(home, {recursive: true, force: true}); }
});

test("safety: Python IPv6 and DNS refusals precede OS calls", () => {
  const home = mkdtempSync(join(tmpdir(), "journey-python-control-"));
  mkdirSync(join(home, "support"));
  const commandLog = createSharedCommandLog(home);
  const guardPath = resolve("e2e/journey-harness/python-socket-guard.py");
  const code = `import importlib.util, socket\ndef forbidden(*args, **kwargs):\n    raise AssertionError('OS_CALL_REACHED')\nsocket.socket.connect = forbidden\nsocket.getaddrinfo = forbidden\nspec = importlib.util.spec_from_file_location('control_guard', ${JSON.stringify(guardPath)})\nguard = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(guard)\nguard.install()\nfor call in (lambda: socket.socket(socket.AF_INET6).connect(('2001:db8::1',443,0,0)), lambda: socket.getaddrinfo('blocked.invalid',443)):\n    try:\n        call()\n    except guard.GuardRefusal:\n        pass\n    else:\n        raise AssertionError('guard did not refuse')\nprint('refused before OS')\n`;
  try {
    const result = runGuardedCli(["-c", code], {home, commandLog});
    expect(result.status, result.stderr).toBe(0);
    expect(result.stdout).toContain("refused before OS");
    expect(commandLog.netGuardRefusals()).toHaveLength(2);
  } finally { rmSync(home, {recursive: true, force: true}); }
});

test("safety: fake keyring and disabled live mode survive sanitization", () => {
  const old = process.env.krellbot_kraken_keyfile;
  process.env.krellbot_kraken_keyfile = "synthetic-control-not-a-key";
  try {
    const env = sanitizedJourneyEnv("/owned/control-home");
    expect(env.krellbot_kraken_keyfile).toBeUndefined();
    expect(env.KRELLBOT_ENABLE_LIVE).toBe("0");
    expect(env.PYTHON_KEYRING_BACKEND).toBe("tests.fakes.fake_keyring.FakeKeyring");
  } finally {
    if (old === undefined) delete process.env.krellbot_kraken_keyfile;
    else process.env.krellbot_kraken_keyfile = old;
  }
});
