"""Krellbot local app. History is local. Orders go only to the Kraken demo host."""

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import Any

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
    from krellbot.tls import urlopen

    with urlopen(req, timeout=20) as res:
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


COMMUNITY_BANNER = "Community pack. Unverified. No guarantee."


def _is_community_path(path) -> bool:
    """True if `path` lives under `<kb_home>/packs/community/`."""
    from krellbot import catalog as kb_catalog

    try:
        return kb_catalog.is_community(Path(path), kb_paths.home())
    except (OSError, ValueError):
        return False


def _print_legacy_pack(pack, paid):
    """Print a legacy pack: same shape as before, plus the runnable marker."""
    print_pack(pack, paid)
    print("  legacy: not runnable")


def _list_user_packs():
    """Yield (path, kind, data) for every pack file under ~/.krellbot/packs
    and ~/.krellbot/packs/community/.

    `kind` is 'dsl' (new Pack DSL schema_version=1) or 'legacy' (id+public_label
    with no schema_version). Skips files that fail IO or JSON parsing, and
    skips non-dict roots.
    """
    from krellbot.pack import discover

    return list(discover(kb_paths.home()))


def cmd_list():
    user = _list_user_packs()
    data = load_catalog()
    if not user and not data:
        return no_packs()
    if user:
        print("Your packs. The format is open.")
        print()
        for path, kind, pack in user:
            if kind == "dsl":
                _print_dsl_pack(pack)
                if _is_community_path(path):
                    print(f"  {COMMUNITY_BANNER}")
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
    found_path = None
    for path, kind, data in discover(kb_paths.home()):
        ident = data.get("id") or data.get("label") or ""
        if ident.lower() == key.lower():
            found = (path, data)
            found_kind = kind
            found_path = path
            break
    if found:
        _path, pack = found
        if found_kind == "dsl":
            _print_dsl_pack(pack)
            if _is_community_path(found_path):
                print(f"  {COMMUNITY_BANNER}")
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
        from krellbot.tls import urlopen

        try:
            with urlopen(req, timeout=20) as res:
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
        "Usage: krellbot list | show <plan> | search <text> | setup <license-key> | setup-kraken <key-file> | keys add <venue> --file <path> | run <plan> | lint <pack.json> | backtest <pack.json> [--venue kraken|coinbase] [--data csv] [--json] | data import kraken-ohlcvt <zip> --pair PAIR --timeframe TF | arm <pack.json> --venue kraken|coinbase --mode paper|live [--paper-balance USD] | disarm --venue NAME --pair PAIR | stop --venue NAME --pair PAIR --price N | tick --venue NAME [--offline-candles csv] | status [--venue NAME] | journal --tail N | service install|uninstall [--dry-run] [--root PATH] | doctor [--json] | ui [--port N] | community list | community install <id> | telemetry enable | telemetry disable | telemetry show",
        file=sys.stderr,
    )
    return 2


def cmd_arm(args):
    """`krellbot arm <pack.json> --venue V --mode M [--paper-balance USD]`."""
    from krellbot import secrets as kb_secrets_mod
    from krellbot.run import arm_pack

    if not args:
        print(
            "usage: krellbot arm <pack.json> --venue kraken|coinbase --mode paper|live [--paper-balance USD]",
            file=sys.stderr,
        )
        return 2
    pack_arg = args[0]
    venue = None
    mode = None
    paper_balance = None
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--venue" and i + 1 < len(args):
            venue = args[i + 1]
            i += 2
            continue
        if a == "--mode" and i + 1 < len(args):
            mode = args[i + 1]
            i += 2
            continue
        if a == "--paper-balance" and i + 1 < len(args):
            try:
                paper_balance = Decimal(args[i + 1])
            except (ValueError, ArithmeticError):
                print(f"invalid --paper-balance: {args[i + 1]}", file=sys.stderr)
                return 2
            i += 2
            continue
        print(f"Unknown argument: {a}", file=sys.stderr)
        return 2
    if venue is None or mode is None:
        print("--venue and --mode are required", file=sys.stderr)
        return 2

    key_check = None
    if mode == "live":
        from krellbot.cli_keys import _probe

        def key_check(venue_arg):

            try:
                api_key, api_secret = kb_secrets_mod.get(venue_arg)
            except (FileNotFoundError, ValueError, PermissionError):
                return None
            return _probe(venue_arg, api_key, api_secret)

    rc = arm_pack(
        Path(pack_arg),
        venue=venue,
        mode=mode,
        paper_balance=paper_balance,
        confirm_fn=None,
        key_check=key_check,
    )
    if rc == 0 and _is_community_path(Path(pack_arg).resolve()):
        print(COMMUNITY_BANNER, flush=True)
    return rc


