/** Guarded spawn/restart extension of the existing e2e workstation harness. */
import {spawn, spawnSync, type ChildProcess} from "node:child_process";
import {copyFileSync, existsSync, mkdirSync, readFileSync} from "node:fs";
import {dirname, join} from "node:path";
import {fileURLToPath} from "node:url";
import {createServer} from "node:net";
import {startWorkstationForSpec, spawnWorkstation, WORKSTATION_HARNESS_PRIMITIVES as baseline} from "../workstation-harness";
import {liveOrderFlagInArgs} from "./command-log";
export {liveOrderFlagInArgs} from "./command-log";
export const REPO_ROOT = baseline.repoRoot;
export const FRONTEND_DIR = baseline.frontendDir;
export const DIST_DIR = baseline.distDir;
const GUARD_TEMPLATE = join(dirname(fileURLToPath(import.meta.url)), "python-socket-guard.py");
const CREDENTIAL_ENV_RE = /^(KRAKEN_|COINBASE_|BINANCE_|BITFINEX_)|(^|_)KEY($|_)|SECRET|KEYFILE|PASSPHRASE|TOKEN|PASSWORD|CREDENTIAL/i;

export function sanitizedJourneyEnv(home: string, inherited: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  for (const [name, value] of Object.entries(inherited)) if (!CREDENTIAL_ENV_RE.test(name)) env[name] = value;
  return {...env, KRELLBOT_HOME: home, HOME: home, USERPROFILE: home,
    PYTHONUNBUFFERED: "1", KRELLBOT_ENABLE_LIVE: "0",
    PYTHON_KEYRING_BACKEND: "tests.fakes.fake_keyring.FakeKeyring", PYTHONPATH: REPO_ROOT,
    KRELLBOT_JOURNEY_NET_GUARD_LOG: join(home, "support", "net-guard.log")};
}

