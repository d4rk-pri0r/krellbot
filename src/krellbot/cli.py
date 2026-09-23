"""Krellbot local app. History is local. Orders go only to the Kraken demo host."""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from krellbot import paths as kb_paths
from krellbot import sanitize as kb_sanitize
from krellbot import secrets as kb_secrets
from krellbot.pack import lint as kb_pack_lint

ROOT = Path(__file__).resolve().parents[1]
STATE = Path.home() / ".krellbot" / "state.json"
API_FILE = Path.home() / ".krellbot" / "api-base"
DEMO_HOST = "demo-futures.kraken.com"
DEMO_TICKERS = f"https://{DEMO_HOST}/derivatives/api/v3/tickers"
DEAD = "Payment failed. Access is cut off. The app will not start and will not send orders."
GRACE = "Payment failed. Access will be cut off."


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def catalog_path():
    local = Path.home() / ".krellbot" / "catalog.json"
    if local.exists():
        return local
    return None


def load_catalog():
    path = catalog_path()
    if path is None:
        return None
    return json.loads(path.read_text())


def packs_dir():
    return kb_paths.home() / "packs"


def load_user_packs():
    root = packs_dir()
    if not root.is_dir():
        return []
    packs = []
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("id") and data.get("public_label"):
            data.setdefault("origin", "Written on this machine.")
            packs.append(data)
    return packs


def no_packs():
    print("No packs installed.")
    print(f"The pack format is open. Put a JSON file in {packs_dir()}/")
    print("Paid packs are a separate download. https://krellbot.dev")
    return 0


def load_state():
    if not STATE.exists():
        return {}
    return json.loads(STATE.read_text())


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    os.chmod(STATE, 0o600)


def api_bases():
    bases = []
    if os.environ.get("KRELLBOT_API"):
        bases.append(os.environ["KRELLBOT_API"].rstrip("/"))
    if API_FILE.exists():
        bases.append(API_FILE.read_text().strip().rstrip("/"))
    bases.extend(["https://krellbot.dev/api", "https://krellbot.pages.dev/api"])
    out = []
    for base in bases:
        if base and base not in out:
            out.append(base)
    return out


def post_json(url, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", "user-agent": "krellbot/0.1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.loads(res.read().decode())


def check_license(key):
    last = None
    for base in api_bases():
        try:
            return post_json(base + "/license", {"key": key})
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode())
            except Exception:
                body = None
            if isinstance(body, dict) and body.get("status"):
                return body
            last = exc
        except Exception as exc:
            last = exc
    return {"status": "dead", "message": f"License check failed. {last}"}


def gate(allow_missing=False):
    state = load_state()
    key = state.get("license_key")
    if not key:
        if allow_missing:
            return state, {"status": "missing", "message": ""}
        print("Paste the license key from the Stripe receipt. krellbot setup <key>", file=sys.stderr)
        raise SystemExit(2)
    result = check_license(key)
    state["license_status"] = result.get("status")
    save_state(state)
    if result.get("status") == "grace":
        print(GRACE)
    if result.get("status") == "dead":
        print(result.get("message") or DEAD)
        raise SystemExit(2)
    return state, result


