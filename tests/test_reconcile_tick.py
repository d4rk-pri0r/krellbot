"""Tick-time invariants: stop placement, sizing, version adoption, property test.

`tick` is the engine's per-venue loop. The locks, the journal, and the
position-from-journal math all live together here. The property test runs
200 random schedules against a fault-injecting fake to check the two
invariants: at most one order per coid, and every open position has a
resting stop.
"""

from __future__ import annotations

import json
import random
from decimal import Decimal
from pathlib import Path

from krellbot.pack.model import Candle
from krellbot.venues.base import PairRules

# ------------------------------ helpers ------------------------------


def _write_pack(home: Path, *, id_: str = "sma-cross", version: str = "1.0.0", pair: str = "SUIUSD") -> Path:
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": id_,
        "version": version,
        "label": "SMA cross",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": pair}],
    }
    target = packs / f"{id_}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _rules() -> PairRules:
    return PairRules(
        ordermin=Decimal("0.0001"),
        costmin=Decimal("0.5"),
        lot_decimals=8,
        price_decimals=5,
    )


class _StaticReader:
    def __init__(self, candles):
        self.candles = list(candles)

    def __call__(self, venue, pair):
        return list(self.candles)


class _JournalSink:
    def __init__(self):
        self.records: list[dict] = []

    def __call__(self, record):
        self.records.append(record)
        return Path("/dev/null")


class _BaseVenue:
    """Minimal in-memory venue."""

    def __init__(self):
        self.orders: list[dict] = []
        self.fills: list[dict] = []
        self.balances: dict[str, Decimal] = {"USD": Decimal(1000), "SUI": Decimal(0)}

    def rules(self, pair):
        return _rules()

    def snapshot(self):
        from krellbot.venues.base import Balance, Fill, OpenOrder, Truth

        orders = [
            OpenOrder(
                id=o["coid"],
                coid=o["coid"],
                pair=o["pair"],
                side=o["side"],
                qty=o["qty"],
                stop_price=o.get("stop_price"),
            )
            for o in self.orders
        ]
        fills = [
            Fill(
                id=f.get("id", ""),
                coid=f.get("coid", ""),
                pair=f.get("pair", ""),
                side=f.get("side", ""),
                qty=f.get("qty", Decimal(0)),
                price=f.get("price", Decimal(0)),
                ts_ms=int(f.get("ts_ms", 0)),
            )
            for f in self.fills
        ]
        bals = [Balance(asset=k, free=v) for k, v in self.balances.items() if v > 0]
        return Truth(balances=bals, open_orders=orders, recent_fills=fills)

    def place_entry_with_stop(self, coid, qty, stop, *, pair):
        self.orders.append({"coid": coid, "pair": pair, "side": "buy", "qty": qty, "stop_price": stop})
        self.balances["SUI"] = self.balances.get("SUI", Decimal(0)) + qty
        self.fills.append(
            {"id": coid, "coid": coid, "pair": pair, "side": "buy", "qty": qty, "price": Decimal(10), "ts_ms": 0}
        )
        return {
            "id": coid,
            "coid": coid,
            "pair": pair,
            "side": "buy",
            "qty": qty,
            "filled_qty": qty,
            "stop_price": stop,
        }

    def place_stop(self, coid, qty, stop, *, pair):
        self.orders.append({"coid": coid, "pair": pair, "side": "sell", "qty": qty, "stop_price": stop})

    def place_exit(self, coid, qty, *, pair):
        self.fills.append(
            {"id": coid, "coid": coid, "pair": pair, "side": "sell", "qty": qty, "price": Decimal(10), "ts_ms": 0}
        )
        self.orders = [o for o in self.orders if not (o["pair"] == pair and o.get("side") == "buy")]
        return {"id": coid, "coid": coid, "pair": pair, "side": "sell", "qty": qty, "filled_qty": qty}

    def cancel_stops(self, pair):
        self.orders = [o for o in self.orders if not (o["pair"] == pair and o.get("stop_price") is not None)]

    def raise_stop(self, pair, new_stop):
        for o in self.orders:
            if o["pair"] == pair and o.get("stop_price") is not None:
                o["stop_price"] = max(o["stop_price"], new_stop)

    def order_by_coid(self, coid):
        for o in self.orders:
            if o["coid"] == coid:
                return o
        return None

    def check_key(self):
        from krellbot.venues.base import KeyPerms

        return KeyPerms(can_trade=True, can_withdraw=False)

    def record_stop_fill(self, coid, qty, price, *, pair):
        # Mirror a stop fill on state. Used by tests that exercise the engine.
        self.orders = [o for o in self.orders if not (o["pair"] == pair and o.get("stop_price") is not None)]
        self.balances["SUI"] = self.balances.get("SUI", Decimal(0)) - qty
        self.fills.append(
            {
                "id": coid,
                "coid": coid,
                "pair": pair,
                "side": "sell",
                "qty": qty,
                "price": price,
                "ts_ms": 0,
                "kind": "stop",
            }
        )


