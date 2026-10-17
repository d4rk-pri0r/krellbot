/**
 * NS20 global-setup: ensure the production bundle exists.
 *
 * The bootstrap token is server-side one-shot; two spec files
 * cannot share one workstation. Each spec file owns its own
 * workstation via ``workstation-harness.ts``; this module only
 * makes sure the bundle is built.
 */

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = resolve(fileURLToPath(import.meta.url), "../../..");
const FRONTEND_DIR = join(REPO_ROOT, "frontend");
const DIST_DIR = join(FRONTEND_DIR, "dist");

export default function globalSetup(): void {
  const indexHtml = join(DIST_DIR, "index.html");
  if (process.env.KRELLBOT_E2E_SKIP_BUILD === "1" || existsSync(indexHtml)) {
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