def cmd_disarm(args):
    """`krellbot disarm --venue V --pair P`."""
    from krellbot.run import disarm_pack

    venue = None
    pair = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--venue" and i + 1 < len(args):
            venue = args[i + 1]
            i += 2
            continue
        if a == "--pair" and i + 1 < len(args):
            pair = args[i + 1]
            i += 2
            continue
        print(f"Unknown argument: {a}", file=sys.stderr)
        return 2
    if venue is None or pair is None:
        print("--venue and --pair are required", file=sys.stderr)
        return 2
    return disarm_pack(venue=venue, pair=pair)


def cmd_stop(args):
    """`krellbot stop --venue V --pair P --price N`."""
    from krellbot.run import set_stop

    venue = None
    pair = None
    price = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--venue" and i + 1 < len(args):
            venue = args[i + 1]
            i += 2
            continue
        if a == "--pair" and i + 1 < len(args):
            pair = args[i + 1]
            i += 2
            continue
        if a == "--price" and i + 1 < len(args):
            try:
                price = Decimal(args[i + 1])
            except (ValueError, ArithmeticError):
                print(f"invalid --price: {args[i + 1]}", file=sys.stderr)
                return 2
            i += 2
            continue
        print(f"Unknown argument: {a}", file=sys.stderr)
        return 2
    if venue is None or pair is None or price is None:
        print("--venue, --pair, --price are required", file=sys.stderr)
        return 2
    return set_stop(venue=venue, pair=pair, new_stop=price)


class CandleFetchError(RuntimeError):
    """Raised when the public candle fetch fails during tick.

    The wrapped type name is the only thing the engine surfaces to the
    operator — the original exception's message and any secret it carried
    are not echoed. Tests inject `fetch` so the real HTTP functions are
    never called.
    """

    def __init__(self, exc_type_name: str):
        self.exc_type_name = exc_type_name
        super().__init__(exc_type_name)


LIVE_TICK_REFUSED = "live is off; set KRELLBOT_ENABLE_LIVE=1 to tick a live pack"


def _default_fetch(venue: str, pair: str, tf: str, transport):
    """Dispatch to the real public fetch for `venue`.

    `transport` is unused for Kraken (its public fetch talks urllib directly);
    it is required for Coinbase. Tests inject their own `fetch` so the real
    HTTP functions are never called from the test suite.
    """
    from krellbot.data import fetch_coinbase_candles, fetch_kraken_ohlc

    if venue == "kraken":
        return fetch_kraken_ohlc(pair, tf)
    if venue == "coinbase":
        return fetch_coinbase_candles(pair, tf, transport)
    raise ValueError(f"unsupported venue for fetch: {venue!r}")


def _default_transport():
    """Build the default Kraken-shaped transport (urllib-backed).

    Tests inject a fake. CoinbaseVenue expects the same shape (post/get).
    """
    from krellbot.venues.kraken import HttpTransport

    return HttpTransport()


def _as_validate_transport(transport):
    """Adapt a venue transport to the paper venue's validate POST protocol."""

    class _Adapter:
        def post(self, url: str, body: dict, headers: dict) -> dict:
            return transport.post(url, body, headers)

    return _Adapter()


