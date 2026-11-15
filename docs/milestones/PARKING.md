# Parking lot

One line per item. Nothing here is work until the owner moves it into a milestone file.

- Linux arm64: the site installer pins x86_64 only and refuses other architectures.
- `npm ci` reports 5 advisories (2 moderate, 3 high); not audited (from #371).
- 79 Python test files are named after retired task IDs (`test_m1r_*`, `test_ns*`, `test_int*`); rename by behavior when touched.
- CLI commands with no web equivalent could be removed once the web app covers them.
- Coinbase live path: same four obligations as M1, not started.
- Paper pricing uses last-closed rather than forming candles (MEDIUM note on #197).
- Strategies reopen: until the revision read resolves, the previous editor stays editable with no busy state, and edits made there are dropped on remount (`src/shell/WorkstationShell.tsx` `handleLibraryReopen`; found in M0.3).
- `scripts/release_archive.py` still accepts a root `static/index.html` as the UI payload (the test fixtures use it); only `frontend/dist/index.html` is real after M0.5.
- docs/cli.md documents `krellbot uninstall`, but `cli.py` has no top-level `uninstall` (installer/launcher flow).
- Signal concept artboard shows a Learn top-nav and sample portfolio equity/bot cards; no Learn view or portfolio-history API exists yet — do not invent those in the cockpit.
- Packs remain under Strategies (toggle), not a top-level nav item matching the marketing concept strip.
- CI frontend flake: `Editor.ownedSeedIdentity.test.tsx` intermittently misses `[data-testid="editor-revision-id"]` under full suite load (seen on #426; passes alone locally; main tip green).
