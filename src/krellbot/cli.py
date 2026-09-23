"""Krellbot local app. History is local. Orders go only to the Kraken demo host."""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

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
    return Path.home() / ".krellbot" / "packs"


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


def cmd_list():
    user = load_user_packs()
    data = load_catalog()
    if not user and not data:
        return no_packs()
    if user:
        print("Your packs. The format is open.")
        print()
        for pack in user:
            print_pack(pack, True)
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
    user = find_pack(load_user_packs(), key)
    if user:
        print_pack(user, True)
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


def cmd_setup_kraken(path):
    gate(allow_missing=False)
    lines = [
        line.strip()
        for line in Path(path).read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if len(lines) < 2:
        print("Key file needs two lines: API key, then secret.", file=sys.stderr)
        return 2
    state = load_state()
    state["kraken_key"] = lines[0]
    state["kraken_secret"] = lines[1]
    save_state(state)
    print("Kraken key stored on this machine. It was not sent to krellbot.dev.")
    print("The key must be allowed to trade and must not be allowed to withdraw.")
    print("Coinbase is not ready.")
    return 0


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


def usage():
    print(
        "Usage: krellbot list | show <plan> | search <text> | setup <license-key> | setup-kraken <key-file> | run <plan>",
        file=sys.stderr,
    )
    return 2


def main(argv):
    if len(argv) < 2 or argv[1] in {"-h", "--help", "help"}:
        return usage()
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
    return usage()


def entry():
    raise SystemExit(main(sys.argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