# ------------------------------- tests --------------------------------


def test_position_without_stop_gets_stop_next_tick(home):
    """If a position is open with no resting stop, the tick must place one."""
    from krellbot import journal
    from krellbot.config import load_config, save_config
    from krellbot.run import arm_pack, tick

    pack_path = _write_pack(home)
    arm_pack(pack_path, venue="kraken", mode="paper", paper_balance=Decimal(1000), requires_license=False)
    journal.append(
        {
            "ts": 1,
            "kind": "tick",
            "venue": "kraken",
            "pack": "sma-cross",
            "bar_ts": 1,
            "detail": {"pair": "SUIUSD", "entry_qty": "5", "exit_qty": "0", "stop_qty": "0"},
        }
    )

    config = load_config(home)
    for armed in config.armed:
        if armed.venue == "kraken":
            armed.owned_qty = Decimal(5)
    save_config(home, config)

    candles = [
        Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100)),
    ]
    venue = _BaseVenue()
    venue.balances["SUI"] = Decimal(5)
    journal = _JournalSink()
    rc = tick(venue="kraken", venue_obj=venue, reader=_StaticReader(candles), journal_sink=journal, clock=lambda: 0)
    assert rc == 0
    tick_records = [r for r in journal.records if r.get("kind") == "tick"]
    assert tick_records, "engine must journal a tick record"
    assert tick_records[0]["detail"].get("entry_coid"), "ensure-stop coid missing"
    assert tick_records[0]["detail"].get("no_double_order") is True


def test_stop_placement_failure_exits_position(home):
    """If `place_entry_with_stop` (called to establish the stop) raises, the
    engine market-exits the owned qty in the same tick.
    """
    from krellbot.run import arm_pack, tick

    pack_path = _write_pack(home)
    arm_pack(pack_path, venue="kraken", mode="paper", paper_balance=Decimal(1000), requires_license=False)
    from krellbot import journal

    journal.append(
        {
            "ts": 1,
            "kind": "tick",
            "venue": "kraken",
            "pack": "sma-cross",
            "bar_ts": 1,
            "detail": {"pair": "SUIUSD", "entry_qty": "5", "exit_qty": "0", "stop_qty": "0"},
        }
    )

    # Pre-seed a position with no stop.
    from krellbot.config import load_config, save_config

    config = load_config(home)
    for armed in config.armed:
        if armed.venue == "kraken":
            armed.owned_qty = Decimal(5)
            armed.owned_qty_initial = True
    save_config(home, config)

    candles = [
        Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100)),
    ]

    class _FailingPlace(_BaseVenue):
        def __init__(self):
            super().__init__()
            self.balances["SUI"] = Decimal(5)

        def place_stop(self, coid, qty, stop, *, pair):
            raise RuntimeError("simulated stop placement failure")

        def place_entry_with_stop(self, coid, qty, stop, *, pair):
            raise RuntimeError("simulated stop placement failure")

        def place_exit(self, coid, qty, *, pair):
            self.exit_calls = getattr(self, "exit_calls", 0) + 1
            return super().place_exit(coid, qty, pair=pair)

    venue = _FailingPlace()
    journal = _JournalSink()
    rc = tick(venue="kraken", venue_obj=venue, reader=_StaticReader(candles), journal_sink=journal, clock=lambda: 0)
    assert rc == 0
    # The market-exit must have been issued.
    assert venue.exit_calls == 1


def test_second_pack_same_pair_refused_at_arm_and_tick(home):
    """Two packs on the same venue+pair: arm refuses; tick skips."""
    from krellbot.run import arm_pack, tick

    p1 = _write_pack(home, id_="pack-a", pair="SUIUSD")
    rc1 = arm_pack(p1, venue="kraken", mode="paper", paper_balance=Decimal(1000), requires_license=False)
    assert rc1 == 0

    p2 = _write_pack(home, id_="pack-b", pair="SUIUSD")
    rc2 = arm_pack(p2, venue="kraken", mode="paper", paper_balance=Decimal(1000), requires_license=False)
    assert rc2 == 1

    # tick runs without raising for the armed pack.
    candles = [
        Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100))
    ]
    venue = _BaseVenue()
    journal = _JournalSink()
    rc = tick(venue="kraken", venue_obj=venue, reader=_StaticReader(candles), journal_sink=journal, clock=lambda: 0)
    assert rc == 0
    # The second pack (refused at arm) was never armed.
    from krellbot.config import load_config

    config = load_config(home)
    armed_ids = {a.pack_id for a in config.armed}
    assert "pack-a" in armed_ids
    assert "pack-b" not in armed_ids