def _key_present(venue: str) -> bool:
    """True when a key is stored. The key itself is never returned to the caller."""
    try:
        kb_secrets.get(venue)
    except (FileNotFoundError, ValueError, PermissionError):
        return False
    return True


def _build_fetch_reader(armed_list, *, fetch, transport):
    """Load the pack whose pair is being read, then call `fetch`.

    The exception type name is the only text that escapes. The exception
    message is not surfaced.
    """
    by_pair = {a.pair: a for a in armed_list}

    def reader(venue: str, pair: str):
        armed = by_pair.get(pair)
        if armed is None:
            raise CandleFetchError("ValueError")
        try:
            raw = Path(armed.pack_path).read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise CandleFetchError(type(exc).__name__) from exc
        if not isinstance(data, dict) or not data.get("timeframe"):
            raise CandleFetchError("ValueError")
        try:
            candles = fetch(venue, pair, data["timeframe"], transport)
            return list(candles or [])
        except CandleFetchError:
            raise
        except Exception as exc:
            raise CandleFetchError(type(exc).__name__) from exc

    return reader


def _build_offline_reader(offline: Path):
    """Build the `--offline-candles` reader from a CSV file."""

    def reader(venue: str, pair: str):
        from krellbot.pack.model import Candle

        text = offline.read_text(encoding="utf-8")
        candles = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("ts_ms,"):
                continue
            parts = line.split(",")
            if len(parts) != 6:
                continue
            try:
                candles.append(
                    Candle(
                        ts_ms=int(parts[0]),
                        open=Decimal(parts[1]),
                        high=Decimal(parts[2]),
                        low=Decimal(parts[3]),
                        close=Decimal(parts[4]),
                        volume=Decimal(parts[5]),
                    )
                )
            except (ValueError, ArithmeticError):
                continue
        return candles

    return reader


def venue_for_tick(home, armed_list, *, transport, fetch):
    """Build the venue object and reader for one venue's armed packs.

    Returns `(venue_obj, reader)` or a refusal string. A string is printed
    and the tick exits 1. The string never contains a key.
    """
    from krellbot.venues.base import WithdrawCapableError
    from krellbot.venues.coinbase import CoinbaseVenue
    from krellbot.venues.kraken import KrakenVenue
    from krellbot.venues.paper import PaperVenue, default_rules

    armed = armed_list[0]
    reader = _build_fetch_reader(armed_list, fetch=fetch, transport=transport)
    modes = {a.mode for a in armed_list}
    if modes != {"paper"} and modes != {"live"}:
        return "mixed paper and live arms; tick refused"

    if armed.mode == "paper":
        has_key = _key_present(armed.venue)
        venue_obj = PaperVenue(
            armed.venue,
            rules_provider=lambda _p: default_rules(_p),
            candle_reader=reader,
            home=home,
            starting_cash=armed.starting_cash,
            has_stored_key=has_key,
            validate_transport=_as_validate_transport(transport) if has_key and armed.venue == "kraken" else None,
        )
        return (venue_obj, reader)

    if os.environ.get("KRELLBOT_ENABLE_LIVE") != "1":
        return LIVE_TICK_REFUSED
    try:
        api_key, api_secret = kb_secrets.get(armed.venue)
    except (FileNotFoundError, ValueError, PermissionError):
        return f"no key stored for {armed.venue}"
    try:
        if armed.venue == "kraken":
            venue_obj = KrakenVenue(api_key, api_secret, transport)
        elif armed.venue == "coinbase":
            venue_obj = CoinbaseVenue(api_key, api_secret, transport, product_id=armed.pair)
        else:
            return f"unsupported live venue {armed.venue}"
        perms = venue_obj.check_key()
    except WithdrawCapableError:
        return f"{armed.venue}: key can withdraw; trade-only keys refused"
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        return "live tick refused"
    if perms is None or not perms.can_trade or perms.can_withdraw:
        return f"{armed.venue}: key can withdraw; trade-only keys refused"
    return (venue_obj, reader)


