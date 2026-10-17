/**
 * Per-spec workstation harness.
 *
 * The bootstrap token is server-side one-shot: only the first call
 * to ``/api/v1/session/bootstrap`` succeeds on a given workstation.
 * Because Playwright spins a fresh browser context per test, two
 * spec files that share one workstation can never both bootstrap.
 *
 * This module lets each spec file own its own workstation: call
 * ``startWorkstationForSpec()`` in ``test.beforeAll`` and
 * ``stopWorkstationForSpec()`` in ``test.afterAll``. The fixture
 * CSVs are generated once per spec under a fresh temp ``KRELLBOT_HOME``
 * so tests stay isolated.
 */

import {
  spawn,
  spawnSync,
  type ChildProcess,
} from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createCsv } from "./fixtures";

const REPO_ROOT = resolve(fileURLToPath(import.meta.url), "../../..");
const FRONTEND_DIR = join(REPO_ROOT, "frontend");
const DIST_DIR = join(FRONTEND_DIR, "dist");

export type WorkstationHandle = {
  baseURL: string;
  homeDir: string;
  editCsv: string;
  rows100kCsv: string;
  child: ChildProcess;
};

function ensureBuilt(): void {
  const indexHtml = join(DIST_DIR, "index.html");
  const skip = process.env.KRELLBOT_E2E_SKIP_BUILD === "1";
  if (skip || existsSync(indexHtml)) {
    return;
  }
  const result = spawnSync("npm", ["run", "build"], {
    cwd: FRONTEND_DIR,
    stdio: "inherit",
  });
  if (result.status !== 0) {
    throw new Error(`npm run build failed with status ${result.status}`);
  }
}

function sanitizedEnv(home: string): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  for (const [name, value] of Object.entries(process.env)) {
    if (name.startsWith("KRAKEN_") || name.startsWith("COINBASE_")) {
      continue;
    }
    env[name] = value;
  }
  env.KRELLBOT_HOME = home;
  env.HOME = home;
  env.USERPROFILE = home;
  env.PYTHONUNBUFFERED = "1";
  env.KRELLBOT_ENABLE_LIVE = "0";
  env.PYTHON_KEYRING_BACKEND = "tests.fakes.fake_keyring.FakeKeyring";
  env.PYTHONPATH = REPO_ROOT;
  return env;
}

function spawnWorkstation(
  home: string,
): Promise<{ url: string; child: ChildProcess }> {
  return new Promise((resolveStart, rejectStart) => {
    const env = sanitizedEnv(home);
    const proc = spawn(
      "uv",
      [
        "run",
        "--project",
        REPO_ROOT,
        "krellbot",
        "workstation",
        "--port",
        "0",
        "--dist",
        DIST_DIR,
      ],
      {
        cwd: REPO_ROOT,
        env,
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    let stderr = "";
    let resolved = false;
    const onLine = (chunk: Buffer | string): void => {
      const text = chunk.toString();
      stderr += text;
      const match = text.match(/Workstation running at (http:\/\/127\.0\.0\.1:\d+\/)/);
      if (match && !resolved) {
        resolved = true;
        resolveStart({ url: match[1], child: proc });
      }
    };
    proc.stdout?.on("data", onLine);
    proc.stderr?.on("data", onLine);
    proc.on("error", (err) => {
      if (!resolved) {
        rejectStart(err);
      }
    });
    proc.on("exit", (code) => {
      if (!resolved) {
        rejectStart(
          new Error(
            `krellbot workstation exited before printing URL (code=${code}); stderr=${stderr.slice(-1000)}`,
          ),
        );
      }
    });
    setTimeout(() => {
      if (!resolved) {
        rejectStart(new Error("timed out waiting for workstation URL"));
      }
    }, 60_000);
  });
}

export async function startWorkstationForSpec(): Promise<WorkstationHandle> {
  ensureBuilt();
  const homeDir = mkdtempSync(join(tmpdir(), "kb-e2e-"));
  const dataDir = join(homeDir, "data");
  mkdirSync(dataDir, { recursive: true });
  const editCsv = join(dataDir, "edit.csv");
  const rows100kCsv = join(dataDir, "rows100k.csv");
  createCsv(editCsv, { rows: 400 });
  createCsv(rows100kCsv, { rows: 100_000 });
  const started = await spawnWorkstation(homeDir);
  writeFileSync(join(dataDir, ".ns20-port"), started.url, "utf8");
  process.env.KRELLBOT_E2E_BASE_URL = started.url;
  process.env.KRELLBOT_E2E_EDIT_CSV = editCsv;
  process.env.KRELLBOT_E2E_ROWS_CSV = rows100kCsv;
  process.env.KRELLBOT_E2E_HOME = homeDir;
  return {
    baseURL: started.url,
    homeDir,
    editCsv,
    rows100kCsv,
    child: started.child,
  };
}

export async function stopWorkstationForSpec(handle: WorkstationHandle): Promise<void> {
  try {
    handle.child.kill("SIGINT");
  } catch {
    // ignore: child may have exited already
  }
  await new Promise((resolve) => setTimeout(resolve, 250));
  try {
    handle.child.kill("SIGKILL");
  } catch {
    // ignore
  }
  try {
    rmSync(handle.homeDir, { recursive: true, force: true });
  } catch {
    // ignore
  }
  delete process.env.KRELLBOT_E2E_BASE_URL;
  delete process.env.KRELLBOT_E2E_EDIT_CSV;
  delete process.env.KRELLBOT_E2E_ROWS_CSV;
  delete process.env.KRELLBOT_E2E_HOME;
}