def test_pending_version_adopted_only_when_flat(home):
    """A pending version is swapped in only when the pack is flat.

    If the pack is long, the pending version stays put and the journal
    records that adoption was deferred.
    """
    from krellbot.config import load_config, save_config
    from krellbot.run import arm_pack, tick

    p1 = _write_pack(home, id_="v1", version="1.0.0", pair="SUIUSD")
    arm_pack(p1, venue="kraken", mode="paper", paper_balance=Decimal(1000), requires_license=False)
    from krellbot import journal

    journal.append(
        {
            "ts": 1,
            "kind": "tick",
            "venue": "kraken",
            "pack": "v1",
            "bar_ts": 1,
            "detail": {"pair": "SUIUSD", "entry_qty": "5", "exit_qty": "0", "stop_qty": "0"},
        }
    )

    # Mark a pending version.
    config = load_config(home)
    for armed in config.armed:
        if armed.pack_id == "v1":
            armed.pending_version = "2.0.0"
    save_config(home, config)

    # While long: pending stays.
    config = load_config(home)
    for armed in config.armed:
        if armed.pack_id == "v1":
            armed.owned_qty = Decimal(5)
            armed.owned_qty_initial = True
    save_config(home, config)

    candles = [
        Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100)),
    ]
    venue = _BaseVenue()
    venue.balances["SUI"] = Decimal(5)
    journal_sink = _JournalSink()
    tick(venue="kraken", venue_obj=venue, reader=_StaticReader(candles), journal_sink=journal_sink, clock=lambda: 0)

    config = load_config(home)
    for armed in config.armed:
        if armed.pack_id == "v1":
            assert armed.pending_version == "2.0.0"
            assert armed.pack_version == "1.0.0"  # not adopted

    # Now flatten: pending is adopted on the next tick.
    config = load_config(home)
    for armed in config.armed:
        if armed.pack_id == "v1":
            armed.owned_qty = Decimal(0)
            armed.owned_qty_initial = True
    save_config(home, config)
    venue.balances["SUI"] = Decimal(0)
    journal.append(
        {
            "ts": 2,
            "kind": "tick",
            "venue": "kraken",
            "pack": "v1",
            "bar_ts": 2,
            "detail": {"pair": "SUIUSD", "entry_qty": "0", "exit_qty": "5", "stop_qty": "0"},
        }
    )

    candles2 = [
        Candle(
            ts_ms=3_600_000, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100)
        )
    ]
    tick(
        venue="kraken",
        venue_obj=venue,
        reader=_StaticReader(candles2),
        journal_sink=journal_sink,
        clock=lambda: 3_600_000 // 1000,
    )
    config = load_config(home)
    for armed in config.armed:
        if armed.pack_id == "v1":
            assert armed.pending_version is None
            assert armed.pack_version == "2.0.0"


def test_engine_never_sells_more_than_pack_bought(home):
    """The engine never sells more base than this pack's journal says it filled."""
    from krellbot.run import arm_pack, tick

    pack_path = _write_pack(home)
    arm_pack(pack_path, venue="kraken", mode="paper", paper_balance=Decimal(1000), requires_license=False)

    # Two consecutive entry bars, then an exit. Engine must not double-count.
    candles = [
        Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100)),
        Candle(
            ts_ms=3_600_000, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100)
        ),
        Candle(
            ts_ms=7_200_000,
            open=Decimal(11),
            high=Decimal(12),
            low=Decimal("10.5"),
            close=Decimal(12),
            volume=Decimal(100),
        ),  # entry
        Candle(
            ts_ms=10_800_000,
            open=Decimal(11),
            high=Decimal(12),
            low=Decimal("10.5"),
            close=Decimal(12),
            volume=Decimal(100),
        ),  # flat again
        Candle(
            ts_ms=14_400_000,
            open=Decimal(10),
            high=Decimal(10),
            low=Decimal("8.5"),
            close=Decimal(9),
            volume=Decimal(100),
        ),  # exit
    ]
    venue = _BaseVenue()
    venue.balances["USD"] = Decimal(1000)
    journal = _JournalSink()

    rc = tick(venue="kraken", venue_obj=venue, reader=_StaticReader(candles), journal_sink=journal, clock=lambda: 0)
    assert rc == 0
    # Count sells: there must be at most one sell, and its qty must match the buy qty.
    sells = [f for f in venue.fills if f["side"] == "sell" and f.get("kind") != "stop"]
    buys = [f for f in venue.fills if f["side"] == "buy"]
    assert len(buys) <= 1
    if sells:
        assert len(sells) == 1
        assert sells[0]["qty"] == buys[0]["qty"]


