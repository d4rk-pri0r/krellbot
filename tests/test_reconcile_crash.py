"""Crash safety: a kill between place and journal must not double-order.

The engine's journal is the source of truth for what was sent. After a crash,
the paper venue's persisted state still holds the entry. The next tick must
see the position is open with a stop already in place and must NOT issue a
second entry. It must journal a tick record for the latest closed bar so the
subsequent ticks don't replay it.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from krellbot.pack.model import Candle


def _pack(home: Path) -> Path:
    import json

    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": "sma-cross",
        "version": "1.0.0",
        "label": "SMA cross",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    target = packs / "sma_cross.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


class _StaticReader:
    def __init__(self, candles):
        self.candles = list(candles)

    def __call__(self, venue, pair):
        return list(self.candles)


class _JournalSpy:
    def __init__(self):
        self.records: list[dict] = []

    def __call__(self, record):
        self.records.append(record)
        return Path("/dev/null")


class _CrashAfterPlaceVenue:
    """A venue that records place_entry_with_stop then raises before returning."""

    def __init__(self, candles):
        self._candles = candles
        self.entry_calls: list[str] = []
        self.exit_calls: list[str] = []
        self.snap_calls = 0
        self._balances: dict[str, Decimal] = {"USD": Decimal(1000), "SUI": Decimal(0)}
        self._orders: list[dict] = []
        self._fills: list[dict] = []

    def rules(self, pair):
        from krellbot.venues.base import PairRules

        return PairRules(
            ordermin=Decimal("0.0001"),
            costmin=Decimal("0.5"),
            lot_decimals=8,
            price_decimals=5,
        )

    def snapshot(self):
        from krellbot.venues.base import Balance, Fill, OpenOrder, Truth

        self.snap_calls += 1
        orders = [
            OpenOrder(
                id=o["coid"],
                coid=o["coid"],
                pair=o["pair"],
                side=o["side"],
                qty=o["qty"],
                stop_price=o.get("stop_price"),
            )
            for o in self._orders
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
            for f in self._fills
        ]
        balances = [Balance(asset=k, free=v) for k, v in self._balances.items() if v > 0]
        return Truth(balances=balances, open_orders=orders, recent_fills=fills)

    def place_entry_with_stop(self, coid, qty, stop, *, pair):
        # Record the order and the stop, then crash.
        self.entry_calls.append(coid)
        self._orders.append({"coid": coid, "pair": pair, "side": "buy", "qty": qty, "stop_price": stop})
        self._balances["SUI"] = self._balances.get("SUI", Decimal(0)) + qty
        raise RuntimeError("simulated crash between place_entry and journal")

    def place_stop(self, coid, qty, stop, *, pair):
        self._orders.append({"coid": coid, "pair": pair, "side": "sell", "qty": qty, "stop_price": stop})

    def place_exit(self, coid, qty, *, pair):
        self.exit_calls.append(coid)
        self._orders = [o for o in self._orders if not (o["pair"] == pair and o.get("side") == "buy")]
        return {"id": coid, "coid": coid, "pair": pair, "side": "sell", "qty": qty, "filled_qty": qty}

    def cancel_stops(self, pair):
        self._orders = [o for o in self._orders if not (o["pair"] == pair and o.get("stop_price") is not None)]

    def raise_stop(self, pair, new_stop):
        for o in self._orders:
            if o["pair"] == pair and o.get("stop_price") is not None:
                o["stop_price"] = max(o["stop_price"], new_stop)

    def order_by_coid(self, coid):
        for o in self._orders:
            if o["coid"] == coid:
                return o
        return None

    def check_key(self):
        from krellbot.venues.base import KeyPerms

        return KeyPerms(can_trade=True, can_withdraw=False)


def test_kill_between_place_and_journal_does_not_double_order(home):
    """Engine places entry then crashes. Next tick sees the open position and
    does NOT place a second entry.
    """
    from krellbot import license
    from krellbot.run import arm_pack, tick

    pack_path = _pack(home)
    license.write_cache(home, status="active", period_end=0, grace_until=10**12)

    candles = [
        Candle(
            ts_ms=0, open=Decimal(10), high=Decimal("10.5"), low=Decimal("9.5"), close=Decimal(10), volume=Decimal(100)
        ),
        Candle(
            ts_ms=3_600_000,
            open=Decimal(10),
            high=Decimal("10.5"),
            low=Decimal("9.5"),
            close=Decimal(10),
            volume=Decimal(100),
        ),
        Candle(
            ts_ms=7_200_000,
            open=Decimal("10.5"),
            high=Decimal("12.5"),
            low=Decimal(10),
            close=Decimal(12),
            volume=Decimal(100),
        ),
    ]

    arm_pack(pack_path, venue="kraken", mode="paper", paper_balance=Decimal(1000), requires_license=True)

    crashing_venue = _CrashAfterPlaceVenue(candles)
    reader = _StaticReader(candles)
    journal = _JournalSpy()

    rc = tick(
        venue="kraken",
        venue_obj=crashing_venue,
        reader=reader,
        journal_sink=journal,
        clock=lambda: 7_200_000 // 1000,
    )
    assert rc == 0
    assert len(crashing_venue.entry_calls) == 1
    assert journal.records, "engine journals a tick even when entry raised"

    # Restart: same venue instance keeps state, but we DO NOT call
    # place_entry_with_stop again. The engine should read snapshot, see the
    # open position, and journal a tick record without sending another entry.
    # Build a fresh, non-crashing venue by reusing the same state.
    class _ResumeVenue(_CrashAfterPlaceVenue):
        def place_entry_with_stop(self, coid, qty, stop, *, pair):
            # Track entries but do not crash.
            self.entry_calls.append(coid)
            self._orders.append({"coid": coid, "pair": pair, "side": "buy", "qty": qty, "stop_price": stop})
            self._balances["SUI"] = self._balances.get("SUI", Decimal(0)) + qty
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
            self._orders.append({"coid": coid, "pair": pair, "side": "sell", "qty": qty, "stop_price": stop})

    resume = _ResumeVenue(candles)
    resume._balances = crashing_venue._balances  # carry state across the crash
    resume._orders = crashing_venue._orders
    resume._fills = crashing_venue._fills
    resume.entry_calls = []  # only count post-restart calls

    rc = tick(
        venue="kraken",
        venue_obj=resume,
        reader=reader,
        journal_sink=journal,
        clock=lambda: 7_200_000 // 1000,
    )
    assert rc == 0
    assert resume.entry_calls == []
    total_entries = len(crashing_venue.entry_calls) + len(resume.entry_calls)
    assert total_entries == 1, f"expected exactly one entry across crash + resume, got {total_entries}"
    ticks = [r for r in journal.records if r.get("kind") == "tick"]
    assert len(ticks) >= 1
