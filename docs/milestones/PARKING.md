# Parking lot

One line per item. Nothing here is work until the owner moves it into a milestone file.

- 79 Python test files are named after retired task IDs (`test_m1r_*`, `test_ns*`, `test_int*`); rename by behavior when touched.
- CLI commands with no web equivalent could be removed once the web app covers them.
- Coinbase live path: same four obligations as M1, not started (engineering tracked under M11.3 once M10.1–M10.2 land).
- `scripts/release_archive.py` still accepts a root `static/index.html` as the UI payload (the test fixtures use it); only `frontend/dist/index.html` is real after M0.5.
- Signal concept artboard shows a Learn top-nav; no Learn view exists yet — do not invent Learn in the cockpit. Portfolio history API + Workstation surface shipped in M4.4 (real journal/fills only; never fabricate sample bots).
- CI frontend flake: `Editor.ownedSeedIdentity.test.tsx` intermittently misses `[data-testid="editor-revision-id"]` under full suite load (seen on #426; passes alone locally; main tip green).
- CI macOS flake: `tests/test_int01_workstation_launch.py` intermittently times out (`test_workstation_serves_index_with_bootstrap_meta` HTTP TimeoutError / `test_workstation_missing_index_exits_2_with_build_hint` subprocess TimeoutExpired) under full suite (seen on #450; Ubuntu/Windows green; main tip green).
- `docs/getting-started.md` Uninstall section still shows top-level `krellbot uninstall` like the pre-M13.8 `docs/cli.md` claim; align with cli.md honesty when that page is next touched.