export function venvPython(): string {
  const candidate = join(REPO_ROOT, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  if (!existsSync(candidate)) throw new Error(`Run uv sync --frozen before tests; missing ${candidate}`);
  return candidate;
}
export type SpawnedCommand = {argv: string[]; startedAt: number; exitCode: number | null; signal: string | null};
export type SharedCommandLog = {
  commands: SpawnedCommand[];
  refusedCommands: string[][];
  netGuardRefusals(): Array<Record<string, unknown>>;
  assertNoLiveOrderFlags(): void;
  assertNoNetGuardRefusals(): void;
  assertAll(): void;
};
export function createSharedCommandLog(home: string): SharedCommandLog {
  const commands: SpawnedCommand[] = [];
  const refusedCommands: string[][] = [];
  const logPath = join(home, "support", "net-guard.log");
  const netGuardRefusals = () => {
    if (!existsSync(logPath)) return [];
    return readFileSync(logPath, "utf8").split("\n").filter((s) => s.trim()).map((s) => JSON.parse(s) as Record<string, unknown>);
  };
  return {commands, refusedCommands, netGuardRefusals,
    assertNoLiveOrderFlags() {
      if (refusedCommands.length || commands.some((c) => liveOrderFlagInArgs(c.argv))) throw new Error("command log: live-order attempt refused");
    },
    assertNoNetGuardRefusals() {
      const refused = netGuardRefusals();
      if (refused.length) throw new Error(`network guard: off-loopback attempt refused: ${JSON.stringify(refused)}`);
    },
    assertAll() { this.assertNoLiveOrderFlags(); this.assertNoNetGuardRefusals(); },
  };
}
export type GuardedSpawnOptions = {home: string; commandLog: SharedCommandLog; env?: Record<string, string>; cwd?: string};
function checkedArgs(args: string[], opts: GuardedSpawnOptions): string[] {
  if (liveOrderFlagInArgs(args)) {
    opts.commandLog.refusedCommands.push([...args]);
    throw new Error(`refused to spawn live-order argv: ${args.join(" ")}`);
  }
  return [GUARD_TEMPLATE, ...args];
}
export function spawnGuardedPython(args: string[], opts: GuardedSpawnOptions): ChildProcess {
  const argv = checkedArgs(args, opts);
  const child = spawn(venvPython(), argv, {cwd: opts.cwd ?? REPO_ROOT,
    env: sanitizedJourneyEnv(opts.home, {...process.env, ...opts.env}), stdio: ["ignore", "pipe", "pipe"]});
  const record: SpawnedCommand = {argv: args, startedAt: Date.now(), exitCode: null, signal: null};
  opts.commandLog.commands.push(record);
  child.on("exit", (code, signal) => {record.exitCode = code; record.signal = signal;});
  return child;
}
export type GuardedRunResult = {stdout: string; stderr: string; status: number};
export function runGuardedCli(args: string[], opts: GuardedSpawnOptions, timeoutMs = 120_000): GuardedRunResult {
  const argv = checkedArgs(args, opts);
  const startedAt = Date.now();
  const result = spawnSync(venvPython(), argv, {cwd: opts.cwd ?? REPO_ROOT,
    env: sanitizedJourneyEnv(opts.home, {...process.env, ...opts.env}), encoding: "utf8", timeout: timeoutMs});
  opts.commandLog.commands.push({argv: args, startedAt, exitCode: result.status, signal: result.signal});
  return {stdout: result.stdout ?? "", stderr: result.stderr ?? String(result.error ?? ""), status: result.status ?? -1};
}
export type JourneyWorkstationHandle = {
  baseURL: string; homeDir: string; editCsv: string; rows100kCsv: string; commandLog: SharedCommandLog;
  child(): ChildProcess; intentionallyStopped(): boolean; restartSameHome(): Promise<string>; stop(): Promise<void>;
};
async function waitPortBindable(port: number): Promise<void> {
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    const ready = await new Promise<boolean>((done) => {
      const probe = createServer();
      probe.once("error", () => done(false));
      probe.once("listening", () => probe.close(() => done(true)));
      probe.listen({host: "127.0.0.1", port});
    });
    if (ready) return;
    await new Promise((done) => setTimeout(done, 250));
  }
  throw new Error(`Same port ${port} never became bindable; no fallback allowed`);
}
export async function startJourneyWorkstation(): Promise<JourneyWorkstationHandle> {
  let commandLog: SharedCommandLog | undefined;
  const spawnProcess = (home: string, port: number, dist: string) => {
    mkdirSync(join(home, "support"), {recursive: true});
    commandLog ??= createSharedCommandLog(home);
    return spawnGuardedPython(["-m", "krellbot", "workstation", "--port", String(port), "--dist", dist], {home, commandLog});
  };
  // Reuse its build, temp-home, CSV generation, launch and readiness logic.
  const initial = await startWorkstationForSpec({spawnProcess});
  const homeDir = initial.homeDir;
  if (!commandLog) throw new Error("guarded spawn was not invoked");
  copyFileSync(join(REPO_ROOT, "tests/fixtures/packs/sma_cross.json"), join(homeDir, "data/pack-sma-cross.json"));
  let child = initial.child;
  let stopped = false;
  const port = Number(new URL(initial.baseURL).port);
  const stop = async () => {
    stopped = true;
    if (child.exitCode === null && child.signalCode === null) {
      const exited = new Promise<void>((done) => child.once("exit", () => done()));
      child.kill("SIGINT");
      await Promise.race([exited, new Promise((done) => setTimeout(done, 500))]);
      if (child.exitCode === null && child.signalCode === null) {
        child.kill("SIGKILL");
        await Promise.race([exited, new Promise((done) => setTimeout(done, 2000))]);
      }
    }
  };
  return {...initial, commandLog, child: () => child, intentionallyStopped: () => stopped, stop,
    async restartSameHome() {
      await stop();
      await waitPortBindable(port);
      const next = await spawnWorkstation(homeDir, {port, spawnProcess});
      child = next.child;
      stopped = false;
      if (next.url !== initial.baseURL) throw new Error("restart changed workstation origin");
      return next.url;
    },
  };
}