def sparkline(points, width=32):
    vals = [p[1] for p in points]
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    span = hi - lo or 1
    blocks = "▁▂▃▄▅▆▇█"
    step = max(1, len(vals) // width)
    sampled = vals[::step][:width]
    return "".join(blocks[min(7, int((v - lo) / span * 7))] for v in sampled)


def find_pack(packs, key):
    key = key.lower().strip()
    for pack in packs:
        labels = {pack["id"].lower(), pack["public_label"].lower(), pack["public_label"][-1].lower()}
        if key in labels:
            return pack
    return None


def print_pack(pack, paid):
    label = pack.get("public_label") or pack.get("id") or "pack"
    if pack.get("spark") and pack.get("return_pct") is not None:
        print(f"{label}  {float(pack['return_pct']):+.1f}%  {sparkline(pack['spark'])}")
    else:
        print(label)
    window = f"{pack.get('window_start') or '?'} to {pack.get('window_end') or '?'}"
    venue = pack.get("venue_of_history") or "no venue yet"
    timeframe = pack.get("timeframe") or "?"
    trades = pack.get("trades", "?")
    drawdown = pack.get("max_drawdown_pct", "?")
    print(f"  {window}  {venue}  {timeframe}  {trades} trades  max drawdown {drawdown}%")
    if paid and pack.get("rule"):
        print(f"  {pack['rule']}")
    if pack.get("origin"):
        print(f"  {pack['origin']}")


def _print_dsl_pack(pack):
    """Print a DSL pack summary for `list`/`show`. Label is sanitize.text'd."""
    label = kb_sanitize.text(pack.get("label") or pack.get("id") or "pack")
    print(label)
    timeframe = pack.get("timeframe") or "?"
    author = kb_sanitize.text(pack.get("author") or "")
    markets = pack.get("markets") or []
    pairs = ", ".join(m.get("pair", "?") for m in markets)
    venues = ", ".join(sorted({m.get("venue", "?") for m in markets}))
    print(f"  v{pack.get('version', '?')}  {timeframe}  {venues}  {pairs}")
    if author:
        print(f"  by {author}")
    if pack.get("origin"):
        print(f"  {kb_sanitize.text(pack['origin'])}")


def _print_legacy_pack(pack, paid):
    """Print a legacy pack: same shape as before, plus the runnable marker."""
    print_pack(pack, paid)
    print("  legacy: not runnable")


def _list_user_packs():
    """Yield (kind, data) for every pack file under ~/.krellbot/packs.

    `kind` is 'dsl' (new Pack DSL schema_version=1) or 'legacy' (id+public_label
    with no schema_version). Skips files that fail IO or JSON parsing, and
    skips non-dict roots.
    """
    from krellbot.pack import discover

    return [(kind, data) for _path, kind, data in discover(kb_paths.home())]


def cmd_list():
    user = _list_user_packs()
    data = load_catalog()
    if not user and not data:
        return no_packs()
    if user:
        print("Your packs. The format is open.")
        print()
        for kind, pack in user:
            if kind == "dsl":
                _print_dsl_pack(pack)
                print()
            else:
                _print_legacy_pack(pack, True)
                print()
    if not data:
        return 0
    _, result = gate(allow_missing=True)
    paid = result.get("status") in {"paid", "grace"}
    print(f"Catalog {data['updated']}  ${data['price_month_usd']}/month")
    print("Past results. Not a Krellbot fill.")
    print()
    packs = sorted(data["packs"], key=lambda p: p["return_pct"], reverse=True)
    for pack in packs:
        print_pack(pack, paid)
        print()
    return 0


def cmd_show(key):
    from krellbot.pack import discover

    found = None
    found_kind = None
    for path, kind, data in discover(kb_paths.home()):
        ident = data.get("id") or data.get("label") or ""
        if ident.lower() == key.lower():
            found = (path, data)
            found_kind = kind
            break
    if found:
        _path, pack = found
        if found_kind == "dsl":
            _print_dsl_pack(pack)
            print()
            print("No order sent. A pack file is not an order.")
        else:
            _print_legacy_pack(pack, True)
            print()
            print("No order sent. This pack was written on this machine.")
        return 0
    data = load_catalog()
    if not data:
        return no_packs()
    _, result = gate(allow_missing=True)
    pack = find_pack(data["packs"], key)
    if not pack:
        print(f"No pack named {key}. Use: krellbot list", file=sys.stderr)
        return 1
    print_pack(pack, result.get("status") in {"paid", "grace"})
    print()
    print("No order sent. This is the plan history.")
    return 0


def cmd_lint(path_arg):
    """Validate a pack JSON file. Exit 0 on a valid DSL pack or a legacy pack."""
    path = Path(path_arg)
    if not path.exists():
        print(f"No such file: {path_arg}", file=sys.stderr)
        return 1
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"invalid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print("pack must be a JSON object", file=sys.stderr)
        return 1
    if kb_pack_lint.is_legacy(data):
        print("legacy: not runnable")
        return 0
    errors = kb_pack_lint.check(data)
    if errors:
        for err in errors:
            print(f"{err['field']}: {err['message']}", file=sys.stderr)
        return 1
    print("ok")
    return 0


def cmd_search(query):
    data = load_catalog()
    if not data:
        return no_packs()
    _, result = gate(allow_missing=False)
    if result.get("status") not in {"paid", "grace"}:
        print(DEAD)
        return 2
    q = query.lower()
    hits = [p for p in data["packs"] if q in (p.get("public_label", "") + " " + p.get("rule", "")).lower()]
    if not hits:
        print("No packs match.")
        return 1
    for pack in hits:
        print_pack(pack, True)
        print()
    return 0


def download_catalog(key):
    import urllib.parse

    quoted = urllib.parse.quote(key, safe="")
    for base in api_bases():
        req = urllib.request.Request(
            base + "/catalog?key=" + quoted,
            headers={"user-agent": "krellbot/0.1"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                body = res.read()
        except Exception:
            continue
        path = Path.home() / ".krellbot" / "catalog.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        os.chmod(path, 0o600)
        return True
    return False


def cmd_setup(license_key):
    result = check_license(license_key)
    if result.get("status") not in {"paid", "grace"}:
        print(result.get("message") or DEAD, file=sys.stderr)
        return 2
    state = load_state()
    state["license_key"] = license_key
    state["license_status"] = result["status"]
    save_state(state)
    print(result.get("message") or "License stored.")
    print(f"Stored in {STATE}")
    print("Coinbase is not ready.")
    if download_catalog(license_key):
        print("Packs downloaded to this machine.")
    else:
        print("License stored. Pack download failed. Run setup again when the site answers.")
    if result["status"] == "grace":
        print(GRACE)
    return 0


def cmd_keys_add(args):
    """Store exchange API key+secret in the OS keyring. No network. No license."""
    venue = args[0]
    file_path = None
    delete_file = False
    i_understand = False
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--file" and i + 1 < len(args):
            file_path = args[i + 1]
            i += 2
            continue
        if a == "--delete-file":
            delete_file = True
            i += 1
            continue
        if a == "--i-understand-plaintext":
            i_understand = True
            i += 1
            continue
        print(f"Unknown argument: {a}", file=sys.stderr)
        return 2
    if venue not in kb_secrets.VENUES:
        print(f"Unknown venue: {venue}", file=sys.stderr)
        return 2
    if file_path is None:
        print("--file is required", file=sys.stderr)
        return 2

    kb_paths.ensure_layout()

    if i_understand:
        ack = kb_paths.ensure_layout() / "run" / "plaintext-ack"
        existing = ack.read_text(encoding="utf-8") if ack.exists() else ""
        if venue not in existing.split():
            payload = (existing + venue + "\n").encode("utf-8")
            kb_paths.atomic_write(ack, payload, mode=0o600)

    lines: list[str] = []
    raw = Path(file_path).read_text(encoding="utf-8")
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    if len(lines) < 2:
        print("Key file needs two lines: API key, then secret.", file=sys.stderr)
        return 2

    key, secret = lines[0], lines[1]
    try:
        backend_name = kb_secrets.store(venue, key, secret)
    except RuntimeError as exc:
        print(f"Could not store credentials in the OS keychain ({type(exc).__name__}).", file=sys.stderr)
        return 1

    if delete_file:
        try:
            length = Path(file_path).stat().st_size
            fd = os.open(file_path, os.O_WRONLY | os.O_TRUNC)
            try:
                os.write(fd, b"\x00" * length)
                os.fsync(fd)
            finally:
                os.close(fd)
            Path(file_path).unlink()
        except FileNotFoundError:
            pass

    print(f"Stored in {backend_name}. Not sent to krellbot.dev.")
    return 0


def cmd_setup_kraken(path):
    """Alias for `keys add kraken --file <path>`. License-free path."""
    return cmd_keys_add(["kraken", "--file", path])


def demo_open():
    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(DEMO_TICKERS, method="GET")
    try:
        with opener.open(req, timeout=15) as res:
            body = res.read(300)
            return res.status == 200 and b"tickers" in body
    except Exception:
        return False


def cmd_run(key):
    user = find_pack(load_user_packs(), key)
    if user:
        print_pack(user, True)
        print()
        print("No order sent. A pack file is not an order.")
        return 0
    data = load_catalog()
    if not data:
        return no_packs()
    state, result = gate(allow_missing=False)
    pack = find_pack(data["packs"], key)
    if not pack:
        print(f"No pack named {key}. Use: krellbot list", file=sys.stderr)
        return 1
    print_pack(pack, True)
    print()
    print("Coinbase is not ready.")
    if result.get("status") == "grace":
        print("No order sent.")
        return 0
    if not state.get("kraken_key") or not state.get("kraken_secret"):
        print("No Kraken key on this machine. No order sent.")
        return 0
    if not demo_open():
        print("Kraken demo did not accept an API call. No order sent.")
        print("This is the plan history.")
        return 0
    print("Demo host answered. No order sent until that path is verified.")
    return 0


def cmd_data_import_kraken_ohlcvt(args):
    """Import a Kraken OHLCVT zip into the local CSV cache."""
    if len(args) < 1:
        print("usage: krellbot data import kraken-ohlcvt <zip> --pair PAIR --timeframe TF", file=sys.stderr)
        return 2
    zip_path = Path(args[0])
    if not zip_path.exists():
        print(f"No such file: {zip_path}", file=sys.stderr)
        return 1
    pair = None
    tf = None
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--pair" and i + 1 < len(args):
            pair = args[i + 1]
            i += 2
            continue
        if a == "--timeframe" and i + 1 < len(args):
            tf = args[i + 1]
            i += 2
            continue
        print(f"Unknown argument: {a}", file=sys.stderr)
        return 2
    if pair is None or tf is None:
        print("--pair and --timeframe are required", file=sys.stderr)
        return 2
    from krellbot.data import TF_MS, import_kraken_ohlcvt_zip, write_cache

    if tf not in TF_MS:
        print(f"Unsupported timeframe: {tf}", file=sys.stderr)
        return 1
    candles = import_kraken_ohlcvt_zip(zip_path, pair=pair, tf=tf)
    kb_paths.ensure_layout()
    csv_path, digest = write_cache(kb_paths.home(), "kraken", pair, tf, candles)
    print(f"wrote {csv_path}  rows={len(candles)}  sha256={digest[:12]}...")
    return 0


def cmd_backtest(args):
    """Run a backtest over a CSV (or fetched) candle series and print a receipt."""
    from krellbot.backtest import Backtester
    from krellbot.backtest.receipt import build_receipt
    from krellbot.data import TF_MS, GapError, check_gaps

    pack_path = Path(args[0])
    if not pack_path.exists():
        print(f"No such file: {pack_path}", file=sys.stderr)
        return 1
    try:
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"invalid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(pack, dict) or "schema_version" not in pack:
        print("pack must be a DSL pack JSON", file=sys.stderr)
        return 1

    venue = None
    data_csv = None
    slippage_mult = None
    fee_bps = None
    slippage_bps = None
    from_date = None
    to_date = None
    allow_gaps = False
    as_json = False
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--venue" and i + 1 < len(args):
            venue = args[i + 1]
            i += 2
            continue
        if a == "--data" and i + 1 < len(args):
            data_csv = args[i + 1]
            i += 2
            continue
        if a == "--slippage-mult" and i + 1 < len(args):
            try:
                slippage_mult = float(args[i + 1])
            except ValueError:
                print(f"invalid --slippage-mult: {args[i + 1]}", file=sys.stderr)
                return 1
            i += 2
            continue
        if a == "--fee-bps" and i + 1 < len(args):
            try:
                fee_bps = int(args[i + 1])
            except ValueError:
                print(f"invalid --fee-bps: {args[i + 1]}", file=sys.stderr)
                return 1
            i += 2
            continue
        if a == "--slippage-bps" and i + 1 < len(args):
            try:
                slippage_bps = int(args[i + 1])
            except ValueError:
                print(f"invalid --slippage-bps: {args[i + 1]}", file=sys.stderr)
                return 1
            i += 2
            continue
        if a == "--from" and i + 1 < len(args):
            from_date = args[i + 1]
            i += 2
            continue
        if a == "--to" and i + 1 < len(args):
            to_date = args[i + 1]
            i += 2
            continue
        if a == "--allow-gaps":
            allow_gaps = True
            i += 1
            continue
        if a == "--json":
            as_json = True
            i += 1
            continue
        print(f"Unknown argument: {a}", file=sys.stderr)
        return 2

    if venue not in {"kraken", "coinbase"}:
        print("--venue must be kraken or coinbase", file=sys.stderr)
        return 1
    tf = pack.get("timeframe")
    if tf not in TF_MS:
        print(f"pack timeframe unsupported: {tf}", file=sys.stderr)
        return 1
    match = next((m for m in pack.get("markets") or [] if m.get("venue") == venue), None)
    pair = match.get("pair") if match else None
    if pair is None:
        print("pack has no markets", file=sys.stderr)
        return 1

    if fee_bps is None:
        fee_bps = 40 if venue == "kraken" else 120
    if slippage_bps is None:
        slippage_bps = 5
    if slippage_mult is None:
        slippage_mult = 1.0

    if data_csv is None:
        print("--data <csv> is required", file=sys.stderr)
        return 1
    csv_path = Path(data_csv)
    if not csv_path.exists():
        print(f"No such file: {csv_path}", file=sys.stderr)
        return 1

    from krellbot.data.cache import _parse_csv, sha256_bytes

    body = csv_path.read_bytes()
    candles = _parse_csv(body)
    digest = sha256_bytes(body)

    try:
        check_gaps(candles, tf, pair=pair, allow_gaps=allow_gaps)
    except GapError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if from_date or to_date:
        from datetime import datetime, timezone

        if from_date:
            fts = int(datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
            candles = [c for c in candles if c.ts_ms >= fts]
        if to_date:
            tts = int(datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
            candles = [c for c in candles if c.ts_ms <= tts]

    if not candles:
        print(f"No candles after filtering (pair={pair})", file=sys.stderr)
        return 1

    bt = Backtester(pack, candles, fee_bps=fee_bps, slippage_bps=slippage_bps, slippage_mult=slippage_mult)
    records = bt.run()
    receipt = build_receipt(
        pack=pack,
        records=records,
        trade_count=bt.trade_count,
        data_manifest_sha256=digest,
        venue=venue,
        pair=pair,
        tf=tf,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        slippage_mult=slippage_mult,
    )
    if as_json:
        print(json.dumps(receipt))
    else:
        m = receipt["metrics"]
        print(f"{receipt['from']} -> {receipt['to']}  {receipt['venue']} {receipt['pair']} {receipt['tf']}")
        print(f"  total_return_pct: {m['total_return_pct']:.4f}")
        print(f"  cagr_pct:         {m['cagr_pct']}")
        print(f"  max_drawdown_pct: {m['max_drawdown_pct']:.4f}")
        print(f"  return_to_dd:     {m['return_to_dd']}")
        print(f"  trade_count:      {m['trade_count']}")
        print(f"  exposure_pct:     {m['exposure_pct']:.4f}")
        bh = m["buy_and_hold"]
        print(f"  buy_and_hold total_return_pct: {bh['total_return_pct']:.4f}")
    return 0


def usage():
    print(
        "Usage: krellbot list | show <plan> | search <text> | setup <license-key> | setup-kraken <key-file> | keys add <venue> --file <path> | run <plan> | lint <pack.json> | backtest <pack.json> [--venue kraken|coinbase] [--data csv] [--json] | data import kraken-ohlcvt <zip> --pair PAIR --timeframe TF",
        file=sys.stderr,
    )
    return 2


def main(argv):
    if len(argv) < 2 or argv[1] in {"-h", "--help", "help"}:
        return usage()
    try:
        kb_secrets.migrate_legacy()
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"Could not migrate legacy state: {type(exc).__name__}.", file=sys.stderr)
        return 1
    cmd = argv[1]
    if cmd in {"list", "ls"} and len(argv) == 2:
        return cmd_list()
    if cmd == "show" and len(argv) == 3:
        return cmd_show(argv[2])
    if cmd == "search" and len(argv) == 3:
        return cmd_search(argv[2])
    if cmd == "setup" and len(argv) == 3:
        return cmd_setup(argv[2])
    if cmd == "setup-kraken" and len(argv) == 3:
        return cmd_setup_kraken(argv[2])
    if cmd == "run" and len(argv) == 3:
        return cmd_run(argv[2])
    if cmd == "lint" and len(argv) == 3:
        return cmd_lint(argv[2])
    if cmd == "keys" and len(argv) >= 4 and argv[2] == "check":
        from krellbot.cli_keys import cmd_keys_check

        return cmd_keys_check(argv[3:])
    if cmd == "keys" and len(argv) >= 4 and argv[2] == "add":
        return cmd_keys_add(argv[3:])
    if cmd == "backtest" and len(argv) >= 3:
        return cmd_backtest(argv[2:])
    if cmd == "data" and len(argv) >= 4 and argv[2] == "import" and argv[3] == "kraken-ohlcvt":
        return cmd_data_import_kraken_ohlcvt(argv[4:])
    return usage()


def entry():
    raise SystemExit(main(sys.argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