def _build_live_venue_for_offline(armed, *, transport):
    """Same venue contract as `venue_for_tick` for live, but no fetch reader.

    Used when `--offline-candles` is set on a live arm. Does not call fetch;
    the caller wires the offline reader into `run.tick`.
    """
    from krellbot.venues.base import WithdrawCapableError
    from krellbot.venues.coinbase import CoinbaseVenue
    from krellbot.venues.kraken import KrakenVenue

    if os.environ.get("KRELLBOT_ENABLE_LIVE") != "1":
        return LIVE_TICK_REFUSED
    try:
        api_key, api_secret = kb_secrets.get(armed.venue)
    except (FileNotFoundError, ValueError, PermissionError):
        return f"no key stored for {armed.venue}"
    try:
        if armed.venue == "kraken":
            venue_obj = KrakenVenue(api_key, api_secret, transport)
        elif armed.venue == "coinbase":
            venue_obj = CoinbaseVenue(api_key, api_secret, transport, product_id=armed.pair)
        else:
            return f"unsupported live venue {armed.venue}"
        perms = venue_obj.check_key()
    except WithdrawCapableError:
        return f"{armed.venue}: key can withdraw; trade-only keys refused"
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        return "live tick refused"
    if perms is None or not perms.can_trade or perms.can_withdraw:
        return f"{armed.venue}: key can withdraw; trade-only keys refused"
    return venue_obj


def _record_fetch_error(*, venue: str, armed, exc_type_name: str) -> None:
    """Append a `reason: fetch_error` tick record before exit 1."""
    from krellbot import journal as kb_journal

    try:
        kb_journal.append(
            {
                "ts": int(_now_seconds_tick()),
                "kind": "tick",
                "venue": venue,
                "pack": armed.pack_id,
                "bar_ts": 0,
                "detail": {
                    "reason": "fetch_error",
                    "exception": exc_type_name,
                    "pair": armed.pair,
                },
            }
        )
    except (OSError, ValueError):
        # Tests inject journal sinks that may not validate; never let the
        # error path itself crash the CLI.
        pass


def _now_seconds_tick() -> float:
    import time

    return time.time()


def cmd_tick(args, *, fetch=None, transport=None):
    """`krellbot tick --venue V [--offline-candles CSV]`.

    `fetch` and `transport` are injected for tests. The defaults talk to the
    real public fetch and urllib. A fetch error is printed as the exception
    type name only, journaled, and the tick exits 1.
    """
    from krellbot.config import load_config
    from krellbot.run import tick as run_tick
    from krellbot.venues.paper import PaperVenue, default_rules

    if fetch is None:
        fetch = _default_fetch
    if transport is None:
        transport = _default_transport()

    venue = None
    offline = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--venue" and i + 1 < len(args):
            venue = args[i + 1]
            i += 2
            continue
        if a == "--offline-candles" and i + 1 < len(args):
            offline = Path(args[i + 1])
            i += 2
            continue
        print(f"Unknown argument: {a}", file=sys.stderr)
        return 2
    if venue is None:
        print("--venue is required", file=sys.stderr)
        return 2

    home = kb_paths.home()
    config = load_config(home)
    armed_list = [a for a in config.armed if a.venue == venue]
    if not armed_list:
        print(f"no armed packs for {venue}", flush=True)
        return 0
    modes = {a.mode for a in armed_list}
    if modes != {"paper"} and modes != {"live"}:
        print("mixed paper and live arms; tick refused", flush=True)
        return 1
    armed = armed_list[0]

    if offline is not None:
        reader = _build_offline_reader(offline)
        if armed.mode == "paper":
            has_key = _key_present(armed.venue)
            venue_obj = PaperVenue(
                armed.venue,
                rules_provider=lambda _p: default_rules(_p),
                candle_reader=reader,
                home=home,
                starting_cash=armed.starting_cash,
                has_stored_key=has_key,
                validate_transport=_as_validate_transport(transport) if has_key and armed.venue == "kraken" else None,
            )
            return run_tick(venue=venue, venue_obj=venue_obj, reader=reader)
        venue_obj = _build_live_venue_for_offline(armed, transport=transport)
        if isinstance(venue_obj, str):
            print(venue_obj, flush=True)
            return 1
        return run_tick(venue=venue, venue_obj=venue_obj, reader=reader)

    result = venue_for_tick(home=home, armed_list=armed_list, transport=transport, fetch=fetch)
    if isinstance(result, str):
        print(result, flush=True)
        return 1
    venue_obj, reader = result
    try:
        return run_tick(venue=venue, venue_obj=venue_obj, reader=reader)
    except CandleFetchError as exc:
        print(exc.exc_type_name, flush=True)
        _record_fetch_error(venue=venue, armed=armed, exc_type_name=exc.exc_type_name)
        return 1


