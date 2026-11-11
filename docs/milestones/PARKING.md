# Parking lot

One line per item. Nothing here is work until the owner moves it into a milestone file.

- Linux arm64: the site installer pins x86_64 only and refuses other architectures.
- `npm ci` reports 5 advisories (2 moderate, 3 high); not audited (from #371).
- 79 Python test files are named after retired task IDs (`test_m1r_*`, `test_ns*`, `test_int*`); rename by behavior when touched.
- CLI commands with no web equivalent could be removed once the web app covers them.
- Coinbase live path: same four obligations as M1, not started.
- Paper pricing uses last-closed rather than forming candles (MEDIUM note on #197).