def test_missed_bars_coalesce_to_latest_closed_bar(home):
    """If the engine skipped many bars, evaluating the latest closed bar
    passes ALL prior bars into evaluate.run so indicator state includes them.
    The journal records ONE tick per bar (the latest).
    """
    from krellbot.run import arm_pack, tick

    pack_path = _write_pack(home)
    arm_pack(pack_path, venue="kraken", mode="paper", paper_balance=Decimal(1000), requires_license=False)

    # 8 closed bars total — the last two are the most recent.
    candles = []
    for i in range(8):
        candles.append(
            Candle(
                ts_ms=i * 3_600_000,
                open=Decimal(10),
                high=Decimal(11),
                low=Decimal(9),
                close=Decimal(10 if i < 6 else 12),
                volume=Decimal(100),
            )
        )
    venue = _BaseVenue()
    journal = _JournalSink()
    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=_StaticReader(candles),
        journal_sink=journal,
        clock=lambda: 8 * 3_600_000 // 1000,
    )
    assert rc == 0
    # Exactly one tick journal row.
    ticks = [r for r in journal.records if r.get("kind") == "tick"]
    assert len(ticks) == 1
    assert ticks[0]["bar_ts"] == candles[-1].ts_ms


def test_property_random_schedules_invariant(home):
    """Property test: 200 schedules from random.Random(0).

    At tick end, at most one order per coid AND every open position has a
    resting stop. The fake can fail place_entry / place_exit / raise_stop /
    record_stop_fill in random ways; the engine must remain correct.
    """
    from krellbot.config import load_config, save_config
    from krellbot.run import arm_pack, tick

    rng = random.Random(0)
    for schedule_idx in range(200):
        # Build a pack and arm it.
        pack_id = f"sched-{schedule_idx}"
        path = _write_pack(home, id_=pack_id, version="1.0.0", pair="SUIUSD")
        arm_pack(path, venue="kraken", mode="paper", paper_balance=Decimal(1000), requires_license=False)

        # Build a candle series that may include gaps and trigger bars.
        n_bars = rng.randint(3, 12)
        candles = []
        for j in range(n_bars):
            base = Decimal(10) + Decimal(rng.randint(-2, 2))
            candles.append(
                Candle(
                    ts_ms=j * 3_600_000,
                    open=base,
                    high=base + Decimal("0.5"),
                    low=base - Decimal("0.5"),
                    close=base + Decimal(rng.choice([-1, 0, 1])),
                    volume=Decimal(100),
                )
            )

        # Build a fault-injecting fake.
        class _FaultFake(_BaseVenue):
            def __init__(self, rng, fail_rate=0.2):
                super().__init__()
                self._rng = rng
                self._fail_rate = fail_rate
                self.calls: list[tuple[str, str]] = []

            def _maybe_fail(self, op, coid):
                self.calls.append((op, coid))
                if self._rng.random() < self._fail_rate:
                    raise RuntimeError(f"fault: {op} {coid}")

            def place_entry_with_stop(self, coid, qty, stop, *, pair):
                self._maybe_fail("entry", coid)
                return super().place_entry_with_stop(coid, qty, stop, pair=pair)

            def place_exit(self, coid, qty, *, pair):
                self._maybe_fail("exit", coid)
                return super().place_exit(coid, qty, pair=pair)

            def raise_stop(self, pair, new_stop):
                self._maybe_fail("raise", f"{pair}-{new_stop}")
                return super().raise_stop(pair, new_stop)

            def record_stop_fill(self, coid, qty, price, *, pair):
                self._maybe_fail("stop_fill", coid)
                return super().record_stop_fill(coid, qty, price, pair=pair)

        venue = _FaultFake(rng)
        journal = _JournalSink()

        reader_candles = list(candles)
        bar_ts_ms = int(reader_candles[-1].ts_ms // 1000)
        for _ in range(rng.randint(1, 4)):
            tick(
                venue="kraken",
                venue_obj=venue,
                reader=_StaticReader(reader_candles),
                journal_sink=journal,
                clock=lambda v=bar_ts_ms: v,
            )

        # Invariant 1: at most one order per coid.
        coids = [o["coid"] for o in venue.orders]
        assert len(coids) == len(set(coids)), f"duplicate coid in orders: {coids}"

        # Invariant 2: every open position has a resting stop.
        opens = [o for o in venue.orders if o.get("side") == "buy"]
        for o in opens:
            assert o.get("stop_price") is not None, f"open position without stop: {o}"

        # Reset config and state between schedules to avoid cross-pollution.
        config = load_config(home)
        config.armed = []
        config.live_first_armed = False
        save_config(home, config)
        # Wipe paper state file if any.
        run = home / "run"
        if run.exists():
            for child in run.iterdir():
                if child.name.startswith("paper-"):
                    child.unlink()
