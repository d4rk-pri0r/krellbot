"""Paper fills prefer forming-candle close when the product expects it.

After the shared Kraken fetch became closed-only (#197 / #388), paper
fill/mark inputs followed last-closed. PaperVenue recovers forming
semantics when the reader still supplies an in-progress bar and a
timeframe is known: market entry/exit price at the forming close, while
stop triggers on closed bars (and may also fire on the forming low
without advancing the closed-bar cursor).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from krellbot.data.candles import TF_MS, is_forming, pricing_close
from krellbot.pack.model import Candle
from krellbot.venues.base import PairRules
from krellbot.venues.paper import PaperVenue

TF = "1h"
TF_MS_1H = TF_MS[TF]
CLOSED_TS = 0
FORMING_TS = TF_MS_1H
# Forming bar started at 1h and is still open halfway through the next hour.
NOW_S = (FORMING_TS + TF_MS_1H // 2) / 1000


def _rules(_pair: str = "SUIUSD") -> PairRules:
    return PairRules(
        ordermin=Decimal("0.0001"),
        costmin=Decimal("0.5"),
        lot_decimals=8,
        price_decimals=5,
    )


def _bar(ts_ms: int, *, close: str, low: str | None = None, open_: str | None = None) -> Candle:
    px = Decimal(close)
    return Candle(
        ts_ms=ts_ms,
        open=Decimal(open_ or close),
        high=px + Decimal(1),
        low=Decimal(low) if low is not None else px - Decimal(1),
        close=px,
        volume=Decimal(100),
    )


class _Reader:
    def __init__(self, candles: list[Candle]) -> None:
        self.candles = list(candles)

    def __call__(self, _venue: str, _pair: str) -> list[Candle]:
        return list(self.candles)


def _venue(home: Path, candles: list[Candle]) -> PaperVenue:
    return PaperVenue(
        "kraken",
        rules_provider=_rules,
        candle_reader=_Reader(candles),
        home=home,
        starting_cash=Decimal(10_000),
        clock=lambda: NOW_S,
        timeframe_for_pair=lambda _pair: TF,
    )


def test_pricing_close_prefers_forming_over_last_closed():
    """Helper: forming close wins over the prior closed close."""
    closed = _bar(CLOSED_TS, close="10")
    forming = _bar(FORMING_TS, close="12.5")
    now_ms = int(NOW_S * 1000)
    assert is_forming(forming, TF, now_ms)
    assert not is_forming(closed, TF, now_ms)
    assert pricing_close([closed, forming], TF, now_ms) == Decimal("12.5")
    assert pricing_close([closed], TF, now_ms) == Decimal(10)


def test_paper_entry_fills_at_forming_close_plus_buy_slip(home: Path):
    """Market entry prices at the forming close, not the last closed close."""
    closed = _bar(CLOSED_TS, close="10")
    forming = _bar(FORMING_TS, close="20")
    venue = _venue(home, [closed, forming])

    venue.place_entry_with_stop("coid-form", Decimal(5), Decimal(15), pair="SUIUSD")
    fill = venue.snapshot().recent_fills[0]
    # 20 * (1 + 0.0005) = 20.01
    assert fill.price == Decimal("20.01")
    assert fill.side == "buy"


def test_paper_exit_fills_at_forming_close_minus_sell_slip(home: Path):
    """Market exit also marks at the forming close."""
    closed = _bar(CLOSED_TS, close="10")
    forming = _bar(FORMING_TS, close="20")
    venue = _venue(home, [closed, forming])
    venue.place_entry_with_stop("coid-form", Decimal(5), Decimal(15), pair="SUIUSD")

    # Advance forming mark so exit differs from entry.
    venue._reader.candles = [closed, _bar(FORMING_TS, close="22")]
    venue.place_exit("coid-form", Decimal(5), pair="SUIUSD")
    sells = [f for f in venue.snapshot().recent_fills if f.side == "sell"]
    assert len(sells) == 1
    # 22 * (1 - 0.0005) = 21.989
    assert sells[0].price == Decimal("21.989")


def test_paper_stop_does_not_treat_forming_as_closed_cursor(home: Path):
    """Forming bar can trigger a stop without locking the closed-bar cursor.

    Entry advances the cursor only through closed bars. A forming low that
    touches the stop fills immediately; a later closed bar at the same
    open still processes the cursor when the forming bar eventually closes.
    """
    closed = _bar(CLOSED_TS, close="10", low="9", open_="10")
    forming = _bar(FORMING_TS, close="9", low="4.0", open_="9")
    venue = _venue(home, [closed, forming])
    venue.place_entry_with_stop("coid-stop", Decimal(5), Decimal("4.5"), pair="SUIUSD")

    state_path = home / "run" / "paper-kraken.json"
    import json

    cursors = json.loads(state_path.read_text(encoding="utf-8"))["last_applied_ts_by_pair"]
    assert cursors["SUIUSD"] == CLOSED_TS

    snap = venue.snapshot()
    sells = [f for f in snap.recent_fills if f.side == "sell"]
    assert len(sells) == 1
    expected = min(Decimal("4.5"), Decimal(9)) * (Decimal(1) - Decimal("0.0005"))
    assert sells[0].price == expected.quantize(Decimal("0.00001"))
    assert not [o for o in snap.open_orders if o.stop_price is not None]


def test_paper_without_timeframe_keeps_last_candle_close(home: Path):
    """Legacy callers (no timeframe) still price at candles[-1].close."""
    candles = [_bar(CLOSED_TS, close="10"), _bar(FORMING_TS, close="20")]
    venue = PaperVenue(
        "kraken",
        rules_provider=_rules,
        candle_reader=_Reader(candles),
        home=home,
        starting_cash=Decimal(10_000),
        clock=lambda: NOW_S,
    )
    venue.place_entry_with_stop("coid-legacy", Decimal(5), Decimal(15), pair="SUIUSD")
    assert venue.snapshot().recent_fills[0].price == Decimal("20.01")
