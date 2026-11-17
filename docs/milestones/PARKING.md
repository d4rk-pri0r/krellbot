# Parking lot

One line per item. Nothing here is work until the owner moves it into a milestone file.

- 79 Python test files are named after retired task IDs (`test_m1r_*`, `test_ns*`, `test_int*`); rename by behavior when touched.
- CLI commands with no web equivalent could be removed once the web app covers them.
- `scripts/release_archive.py` still accepts a root `static/index.html` as the UI payload (the test fixtures use it); only `frontend/dist/index.html` is real after M0.5.
- Signal concept artboard shows a Learn top-nav; no Learn view exists yet — do not invent Learn in the cockpit. Portfolio history API + Workstation surface shipped in M4.4 (real journal/fills only; never fabricate sample bots).
- CI frontend flake: `Editor.ownedSeedIdentity.test.tsx` intermittently misses `[data-testid="editor-revision-id"]` under full suite load (seen on #426; passes alone locally; main tip green).
- CI macOS flake: `tests/test_int01_workstation_launch.py` intermittently times out (`test_workstation_serves_index_with_bootstrap_meta` HTTP TimeoutError / `test_workstation_missing_index_exits_2_with_build_hint` subprocess TimeoutExpired) under full suite (seen on #450; Ubuntu/Windows green; main tip green).
- CI Windows 3.13 flake: `tests/test_installer_wrapper_vs_engine.py` module fixture times out on SSL read fetching `https://krellbot.dev/api/install?os=linux` (seen on #522 tip 4b5ed77; other matrix cells green).
- `tests/test_ns07_assets.py::test_no_cdn_references` matches bare substring `cdn` inside Vite content-hashes (e.g. `index-Cdn….css` in `dist/index.html`); tighten to host-like tokens when that test is next touched.
- `docs/getting-started.md` Uninstall section still shows top-level `krellbot uninstall` like the pre-M13.8 `docs/cli.md` claim; align with cli.md honesty when that page is next touched.
