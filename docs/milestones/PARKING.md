# Parking lot

One line per item. Nothing here is work until the owner moves it into a milestone file.

- 79 Python test files are named after retired task IDs (`test_m1r_*`, `test_ns*`, `test_int*`); rename by behavior when touched.
- CLI commands with no web equivalent could be removed once the web app covers them.
- `scripts/release_archive.py` still accepts a root `static/index.html` as the UI payload (the test fixtures use it); only `frontend/dist/index.html` is real after M0.5.
- Signal concept artboard shows a Learn top-nav; no Learn view exists yet — do not invent Learn in the cockpit. Portfolio history API + Workstation surface shipped in M4.4 (real journal/fills only; never fabricate sample bots).
- CI frontend flake: `Editor.ownedSeedIdentity.test.tsx` intermittently misses `[data-testid="editor-revision-id"]` under full suite load (seen on #426; passes alone locally; main tip green).
- CI macOS flake: `tests/test_int01_workstation_launch.py` under full-suite load (seen on #450); wait/HTTP budgets raised — keep watching macOS matrix if TimeoutError returns.
- CI Windows 3.13 flake: `tests/test_installer_wrapper_vs_engine.py` live installer fetch can still fail after retries under sustained SSL loss (retries landed; keep watching Windows matrix).
- `tests/test_ns07_assets.py::test_no_cdn_references` matches bare substring `cdn` inside Vite content-hashes (e.g. `index-Cdn….css` in `dist/index.html`); tighten to host-like tokens when that test is next touched.
- Hosting operator exchange keys (cloud key custody) — explicitly out of P0–P4; never promote without a custody redesign.
- Paid ads for trading signals — restricted channels; out of P0–P4 growth plan.
- Personalized / individualized trading advice framing — packs stay tools; out of scope.
- CLI user-facing feature expansion — AGENTS.md web-only surface; keep CLI as plumbing.
- More than two qualified live venues — Binance live still waits after M23.4 Coinbase second-venue product path; park further live venues.
- Exchange-native free AI agent tooling parity race — spike only in M22.5; no cloud-key me-too product.
- Multi-pack reservation / breaking one-pack-per-(venue,pair) before independent qualification (still true post-M16).
- Learn top-nav / Learn view (Signal artboard) — still do not invent in cockpit.