def cmd_status(args):
    """`krellbot status [--venue V]`."""
    from krellbot.run import status as run_status

    venue = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--venue" and i + 1 < len(args):
            venue = args[i + 1]
            i += 2
            continue
        print(f"Unknown argument: {a}", file=sys.stderr)
        return 2
    return run_status(venue=venue)


_JOURNAL_WINDOW_SECONDS = {"24h": 24 * 3600, "14d": 14 * 86400}
_JOURNAL_SECRET_FIELDS = ("key", "secret", "license", "balance")


def _drop_secret_fields(record: Any) -> Any:
    """Recursively drop `key`, `secret`, `license`, `balance` from a record."""

    if isinstance(record, dict):
        return {k: _drop_secret_fields(v) for k, v in record.items() if k not in _JOURNAL_SECRET_FIELDS}
    if isinstance(record, list):
        return [_drop_secret_fields(v) for v in record]
    return record


def _read_journal_records(home: Path) -> list:
    """Return all valid journal records under `<home>/journal`, in file order."""
    journal_dir = Path(home) / "journal"
    if not journal_dir.is_dir():
        return []
    records: list = []
    for path in sorted(journal_dir.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            records.append(rec)
    return records


def cmd_journal(args, *, now: float | None = None):
    """`krellbot journal --tail N | --since 24h|14d [--json]`.

    `--since` accepts `24h` or `14d` only; unknown values exit 2. `--json`
    emits one JSON object per line and drops `key`, `secret`, `license`,
    and `balance` fields at any depth. `now` is injected for tests so the
    since-window math does not depend on wall-clock time.
    """
    import time

    if now is None:
        now = time.time()

    tail = 5
    since_seconds: int | None = None
    as_json = False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--tail" and i + 1 < len(args):
            try:
                tail = int(args[i + 1])
            except ValueError:
                print(f"invalid --tail: {args[i + 1]}", file=sys.stderr)
                return 2
            i += 2
            continue
        if a == "--since" and i + 1 < len(args):
            value = args[i + 1]
            if value not in _JOURNAL_WINDOW_SECONDS:
                print(
                    f"unsupported --since value: {value!r}; use one of 24h, 14d",
                    file=sys.stderr,
                )
                return 2
            since_seconds = _JOURNAL_WINDOW_SECONDS[value]
            i += 2
            continue
        if a == "--json":
            as_json = True
            i += 1
            continue
        print(f"Unknown argument: {a}", file=sys.stderr)
        return 2

    home = kb_paths.home()
    records = _read_journal_records(home)
    if not records:
        print("no journal", flush=True)
        return 0

    if since_seconds is not None:
        threshold = int(now) - since_seconds
        records = [r for r in records if isinstance(r.get("ts"), int) and r["ts"] >= threshold]
    else:
        records = records[-tail:]

    if not records:
        print("no journal records", flush=True)
        return 0

    for rec in records:
        if as_json:
            rec = _drop_secret_fields(rec)
        print(json.dumps(rec, sort_keys=True), flush=True)
    return 0


def _resolve_executable() -> str:
    """Resolve the absolute path of the running krellbot executable."""
    import os

    candidate = os.path.abspath(sys.argv[0] or sys.executable)
    return candidate


def cmd_service(args):
    """`krellbot service install|uninstall [--dry-run] [--root PATH]`."""
    from krellbot import service as kb_service

    if not args:
        print(
            "usage: krellbot service install|uninstall [--dry-run] [--root PATH]",
            file=sys.stderr,
        )
        return 2
    sub = args[0]
    dry_run = False
    write_root: Path | None = None
    executable: str | None = None
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--dry-run":
            dry_run = True
            i += 1
            continue
        if a == "--root" and i + 1 < len(args):
            write_root = Path(args[i + 1])
            i += 2
            continue
        if a == "--executable" and i + 1 < len(args):
            executable = args[i + 1]
            i += 2
            continue
        print(f"Unknown argument: {a}", file=sys.stderr)
        return 2

    if sub == "install":
        if write_root is None and not dry_run:
            write_root = Path.home()
        return kb_service.install(
            executable=executable or _resolve_executable(),
            home=kb_paths.home(),
            write_root=write_root,
            dry_run=dry_run,
        )
    if sub == "uninstall":
        if write_root is None:
            write_root = Path.home()
        return kb_service.uninstall(home=kb_paths.home(), write_root=write_root)
    print(f"unknown service subcommand: {sub}", file=sys.stderr)
    return 2


def _kraken_time_source() -> int:
    """Read the public Kraken Time endpoint. Returns unixtime seconds.

    Raises on any network or parse failure. Caller (`cmd_doctor`) catches the
    error so doctor reports `clock not checked` instead of crashing.
    """
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        "https://api.kraken.com/0/public/Time",
        headers={"user-agent": "krellbot/0.1"},
    )
    from krellbot.tls import urlopen

    with urlopen(req, timeout=10) as res:
        body = res.read().decode("utf-8")
    payload = json.loads(body)
    return int(payload["result"]["unixtime"])


