"""Synthetic valid increments must fit the decimal-count paper adapter exactly."""

from dataclasses import asdict, replace
from decimal import Decimal, localcontext

import pytest

from krellbot.cli import _build_paper_rules_provider
from krellbot.data.instruments import (
    InstrumentMetadataError,
    InstrumentRulesSnapshot,
    InstrumentRulesV1,
    derive_decimal_places,
    pairrules_from_instrument,
)
from krellbot.pack.model import Candle
from krellbot.venues.paper import PaperVenue


def _record(**changes):
    record = InstrumentRulesV1(
        schema_version="1",
        venue="coinbase",
        canonical_pair="ABC-USD",
        venue_symbol="ABC-USD",
        base_asset="ABC",
        quote_asset="USD",
        min_quantity="0.01",
        min_notional="0.01",
        quantity_increment="0.01",
        price_increment="0.01",
        source={
            "endpoint": "synthetic://fixture",
            "retrieved_at": "2026-01-01T00:00:00Z",
            "source_version": "synthetic",
            "payload_sha256": "0" * 64,
        },
        usable_until="2099-01-01T00:00:00Z",
    )
    return replace(record, **changes)


@pytest.mark.parametrize("field", ["quantity_increment", "price_increment"])
@pytest.mark.parametrize("step", ["0.05", "0.25", "0.0500", "5", "10", "1E+1"])
def test_valid_but_unrepresentable_steps_refuse_with_exact_identity(field, step):
    record = _record(**{field: step})
    before = asdict(record)
    with pytest.raises(InstrumentMetadataError) as caught:
        pairrules_from_instrument(record)
    assert (caught.value.code, caught.value.venue, caught.value.pair) == ("metadata_invalid", "coinbase", "ABC-USD")
    assert field in str(caught.value)
    assert asdict(record) == before


@pytest.mark.parametrize("step,places", [("1", 0), ("1.000", 0), ("0.0100", 2), ("1E-3", 3), ("0.0001000", 4)])
def test_equivalent_power_of_ten_steps_are_exact_even_with_small_decimal_context(step, places):
    with localcontext() as context:
        context.prec = 2
        rules = pairrules_from_instrument(_record(quantity_increment=step, price_increment=step))
    assert rules.lot_decimals == rules.price_decimals == places
    assert rules.ordermin == rules.costmin == Decimal("0.01")
    assert Decimal(1).scaleb(-places) == Decimal(step)
    assert derive_decimal_places("0.0100") == 4  # Public helper contract is deliberately unchanged.


@pytest.mark.parametrize(
    "quantity,price,refuses", [("0.05", "0.01", True), ("0.01", "0.25", True), ("0.0100", "0.0100", False)]
)
def test_snapshot_actual_cli_provider_prevents_off_grid_publication(
    home, monkeypatch, fresh_keyring, quantity, price, refuses
):
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "0")
    monkeypatch.chdir(home)
    monkeypatch.setattr("krellbot.data.instruments._default_now", lambda: 1_700_000_000)
    record = _record(quantity_increment=quantity, price_increment=price)
    InstrumentRulesSnapshot(home).write({"coinbase": {"ABC-USD": record}})
    snapshot_file = home / "run" / "instrument-rules.json"
    snapshot_before = snapshot_file.read_bytes()
    bar = Candle(0, Decimal(100), Decimal(100), Decimal(100), Decimal(100), Decimal(10))
    venue = PaperVenue(
        "coinbase",
        rules_provider=_build_paper_rules_provider(home, "coinbase"),
        candle_reader=lambda *_: [bar],
        home=home,
        starting_cash=Decimal(1000),
    )
    state_file = home / "run" / "paper-coinbase.json"
    before = state_file.read_bytes()
    if refuses:
        with pytest.raises(InstrumentMetadataError) as caught:
            venue.place_entry_with_stop("synthetic-entry", Decimal("0.13"), Decimal("90.13"), pair="ABC-USD")
        assert caught.value.code == "metadata_invalid" and caught.value.pair == "ABC-USD"
        assert state_file.read_bytes() == before
        assert not venue.snapshot().recent_fills and not venue.snapshot().open_orders
    else:
        venue.place_entry_with_stop("synthetic-entry", Decimal("0.13"), Decimal("90.13"), pair="ABC-USD")
        truth = venue.snapshot()
        assert len(truth.recent_fills) == len(truth.open_orders) == 1
        assert truth.recent_fills[0].qty % Decimal(quantity) == 0
        assert truth.recent_fills[0].price % Decimal(price) == 0
        assert truth.open_orders[0].stop_price % Decimal(price) == 0
    assert snapshot_file.read_bytes() == snapshot_before
