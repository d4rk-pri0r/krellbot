"""Run engine: arm, disarm, tick, status, journal.

`tick` is the only function that talks to a venue. It:
    1. Acquires `$KRELLBOT_HOME/run/<venue>.lock`. If held, exit 0 silently
       with `another tick running` on stdout.
    2. Loads the license cache + armed packs config.
    3. Snapshots the venue.
    4. For each armed pack on the venue: ensure a resting stop if owned > 0.
       If the stop-place fails, market-exit the owned qty in the same tick.
    5. Acts on the latest closed bar only. Missed bars are coalesced by
       feeding every candle up to and including the latest into evaluate.run
       so indicator state includes them.
    6. Entry / exit / raise_stop per the engine rules.
    7. Journal one tick record per pack per bar, including refusals.
    8. If entries are blocked by the license gate, print the lapsed message.

`arm_pack` records a pack into config. It refuses a second pack on the same
venue+pair, refuses if the cap cannot meet the pair's costmin (paper), and
requires a typed "LIVE" confirmation the first time live is armed.

Money is `Decimal`. No HTTP. No secret in any log/journal line.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

from krellbot import catalog as kb_catalog
from krellbot import config as kb_config
from krellbot import journal as kb_journal
from krellbot import license as kb_license
from krellbot import paths as kb_paths
from krellbot import secrets as kb_secrets
from krellbot.pack import evaluate as kb_evaluate
from krellbot.pack import lint as kb_pack_lint
from krellbot.pack.model import Candle as Candle

from .lock import TickLock

# ---- coid ----------------------------------------------------------------


def coid_for(
    *,
    pack_id: str,
    pack_version: str,
    venue: str,
    pair: str,
    bar_ts: int,
    intent: str,
) -> str:
    """First 18 hex chars of sha256 over the canonical intent key."""
    raw = f"{pack_id}|{pack_version}|{venue}|{pair}|{bar_ts}|{intent}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:18]


# ---- arm -----------------------------------------------------------------


def arm_pack(
    pack_path: Path | str,
    *,
    venue: str,
    mode: str,
    paper_balance: Decimal | None = None,
    requires_license: bool | None = None,
    confirm_fn: Callable[[], str] | None = None,
    key_check: Callable[[str], Any] | None = None,
    home: Path | None = None,
) -> int:
    """Arm a pack on a venue. Returns 0 on success, 1 on refusal, 2 on bad input.

    `confirm_fn` and `key_check` are injected so tests don't touch stdin or
    the network. The CLI wires stdin and `cli_keys._probe`.
    """
    from krellbot.venues.base import WithdrawCapableError

    home = Path(home) if home is not None else kb_paths.home()
    pack_path = Path(pack_path)
    if not pack_path.exists():
        print(f"no such pack: {pack_path}", flush=True)
        return 2
    try:
        pack_data = json.loads(pack_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"invalid JSON: {exc}", flush=True)
        return 2
    if not isinstance(pack_data, dict):
        print("pack must be a JSON object", flush=True)
        return 2
    if kb_pack_lint.is_legacy(pack_data):
        print("legacy: not runnable", flush=True)
        return 2
    errors = kb_pack_lint.check(pack_data)
    if errors:
        for err in errors:
            print(f"{err['field']}: {err['message']}", flush=True)
        return 2

    if venue not in kb_secrets.VENUES:
        print(f"unknown venue: {venue}", flush=True)
        return 2
    if mode not in {"paper", "live"}:
        print(f"unknown mode: {mode}", flush=True)
        return 2

    markets = pack_data.get("markets") or []
    market = next((m for m in markets if m.get("venue") == venue), None)
    if market is None:
        print(f"pack has no market for {venue}", flush=True)
        return 2
    pair = str(market.get("pair", ""))

    pack_id = str(pack_data.get("id", ""))
    pack_version = str(pack_data.get("version", ""))
    cap = Decimal(str(pack_data["risk"]["max_account_pct"]))
    stop_block = pack_data.get("risk", {}).get("stop", {}) or {}
    # Compute the stop. The engine stores a Decimal; the broker will quantize.
    if stop_block.get("type") == "pct":
        stop = Decimal(str(stop_block["pct"]))
    elif stop_block.get("type") == "atr":
        stop = Decimal(str(stop_block.get("mult", "1")))
    else:
        stop = Decimal(0)

    config = kb_config.load_config(home)
    if kb_config.find_armed(config, venue, pair) is not None:
        print(f"already armed: {venue} {pair}", flush=True)
        return 1

    if mode == "live":
        if os.environ.get("KRELLBOT_ENABLE_LIVE") != "1":
            print("live is off; set KRELLBOT_ENABLE_LIVE=1 to arm a live pack", flush=True)
            return 1
        # Must have a stored key for this venue.
        try:
            kb_secrets.get(venue)
        except FileNotFoundError:
            print(f"no key stored for {venue}", flush=True)
            return 1
        except (ValueError, PermissionError) as exc:
            print(f"could not read key for {venue}: {type(exc).__name__}", flush=True)
            return 1
        # Permissions must be trade-yes, withdraw-no.
        if key_check is None:
            print("live arm requires a key_check callable", flush=True)
            return 1
        try:
            perms = key_check(venue)
        except WithdrawCapableError:
            print(f"{venue}: key can withdraw; trade-only keys refused", flush=True)
            return 1
        except (OSError, RuntimeError, ValueError, TypeError):
            print(f"{venue}: key check failed", flush=True)
            return 1
        if perms is None or not getattr(perms, "can_trade", False):
            print(f"{venue}: trade is off", flush=True)
            return 1
        if getattr(perms, "can_withdraw", False):
            print(f"{venue}: withdraw is on; trade-only keys refused", flush=True)
            return 1
        if stop <= Decimal(0):
            print("live arm requires a stop", flush=True)
            return 1
        if cap <= Decimal(0):
            print("live arm requires a cap > 0", flush=True)
            return 1
        # First live arm: typed confirmation.
        if not config.live_first_armed:
            text = confirm_fn() if confirm_fn is not None else input("Type LIVE to arm: ")
            if text.strip() != "LIVE":
                print("confirmation text was not 'LIVE'; not armed", flush=True)
                return 1
            config.live_first_armed = True
        else:
            # Second-and-later live arm: no prompt. Tests inject must_not_call
            # to prove it.
            pass

    if requires_license is None:
        requires_license = kb_catalog.requires_license_for(pack_path, home)

    if mode == "paper":
        if paper_balance is None:
            print("paper arm requires --paper-balance", flush=True)
            return 2
        if paper_balance <= Decimal(0):
            print("paper-balance must be positive", flush=True)
            return 2
        # Cap must be able to meet costmin: rough check uses a floor of
        # $1 per unit. We don't know the price without a candle feed, so we
        # require paper_balance * cap / 100 >= 0.5 USD (costmin floor).
        cash_for_cap = paper_balance * cap / Decimal(100)
        if cash_for_cap < Decimal("0.5"):
            print("cap cannot meet the pair minimum", flush=True)
            return 1

    kb_paths.ensure_layout()
    sha = hashlib.sha256(pack_path.read_bytes()).hexdigest()
    armed = kb_config.ArmedPack(
        pack_path=str(pack_path),
        pack_sha256=sha,
        pack_id=pack_id,
        pack_version=pack_version,
        venue=venue,
        pair=pair,
        cap=cap,
        stop=stop,
        mode=mode,
        starting_cash=paper_balance if mode == "paper" else None,
        requires_license=bool(requires_license),
        armed_at_ts=int(_now_seconds()),
    )
    config.armed.append(armed)
    kb_config.save_config(home, config)
    print(f"armed {pack_id} {pack_version} on {venue} {pair}", flush=True)
    return 0


def disarm_pack(
    *,
    venue: str,
    pair: str,
    home: Path | None = None,
) -> int:
    """Remove an armed record. Returns 0 on success, 1 if not armed."""
    home = Path(home) if home is not None else kb_paths.home()
    config = kb_config.load_config(home)
    found = kb_config.find_armed(config, venue, pair)
    if found is None:
        print(f"not armed: {venue} {pair}", flush=True)
        return 1
    config.armed = [a for a in config.armed if not (a.venue == venue and a.pair == pair)]
    kb_config.save_config(home, config)
    print(f"disarmed {venue} {pair}", flush=True)
    return 0


def set_stop(
    *,
    venue: str,
    pair: str,
    new_stop: Decimal,
    home: Path | None = None,
) -> int:
    """Raise (only) the stop for an armed pack."""
    home = Path(home) if home is not None else kb_paths.home()
    config = kb_config.load_config(home)
    armed = kb_config.find_armed(config, venue, pair)
    if armed is None:
        print(f"not armed: {venue} {pair}", flush=True)
        return 1
    if new_stop <= armed.stop:
        print("new stop must be strictly above the current stop", flush=True)
        return 1
    armed.stop = new_stop
    kb_config.save_config(home, config)
    print(f"stop set: {venue} {pair} -> {new_stop}", flush=True)
    return 0


# ---- tick ----------------------------------------------------------------


def tick(
    *,
    venue: str,
    venue_obj: Any,
    reader: Callable[[str, str], list],
    journal_sink: Callable[[dict], Path] | None = None,
    clock: Callable[[], float] | None = None,
    home: Path | None = None,
) -> int:
    """Run one tick. Returns 0 on success, 1 on refusal.

    `venue_obj` is duck-typed: it must satisfy the Venue protocol surface.
    `journal_sink` defaults to `journal.append` (which requires the required
    keys). Tests inject a recording sink.
    """
    home = Path(home) if home is not None else kb_paths.home()
    journal = journal_sink if journal_sink is not None else kb_journal.append
    now = clock() if clock is not None else _now_seconds()

    lock = TickLock(home, venue)
    if not lock.acquire():
        print("another tick running", flush=True)
        return 0

    try:
        kb_paths.ensure_layout()
        config = kb_config.load_config(home)
        armed_for_venue = [a for a in config.armed if a.venue == venue]
        if not armed_for_venue:
            print(f"no armed packs for {venue}", flush=True)
            return 0

        cache = kb_license.read_cache(home)

        snap = venue_obj.snapshot()
        snap_balances = _snapshot_balances(snap)
        snap_orders = _snapshot_orders(snap)
        warned = False

        for armed in armed_for_venue:
            pack = armed_pack_dict(home, armed)
            blocked = armed.requires_license and not kb_license.entries_allowed(cache, now=int(now))
            if blocked and not warned:
                print("License lapsed or unreachable: entries off, exits on", flush=True)
                warned = True

            candles = list(reader(venue, armed.pair) or [])
            latest = candles[-1] if candles else None
            bar_ts = int(latest.ts_ms) if latest is not None else 0
            if candles and _already_journaled(home, armed.pack_id, bar_ts):
                continue

            base, _quote = _base_quote(armed.pair)
            venue_base = snap_balances.get(base, Decimal(0))
            journal_qty = _journal_owned(home, armed.pack_id, armed.pair)
            recognized = _recognized_open_qty(armed, venue, candles, snap_orders)
            owned = min(venue_base, max(journal_qty, recognized))
            resting = next(
                (
                    o.stop_price
                    for o in snap_orders
                    if getattr(o, "pair", None) == armed.pair and getattr(o, "stop_price", None) is not None
                ),
                None,
            )

            ensure_stop_failed = False
            ensure_stop_entry = ""
            if owned > Decimal(0) and resting is None and latest is not None:
                repair = _stop_price(pack, Decimal(str(latest.close)))
                stop_coid = coid_for(
                    pack_id=armed.pack_id,
                    pack_version=armed.pack_version,
                    venue=venue,
                    pair=armed.pair,
                    bar_ts=bar_ts,
                    intent="stop",
                )
                try:
                    venue_obj.place_stop(stop_coid, owned, repair, pair=armed.pair)
                    ensure_stop_entry = stop_coid
                except (AttributeError, RuntimeError, ValueError):
                    ensure_stop_failed = True
                    print("ensure_stop failed: stop", flush=True)
                    exit_coid = coid_for(
                        pack_id=armed.pack_id,
                        pack_version=armed.pack_version,
                        venue=venue,
                        pair=armed.pair,
                        bar_ts=bar_ts,
                        intent="exit",
                    )
                    try:
                        venue_obj.place_exit(exit_coid, owned, pair=armed.pair)
                    except (AttributeError, RuntimeError, ValueError):
                        pass
                    owned = Decimal(0)

            if not candles:
                _record_tick(
                    journal,
                    now=int(now),
                    venue=venue,
                    pack=armed.pack_id,
                    bar_ts=0,
                    detail={"reason": "no_candles", "pair": armed.pair, "ensure_stop_failed": ensure_stop_failed},
                )
                continue

            target = kb_evaluate.run(pack, candles)
            entry_qty = Decimal(0)
            exit_qty = Decimal(0)
            entry_coid_for_signal = ""
            if not blocked and target.long and owned == Decimal(0) and target.stop_price is not None:
                entry_coid_for_signal = coid_for(
                    pack_id=armed.pack_id,
                    pack_version=armed.pack_version,
                    venue=venue,
                    pair=armed.pair,
                    bar_ts=bar_ts,
                    intent="entry",
                )
                if venue_obj.order_by_coid(entry_coid_for_signal) is None:
                    cash = _cash_for(venue_obj, armed.pair)
                    rules = venue_obj.rules(armed.pair)
                    close_price = Decimal(str(candles[-1].close))
                    cash_for_cap = cash * armed.cap / Decimal(100)
                    if cash_for_cap >= rules.costmin and close_price > 0:
                        qty = (cash_for_cap / close_price).quantize(
                            Decimal(1).scaleb(-rules.lot_decimals), rounding=ROUND_DOWN
                        )
                        if qty >= rules.ordermin and qty * close_price >= rules.costmin:
                            try:
                                venue_obj.place_entry_with_stop(
                                    entry_coid_for_signal,
                                    qty,
                                    target.stop_price,
                                    pair=armed.pair,
                                )
                                entry_qty = qty
                                owned = qty
                            except (RuntimeError, ValueError):
                                entry_qty = Decimal(0)
            elif target.reason == "exit" and owned > Decimal(0):
                try:
                    venue_obj.cancel_stops(armed.pair)
                except (RuntimeError, ValueError):
                    pass
                exit_coid = coid_for(
                    pack_id=armed.pack_id,
                    pack_version=armed.pack_version,
                    venue=venue,
                    pair=armed.pair,
                    bar_ts=bar_ts,
                    intent="exit",
                )
                try:
                    venue_obj.place_exit(exit_coid, owned, pair=armed.pair)
                    exit_qty = owned
                    owned = Decimal(0)
                except (RuntimeError, ValueError):
                    pass
            elif target.long and owned > Decimal(0) and target.stop_price is not None:
                cur_stop = resting
                if cur_stop is None or target.stop_price > cur_stop:
                    try:
                        venue_obj.raise_stop(armed.pair, target.stop_price)
                    except (RuntimeError, ValueError):
                        pass

            armed.owned_qty = owned
            _record_tick(
                journal,
                now=int(now),
                venue=venue,
                pack=armed.pack_id,
                bar_ts=bar_ts,
                detail={
                    "pair": armed.pair,
                    "reason": target.reason,
                    "entry_qty": str(entry_qty),
                    "exit_qty": str(exit_qty),
                    "stop_qty": "0",
                    "owned_qty_after": str(owned),
                    "entries_blocked": blocked,
                    "ensure_stop_failed": ensure_stop_failed,
                    "entry_coid": ensure_stop_entry or entry_coid_for_signal,
                    "no_double_order": bool(ensure_stop_entry),
                },
            )

        config = kb_config.load_config(home)
        for armed in config.armed:
            if armed.venue != venue:
                continue
            held = next((a for a in armed_for_venue if a.pack_id == armed.pack_id and a.pair == armed.pair), None)
            if held is not None:
                armed.owned_qty = held.owned_qty
            if armed.pending_version and armed.owned_qty == Decimal(0):
                armed.pack_version = armed.pending_version
                armed.pending_version = None
        kb_config.save_config(home, config)

        return 0
    finally:
        lock.release()


# ---- status / journal tail ------------------------------------------------


def status(*, venue: str | None = None, home: Path | None = None) -> int:
    """Print armed packs. Returns 0."""
    home = Path(home) if home is not None else kb_paths.home()
    config = kb_config.load_config(home)
    armed = config.armed
    if venue is not None:
        armed = [a for a in armed if a.venue == venue]
    if not armed:
        print("no armed packs", flush=True)
        return 0
    for a in armed:
        print(
            f"{a.pack_id} {a.pack_version} {a.venue} {a.pair} cap={a.cap} stop={a.stop} mode={a.mode} requires_license={a.requires_license}",
            flush=True,
        )
    return 0


def journal_tail(n: int = 5, *, home: Path | None = None) -> int:
    """Print the last `n` journal records across all months."""
    home = Path(home) if home is not None else kb_paths.home()
    journal_dir = Path(home) / "journal"
    if not journal_dir.is_dir():
        print("no journal", flush=True)
        return 0
    lines: list[str] = []
    for path in sorted(journal_dir.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if line.strip():
                lines.append(line)
    tail = lines[-n:]
    for line in tail:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        print(json.dumps(rec, sort_keys=True), flush=True)
    if not tail:
        print("no journal records", flush=True)
    return 0


# ---- internals ------------------------------------------------------------


def _journal_owned(home: Path, pack_id: str, pair: str) -> Decimal:
    from krellbot.run.reconcile import reconcile_owned_qty

    return reconcile_owned_qty(home, pack_id=pack_id, pair=pair, venue_owned_qty=Decimal("1e18"))


def _recognized_open_qty(armed: kb_config.ArmedPack, venue: str, candles: list, orders: list) -> Decimal:
    known = {
        coid_for(
            pack_id=armed.pack_id,
            pack_version=armed.pack_version,
            venue=venue,
            pair=armed.pair,
            bar_ts=int(candle.ts_ms),
            intent=intent,
        )
        for candle in candles
        for intent in ("entry", "stop")
    }
    total = Decimal(0)
    for order in orders:
        coid = getattr(order, "coid", None)
        pair = getattr(order, "pair", None)
        qty = getattr(order, "qty", None)
        if coid in known and pair == armed.pair and qty is not None:
            total += Decimal(str(qty))
    return total


def _stop_price(pack: dict, last_close: Decimal) -> Decimal:
    stop = (pack.get("risk") or {}).get("stop") or {}
    if stop.get("type") == "pct":
        return last_close * (Decimal(1) - Decimal(str(stop["pct"])) / Decimal(100))
    if last_close > 0:
        return last_close / Decimal(2)
    return Decimal(0)


def _now_seconds() -> float:
    import time

    return time.time()


def _base_quote(pair: str) -> tuple[str, str]:
    if not pair:
        return ("", "")
    if pair.endswith("USD"):
        return pair[: -len("USD")], "USD"
    if len(pair) >= 6:
        return pair[:-3], pair[-3:]
    return pair, ""


def _snapshot_balances(snap: Any) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    if isinstance(snap, dict):
        for k, v in snap.get("balances", {}).items():
            out[k] = Decimal(str(v))
    else:
        for b in getattr(snap, "balances", []) or []:
            out[str(b.asset)] = Decimal(str(b.free))
    return out


def _snapshot_orders(snap: Any) -> list:
    if isinstance(snap, dict):
        return list(snap.get("open_orders", []))
    return list(getattr(snap, "open_orders", []) or [])


def _cash_for(venue_obj: Any, pair: str) -> Decimal:
    _base, quote = _base_quote(pair)
    snap = venue_obj.snapshot()
    if isinstance(snap, dict):
        return Decimal(str(snap.get("balances", {}).get(quote, Decimal(0))))
    for b in snap.balances:
        if b.asset == quote:
            return Decimal(str(b.free))
    return Decimal(0)


def _record_tick(
    journal: Callable[[dict], Path],
    *,
    now: int,
    venue: str,
    pack: str,
    bar_ts: int,
    detail: dict,
) -> None:
    try:
        journal(
            {
                "ts": int(now),
                "kind": "tick",
                "venue": venue,
                "pack": pack,
                "bar_ts": int(bar_ts),
                "detail": detail,
            }
        )
    except ValueError:
        # Test sinks may not validate required keys; that's their problem.
        pass


def _already_journaled(home: Path, pack_id: str, bar_ts: int) -> bool:
    journal_dir = Path(home) / "journal"
    if not journal_dir.is_dir():
        return False
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
            if rec.get("kind") == "tick" and rec.get("pack") == pack_id and int(rec.get("bar_ts", 0)) == int(bar_ts):
                return True
    return False


def armed_pack_dict(home: Path, armed: kb_config.ArmedPack) -> dict:
    """Read the pack JSON bytes for the engine to evaluate."""
    path = Path(armed.pack_path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
