"""INT03 — paper tick calls the shared decision trace.

The brief pins three observable behaviors:

  1. A paper tick calls ``krellbot.domain.trace.paper_decision_trace`` once
     per armed paper pack. The journal detail records ``decision_trace_bars``
     equal to the returned list length and ``decision_reason`` equal to the
     last row's ``target.reason`` when that value is a string.
  2. A live tick does not call ``paper_decision_trace``. Its journal detail
     carries no ``decision_trace_bars`` key.
  3. The paper detail carries no ``fill_price``, ``venue_fill``, ``equity``,
     ``return_pct``, or ``pnl`` field. The trace is the per-bar decision
     record, not a venue fill record.

The test spies on ``krellbot.domain.trace.paper_decision_trace`` (the symbol
``tick`` actually calls) and injects a fake venue that satisfies the duck
type. No real venue is opened; ``KRELLBOT_ENABLE_LIVE`` is left unset so a
live arm that accidentally tried to place an order would fail closed.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest


def _write_pack(home: Path, *, pair: str = "SUIUSD", pack_id: str = "int03") -> Path:
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "INT03 paper trace",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": pair}],
    }
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm(
    home: Path,
    pack_path: Path,
    *,
    mode: str,
    pack_id: str = "int03",
    pair: str = "SUIUSD",
) -> None:
    """Save a fresh ``ArmedPack`` directly via ``save_config``.

    The CLI's ``arm_pack`` refuses live arms unless
    ``KRELLBOT_ENABLE_LIVE=1``; saving the record directly lets the live
    test exercise the tick path without flipping the global env gate.
    """
    from krellbot.config import ArmedPack, Config, save_config

    save_config(
        home,
        Config(
            armed=[
                ArmedPack(
                    pack_path=str(pack_path),
                    pack_sha256="0" * 64,
                    pack_id=pack_id,
                    pack_version="1.0.0",
                    venue="kraken",
                    pair=pair,
                    cap=Decimal(100),
                    stop=Decimal(5),
                    mode=mode,
                    starting_cash=Decimal(1000) if mode == "paper" else None,
                    requires_license=False,
                    armed_at_ts=1,
                )
            ]
        ),
    )


class _StaticReader:
    """A candle reader that returns the same list for every (venue, pair)."""

    def __init__(self, candles):
        self.candles = list(candles)

    def __call__(self, venue, pair):
        return list(self.candles)


class _BaseVenue:
    """A minimal in-memory venue that satisfies the duck type ``tick`` uses.

    The engine snapshots once per tick and then per pack reads ``rules(pair)``
    and (when it decides to act) calls ``place_entry_with_stop`` /
    ``place_exit`` / ``place_stop``. No real network is touched.
    """

    def __init__(self):
        self.orders: list[dict] = []
        self.fills: list[dict] = []
        self.balances: dict[str, Decimal] = {"USD": Decimal(1000), "SUI": Decimal(0)}

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


class _JournalSink:
    """A recording journal sink that captures every record ``tick`` writes."""

    def __init__(self):
        self.records: list[dict] = []

    def __call__(self, record):
        self.records.append(record)
        return Path("/dev/null")


def _install_trace_spy(monkeypatch):
    """Wrap ``krellbot.domain.trace.paper_decision_trace`` with a counting spy.

    The spy delegates to the real implementation so the journal detail can
    report a meaningful ``decision_trace_bars`` count and ``decision_reason``
    without the test having to fabricate a trace by hand. The wrapper is
    bound to the module attribute — the same name ``tick`` looks up at call
    time — so a failure to call through it is observable as ``calls == 0``.
    """
    import krellbot.domain.trace as trace_mod

    real = trace_mod.paper_decision_trace

    def spy(pack, candles):
        spy.calls += 1
        spy.last_pack = pack
        spy.last_candles = candles
        return real(pack, candles)

    spy.calls = 0
    spy.last_pack = None
    spy.last_candles = None
    monkeypatch.setattr(trace_mod, "paper_decision_trace", spy)
    return spy


def _make_candles() -> list:
    """Three 1h bars: warmup, flat, then close crosses above sma2 (10->11)."""
    from krellbot.pack.model import Candle

    return [
        Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100)),
        Candle(
            ts_ms=3_600_000,
            open=Decimal(10),
            high=Decimal(11),
            low=Decimal(9),
            close=Decimal(10),
            volume=Decimal(100),
        ),
        Candle(
            ts_ms=7_200_000,
            open=Decimal(11),
            high=Decimal(13),
            low=Decimal(10),
            close=Decimal(12),
            volume=Decimal(100),
        ),
    ]


# ---------------------------------------------------------------------------
# 1. Paper tick calls paper_decision_trace once and records bars + reason.
# ---------------------------------------------------------------------------


def test_paper_tick_calls_paper_decision_trace_and_records_bars_and_reason(home, fresh_keyring, monkeypatch):
    """A paper tick must call ``paper_decision_trace(pack, candles)`` once
    for the armed paper pack. The journal detail records
    ``decision_trace_bars`` equal to the returned list length and
    ``decision_reason`` equal to the last row's ``target.reason``.
    """
    from krellbot.run import tick

    pack_path = _write_pack(home, pack_id="int03-paper")
    _arm(home, pack_path, mode="paper", pack_id="int03-paper")
    spy = _install_trace_spy(monkeypatch)

    candles = _make_candles()
    venue = _BaseVenue()
    journal = _JournalSink()

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=_StaticReader(candles),
        journal_sink=journal,
        clock=lambda: 0,
        home=home,
    )

    assert rc == 0
    assert spy.calls == 1, f"paper tick must call paper_decision_trace once, got {spy.calls}"
    assert spy.last_pack is not None
    assert list(spy.last_candles) == list(candles)

    tick_records = [r for r in journal.records if r.get("kind") == "tick" and r.get("pack") == "int03-paper"]
    assert tick_records, "engine must journal a tick record for the paper pack"
    detail = tick_records[0]["detail"]

    assert "decision_trace_bars" in detail, detail
    assert detail["decision_trace_bars"] == len(candles), (
        f"decision_trace_bars must equal the trace length ({len(candles)}), got {detail['decision_trace_bars']!r}"
    )
    assert "decision_reason" in detail, detail
    # The last bar triggers entry; its target.reason is the last trace row's reason.
    assert isinstance(detail["decision_reason"], str), detail
    assert detail["decision_reason"], detail


def test_paper_tick_decision_reason_matches_last_trace_row_target_reason(home, fresh_keyring, monkeypatch):
    """``decision_reason`` is the last trace row's ``target.reason``,
    captured by the spy for direct comparison. The string comes from the
    function's return, not from a hardcoded copy.
    """
    import krellbot.domain.trace as trace_mod
    from krellbot.run import tick

    pack_path = _write_pack(home, pack_id="int03-reason")
    _arm(home, pack_path, mode="paper", pack_id="int03-reason")

    candles = _make_candles()

    captured_trace: dict = {}

    real = trace_mod.paper_decision_trace

    def spy(pack, cs):
        captured_trace["rows"] = real(pack, cs)
        return captured_trace["rows"]

    monkeypatch.setattr(trace_mod, "paper_decision_trace", spy)

    venue = _BaseVenue()
    journal = _JournalSink()

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=_StaticReader(candles),
        journal_sink=journal,
        clock=lambda: 0,
        home=home,
    )

    assert rc == 0
    rows = captured_trace["rows"]
    assert rows, "spy must have captured a non-empty trace"
    last_reason = rows[-1]["target"]["reason"]
    assert isinstance(last_reason, str)

    tick_records = [r for r in journal.records if r.get("kind") == "tick" and r.get("pack") == "int03-reason"]
    detail = tick_records[0]["detail"]
    assert detail["decision_reason"] == last_reason, (
        f"decision_reason {detail['decision_reason']!r} must equal last trace row's reason {last_reason!r}"
    )
    assert detail["decision_trace_bars"] == len(rows)


# ---------------------------------------------------------------------------
# 2. Live tick does not call paper_decision_trace.
# ---------------------------------------------------------------------------


def test_live_tick_does_not_call_paper_decision_trace(home, fresh_keyring, monkeypatch):
    """A live tick must not invoke ``paper_decision_trace``. The journal
    detail carries no ``decision_trace_bars`` key — the live path must not
    gain a trace field it never asked for.
    """
    from krellbot.run import tick

    pack_path = _write_pack(home, pack_id="int03-live", pair="BTCUSD")
    _arm(home, pack_path, mode="live", pack_id="int03-live", pair="BTCUSD")
    spy = _install_trace_spy(monkeypatch)

    candles = _make_candles()
    venue = _BaseVenue()
    venue.balances["USD"] = Decimal(1000)
    venue.balances["BTC"] = Decimal(0)
    journal = _JournalSink()

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=_StaticReader(candles),
        journal_sink=journal,
        clock=lambda: 0,
        home=home,
    )

    assert rc == 0
    assert spy.calls == 0, (
        f"live tick must not call paper_decision_trace; got {spy.calls} call(s). "
        "The trace is paper-only — a live tick must not gain decision_trace_bars."
    )

    tick_records = [r for r in journal.records if r.get("kind") == "tick" and r.get("pack") == "int03-live"]
    assert tick_records, "engine must journal a tick record for the live pack"
    detail = tick_records[0]["detail"]
    assert "decision_trace_bars" not in detail, (
        f"live tick detail must not carry decision_trace_bars; got detail={detail!r}"
    )
    assert "decision_reason" not in detail, f"live tick detail must not carry decision_reason; got detail={detail!r}"


# ---------------------------------------------------------------------------
# 3. Paper detail has no fill / venue / equity / pnl fields.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("forbidden_field", ["fill_price", "venue_fill", "equity", "return_pct", "pnl"])
def test_paper_tick_detail_has_no_fill_or_pnl_fields(forbidden_field: str, home, fresh_keyring, monkeypatch):
    """The paper journal detail is a decision record, not a fill record.
    None of the brief-forbidden fields appear.
    """
    from krellbot.run import tick

    pack_path = _write_pack(home, pack_id=f"int03-{forbidden_field}")
    _arm(home, pack_path, mode="paper", pack_id=f"int03-{forbidden_field}")
    _install_trace_spy(monkeypatch)

    candles = _make_candles()
    venue = _BaseVenue()
    journal = _JournalSink()

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=_StaticReader(candles),
        journal_sink=journal,
        clock=lambda: 0,
        home=home,
    )

    assert rc == 0
    tick_records = [
        r for r in journal.records if r.get("kind") == "tick" and r.get("pack") == f"int03-{forbidden_field}"
    ]
    assert tick_records, "engine must journal a tick record for the paper pack"
    detail = tick_records[0]["detail"]
    assert forbidden_field not in detail, f"paper detail must not carry {forbidden_field!r}; got detail={detail!r}"