def cmd_doctor(args):
    """`krellbot doctor [--json]`.

    Wires the Kraken public Time endpoint as the clock source. Tests bypass
    this command and call `krellbot.doctor.run` directly with a fake source
    to prove zero socket calls.
    """
    from krellbot import doctor as kb_doctor

    as_json = False
    skip_clock = False
    for a in args:
        if a == "--json":
            as_json = True
            continue
        if a == "--skip-clock":
            skip_clock = True
            continue
        print(f"Unknown argument: {a}", file=sys.stderr)
        return 2

    if skip_clock:
        time_source: Any = None
    else:

        def time_source() -> int:
            return _kraken_time_source()

    rc, body = kb_doctor.run(
        home=kb_paths.home(),
        write_root=Path.home(),
        time_source=time_source,
        as_json=as_json,
    )
    print(body)
    return rc


def cmd_ui(args):
    """`krellbot ui [--port N]`.

    Bind a token-gated dashboard to 127.0.0.1 on a random port (or the
    given `--port`). Print the URL with the gate token. SIGINT stops the
    server and returns 0. The server never accepts a non-loopback Host
    header and never opens a socket to a venue.
    """
    import signal

    from krellbot.ui.server import DashboardServer

    port = 0
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--port" and i + 1 < len(args):
            try:
                port = int(args[i + 1])
            except ValueError:
                print(f"invalid --port: {args[i + 1]}", file=sys.stderr)
                return 2
            i += 2
            continue
        print(f"Unknown argument: {a}", file=sys.stderr)
        return 2

    server = DashboardServer(home=kb_paths.home(), port=port)
    server.start()

    url = f"http://127.0.0.1:{server.bound_port}/{server.token}/"
    print(f"Dashboard running at {url}")
    print("Open it in your browser. Ctrl-C to stop.")
    print("Bound to 127.0.0.1 only. Token in URL is also the session cookie.")

    stopped = threading.Event()

    def _on_signal(signum: int, frame: Any) -> None:
        stopped.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        stopped.wait()
    finally:
        server.stop()
        print("Stopped.")
    return 0


