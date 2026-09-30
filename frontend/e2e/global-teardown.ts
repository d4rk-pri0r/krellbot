/**
 * NS20 global-teardown: SIGINT the workstation, wipe the temp home.
 *
 * Lives in a separate module from ``global-setup.ts`` because Playwright
 * imports the two modules independently; sharing state through
 * ``process.env`` is the cleanest contract.
 */

import { rmSync, existsSync } from "node:fs";

export default function globalTeardown(): void {
  const home = process.env.KRELLBOT_HOME;
  if (home && existsSync(home)) {
    try {
      rmSync(home, { recursive: true, force: true });
    } catch {
      // ignore: best-effort
    }
  }
  delete process.env.KRELLBOT_E2E_BASE_URL;
  delete process.env.KRELLBOT_E2E_EDIT_CSV;
  delete process.env.KRELLBOT_E2E_ROWS_CSV;
}