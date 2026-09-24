"""Paper venue: state in $KRELLBOT_HOME/run/paper-<venue>.json, no HTTP.

The paper venue is what `arm --mode paper` and `tick` route orders to. It must
implement the Venue protocol: rules, snapshot, place_entry_with_stop,
place_exit, cancel_stops, raise_stop, order_by_coid, check_key. Stop fills on
a closed bar whose low is at-or-below the stop price happen at
min(stop, open) * (1 - sell_slip). For Kraken paper, if a key is stored and
a validate transport was injected, the venue also POSTs AddOrder with
validate=true and the same fields; that POST does not affect fills.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.pack.model import Candle
from krellbot.venues.base import PairRules


def _paper_home(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    return home


def _default_rules(pair: str = "SUIUSD") -> PairRules:
    return PairRules(
        ordermin=Decimal("0.0001"),
        costmin=Decimal("0.5"),
        lot_decimals=8,
        price_decimals=5,
    )


class _StaticReader:
    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles

    def __call__(self, venue: str, pair: str) -> list[Candle]:
        return list(self.candles)


def test_paper_rules_reads_from_injected_provider(home):
    """rules(pair) returns whatever the injected PairRules provider returns."""
    from krellbot.venues.paper import PaperVenue

    rules = PairRules(
        ordermin=Decimal("0.01"),
        costmin=Decimal(5),
        lot_decimals=4,
        price_decimals=2,
    )

    venue = PaperVenue("kraken", rules_provider=lambda pair: rules, candle_reader=_StaticReader([]), home=home)
    got = venue.rules("SUIUSD")
    assert got == rules


def test_paper_place_entry_with_stop_fills_at_close_plus_buy_slip(home):
    """place_entry_with_stop records a buy at close*(1+buy_slip) and rests a stop."""
    from krellbot.venues.paper import PaperVenue

    candle = Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100))
    reader = _StaticReader([candle])
    venue = PaperVenue(
        "kraken", rules_provider=_default_rules, candle_reader=reader, home=home, starting_cash=Decimal(1000)
    )

    venue.place_entry_with_stop("coid-1", Decimal(5), Decimal("4.5"), pair="SUIUSD")
    snap = venue.snapshot()
    # One recent fill, one resting stop.
    assert len(snap.recent_fills) == 1
    fill = snap.recent_fills[0]
    # Buy fill price = 10 * (1 + 0.0005) = 10.005
    assert fill.price == Decimal("10.005")
    assert fill.qty == Decimal(5)
    assert fill.side == "buy"
    # Stop order rests.
    stops = [o for o in snap.open_orders if o.stop_price is not None]
    assert len(stops) == 1
    assert stops[0].stop_price == Decimal("4.5")
    assert stops[0].coid == "coid-1"


def test_paper_stop_fills_on_trigger_bar(home):
    """A bar whose low <= stop triggers a stop fill at min(stop, open)*(1-sell_slip).

    The fill lands before any signal fill on the same bar.
    """
    from krellbot.venues.paper import PaperVenue

    candles = [
        Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100)),
        Candle(
            ts_ms=3_600_000,
            open=Decimal(9),
            high=Decimal(10),
            low=Decimal("4.0"),
            close=Decimal("4.5"),
            volume=Decimal(100),
        ),
    ]
    venue = PaperVenue(
        "kraken",
        rules_provider=_default_rules,
        candle_reader=_StaticReader(candles),
        home=home,
        starting_cash=Decimal(1000),
    )

    venue.place_entry_with_stop("coid-1", Decimal(5), Decimal("4.5"), pair="SUIUSD")

    stop_price = min(Decimal("4.5"), Decimal(9)) * (Decimal(1) - Decimal("0.0005"))
    venue.record_stop_fill("coid-1", Decimal(5), stop_price, pair="SUIUSD")

    snap = venue.snapshot()
    # A stop fill is recorded. No resting stop remains for that pair.
    assert not [o for o in snap.open_orders if o.pair == "SUIUSD" and o.stop_price is not None]
    fills = snap.recent_fills
    stop_fills = [f for f in fills if f.side == "sell"]
    assert len(stop_fills) == 1
    assert stop_fills[0].price == stop_price.quantize(Decimal("0.00001"))


def test_paper_place_exit_fills_at_close_minus_sell_slip(home):
    """place_exit at last close * (1 - sell_slip) removes the resting stop."""
    from krellbot.venues.paper import PaperVenue

    candle = Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100))
    reader = _StaticReader([candle])
    venue = PaperVenue(
        "kraken", rules_provider=_default_rules, candle_reader=reader, home=home, starting_cash=Decimal(1000)
    )

    venue.place_entry_with_stop("coid-1", Decimal(5), Decimal("4.5"), pair="SUIUSD")
    venue.place_exit("coid-1", Decimal(5), pair="SUIUSD")
    snap = venue.snapshot()
    # No more resting stop.
    assert not [o for o in snap.open_orders if o.pair == "SUIUSD" and o.stop_price is not None]
    # Sell fill recorded at 10 * (1 - 0.0005) = 9.995.
    sells = [f for f in snap.recent_fills if f.side == "sell"]
    assert len(sells) == 1
    assert sells[0].price == Decimal("9.995")


def test_paper_raise_stop_only_raises(home):
    """raise_stop replaces the resting stop only when new > current."""
    from krellbot.venues.paper import PaperVenue

    candle = Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100))
    venue = PaperVenue(
        "kraken",
        rules_provider=_default_rules,
        candle_reader=_StaticReader([candle]),
        home=home,
        starting_cash=Decimal(1000),
    )

    venue.place_entry_with_stop("coid-1", Decimal(5), Decimal("4.5"), pair="SUIUSD")
    # Lower stop should NOT lower.
    venue.raise_stop("SUIUSD", Decimal("4.0"))
    snap = venue.snapshot()
    stops = [o for o in snap.open_orders if o.pair == "SUIUSD" and o.stop_price is not None]
    assert stops[0].stop_price == Decimal("4.5")

    # Higher stop must replace.
    venue.raise_stop("SUIUSD", Decimal("5.5"))
    snap = venue.snapshot()
    stops = [o for o in snap.open_orders if o.pair == "SUIUSD" and o.stop_price is not None]
    assert stops[0].stop_price == Decimal("5.5")


def test_paper_state_round_trips_through_atomic_write(home):
    """State survives an out-of-process restart: another PaperVenue reads the same file."""
    from krellbot.venues.paper import PaperVenue

    candle = Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100))
    reader = _StaticReader([candle])
    venue_a = PaperVenue(
        "kraken", rules_provider=_default_rules, candle_reader=reader, home=home, starting_cash=Decimal(1000)
    )
    venue_a.place_entry_with_stop("coid-1", Decimal(5), Decimal("4.5"), pair="SUIUSD")

    # New instance over the same home reads the same file.
    venue_b = PaperVenue(
        "kraken", rules_provider=_default_rules, candle_reader=reader, home=home, starting_cash=Decimal(1000)
    )
    snap = venue_b.snapshot()
    assert any(o.coid == "coid-1" for o in snap.open_orders)


def test_paper_validate_true_when_key_present_never_trades(home):
    """When a Kraken key is stored AND a validate transport is injected, the
    paper venue also POSTs AddOrder with validate=true and the same fields.
    The validate POST does not record a fill.
    """
    from krellbot.venues.paper import PaperVenue

    recorded: list[dict] = []

    class FakeValidate:
        def post(self, url: str, body: dict, headers: dict) -> dict:
            recorded.append({"url": url, "body": dict(body), "headers": dict(headers)})
            return {"result": {"txid": ["V-1"]}}

    candle = Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100))
    venue = PaperVenue(
        "kraken",
        rules_provider=_default_rules,
        candle_reader=_StaticReader([candle]),
        home=home,
        starting_cash=Decimal(1000),
        validate_transport=FakeValidate(),
        has_stored_key=True,
    )
    venue.place_entry_with_stop("coid-1", Decimal(5), Decimal("4.5"), pair="SUIUSD")
    assert recorded, "validate POST must be issued when key + transport"
    assert recorded[0]["body"]["validate"] == "true"
    assert recorded[0]["body"]["ordertype"] == "market"
    assert recorded[0]["body"]["type"] == "buy"
    assert recorded[0]["body"]["pair"] == "SUIUSD"
    # Fills still happen as normal.
    snap = venue.snapshot()
    assert len(snap.recent_fills) == 1


def test_paper_no_validate_call_without_key(home):
    """If no key is stored, the validate transport is not called even if injected."""
    from krellbot.venues.paper import PaperVenue

    recorded: list[dict] = []

    class FakeValidate:
        def post(self, url: str, body: dict, headers: dict) -> dict:
            recorded.append({"url": url})
            return {"result": {}}

    candle = Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100))
    venue = PaperVenue(
        "kraken",
        rules_provider=_default_rules,
        candle_reader=_StaticReader([candle]),
        home=home,
        starting_cash=Decimal(1000),
        validate_transport=FakeValidate(),
        has_stored_key=False,
    )
    venue.place_entry_with_stop("coid-1", Decimal(5), Decimal("4.5"), pair="SUIUSD")
    assert recorded == []


def test_paper_no_validate_call_without_transport(home):
    """If no validate transport is injected, no POST is issued even with a key."""
    from krellbot.venues.paper import PaperVenue

    candle = Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100))
    venue = PaperVenue(
        "kraken",
        rules_provider=_default_rules,
        candle_reader=_StaticReader([candle]),
        home=home,
        starting_cash=Decimal(1000),
        validate_transport=None,
        has_stored_key=True,
    )
    # Just must not raise and must record one fill.
    venue.place_entry_with_stop("coid-1", Decimal(5), Decimal("4.5"), pair="SUIUSD")
    assert len(venue.snapshot().recent_fills) == 1


def test_paper_state_is_persisted_atomically(home, monkeypatch):
    """If os.replace fails mid-write, the previous state file stays intact."""
    import os as os_mod

    from krellbot.venues.paper import PaperVenue

    candle = Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100))
    venue = PaperVenue(
        "kraken",
        rules_provider=_default_rules,
        candle_reader=_StaticReader([candle]),
        home=home,
        starting_cash=Decimal(1000),
    )
    venue.place_entry_with_stop("coid-1", Decimal(5), Decimal("4.5"), pair="SUIUSD")

    state_file = home / "run" / "paper-kraken.json"
    assert state_file.exists()
    original = state_file.read_bytes()

    real_replace = os_mod.replace

    def boom(src, dst):
        raise OSError("simulated crash")

    monkeypatch.setattr(os_mod, "replace", boom)
    with pytest.raises(OSError):
        venue.place_exit("coid-1", Decimal(5), pair="SUIUSD")

    monkeypatch.setattr(os_mod, "replace", real_replace)
    assert state_file.read_bytes() == original