# ---- community -------------------------------------------------------------


class _UrllibGetTransport:
    """Default transport for `community install`. Tests inject their own."""

    def __init__(self, *, timeout: float = 20.0) -> None:
        self._timeout = timeout

    def get(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"user-agent": "krellbot/0.1"})
        from krellbot.tls import urlopen

        with urlopen(req, timeout=self._timeout) as res:
            return res.read()


def cmd_community(args):
    """`krellbot community list | install <id>`."""
    from krellbot import community as kb_community

    if not args:
        print("usage: krellbot community list | install <id>", file=sys.stderr)
        return 2
    sub = args[0]
    if sub == "list":
        return _cmd_community_list(kb_community.list_installed(kb_paths.home()))
    if sub == "install" and len(args) == 2:
        return _cmd_community_install(args[1], transport=_UrllibGetTransport())
    print("usage: krellbot community list | install <id>", file=sys.stderr)
    return 2


def _cmd_community_list(items):
    if not items:
        print("No community packs installed.")
        print("Install with: krellbot community install <id>")
        return 0
    print("Community packs installed.")
    print()
    for _path, data in items:
        _print_dsl_pack(data)
        print(f"  {COMMUNITY_BANNER}")
        print()
    return 0


def _cmd_community_install(pack_id, *, transport):
    from krellbot import community as kb_community

    try:
        path = kb_community.install(pack_id, transport=transport, home=kb_paths.home())
    except kb_community.ForeignUrlError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except kb_community.IndexError_ as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, urllib.error.URLError) as exc:
        print(f"install failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"installed {pack_id} to {path}")
    return 0


# ---- telemetry -------------------------------------------------------------


def cmd_telemetry(args):
    """`krellbot telemetry enable | disable | show`.

    `enable` prints one example payload and only persists the install when
    the operator types `y` on stdin. `disable` flips it off. `show` prints
    the stored record without sending.
    """
    from krellbot import telemetry as kb_telemetry

    if not args:
        print("usage: krellbot telemetry enable | disable | show", file=sys.stderr)
        return 2
    sub = args[0]
    if sub == "enable":
        if kb_telemetry.enable(kb_paths.home()):
            print("telemetry enabled")
            return 0
        print("telemetry not enabled")
        return 0
    if sub == "disable":
        kb_telemetry.disable(kb_paths.home())
        print("telemetry disabled")
        return 0
    if sub == "show":
        kb_telemetry.show(kb_paths.home())
        return 0
    print("usage: krellbot telemetry enable | disable | show", file=sys.stderr)
    return 2


def main(argv):
    if len(argv) >= 2 and argv[1] == "--version":
        from krellbot import __version__

        print(__version__)
        return 0
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
    if cmd == "arm" and len(argv) >= 3:
        return cmd_arm(argv[2:])
    if cmd == "disarm" and len(argv) >= 2:
        return cmd_disarm(argv[2:])
    if cmd == "stop" and len(argv) >= 2:
        return cmd_stop(argv[2:])
    if cmd == "tick" and len(argv) >= 2:
        return cmd_tick(argv[2:])
    if cmd == "status" and len(argv) >= 2:
        return cmd_status(argv[2:])
    if cmd == "journal" and len(argv) >= 2:
        return cmd_journal(argv[2:])
    if cmd == "service" and len(argv) >= 3:
        return cmd_service(argv[2:])
    if cmd == "doctor" and len(argv) >= 2:
        return cmd_doctor(argv[2:])
    if cmd == "ui" and len(argv) >= 2:
        return cmd_ui(argv[2:])
    if cmd == "community" and len(argv) >= 2:
        return cmd_community(argv[2:])
    if cmd == "telemetry" and len(argv) >= 2:
        return cmd_telemetry(argv[2:])
    return usage()


def entry():
    raise SystemExit(main(sys.argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
