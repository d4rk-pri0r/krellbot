"""NS11a — versioned spot domain records.

Spot-only instrument records: asset_class=spot, Decimal quantity/price,
deterministic instrument_id, and a stop gate that refuses to submit
when the venue reports `unsupported`. No venue adapters are imported.
"""

from __future__ import annotations

import importlib
from decimal import Decimal

import pytest

from krellbot import domain as domain_mod
from krellbot.domain import records as records_mod
from krellbot.domain.records import (
    InstrumentRecord,
    UnsupportedAssetClass,
    UnsupportedStop,
    make_instrument,
    require_supported_stop,
)

# ---- asset_class ---------------------------------------------------------


def test_instrument_record_accepts_spot():
    rec = InstrumentRecord(venue="kraken", pair="XBTUSD", asset_class="spot")
    assert rec.venue == "kraken"
    assert rec.pair == "XBTUSD"
    assert rec.asset_class == "spot"


def test_instrument_record_rejects_futures_and_stores_nothing():
    with pytest.raises(UnsupportedAssetClass) as ei:
        InstrumentRecord(venue="kraken", pair="XBTUSD", asset_class="futures")
    assert ei.value.asset_class == "futures"


def test_instrument_record_rejects_unknown_asset_class_and_stores_nothing():
    with pytest.raises(UnsupportedAssetClass):
        InstrumentRecord(venue="kraken", pair="XBTUSD", asset_class="perpetual")


def test_make_instrument_also_refuses_non_spot():
    with pytest.raises(UnsupportedAssetClass):
        make_instrument(venue="coinbase", pair="BTC-USD", asset_class="futures")


# ---- Decimal-only quantity / price --------------------------------------


def test_instrument_record_accepts_decimal_quantity_and_price():
    rec = InstrumentRecord(
        venue="kraken",
        pair="XBTUSD",
        asset_class="spot",
        quantity=Decimal("0.01"),
        price=Decimal("30000.50"),
    )
    assert rec.quantity == Decimal("0.01")
    assert rec.price == Decimal("30000.50")


def test_quantity_float_raises_type_error():
    with pytest.raises(TypeError) as ei:
        InstrumentRecord(venue="kraken", pair="XBTUSD", asset_class="spot", quantity=0.01)
    assert "quantity" in str(ei.value)
    assert "float" in str(ei.value).lower()


def test_price_float_raises_type_error():
    with pytest.raises(TypeError) as ei:
        InstrumentRecord(venue="kraken", pair="XBTUSD", asset_class="spot", price=30000.5)
    assert "price" in str(ei.value)
    assert "float" in str(ei.value).lower()


def test_float_is_not_coerced():
    """Passing a float never silently becomes a Decimal."""
    with pytest.raises(TypeError):
        InstrumentRecord(
            venue="kraken",
            pair="XBTUSD",
            asset_class="spot",
            quantity=1.0,
            price=2.0,
        )


def test_decimal_int_is_accepted():
    """An int passed as a Decimal-built value (no fraction) is fine."""
    rec = InstrumentRecord(
        venue="kraken",
        pair="XBTUSD",
        asset_class="spot",
        quantity=Decimal(1),
        price=Decimal(2),
    )
    assert rec.quantity == Decimal(1)
    assert rec.price == Decimal(2)


# ---- instrument_id ------------------------------------------------------


def test_instrument_id_is_deterministic_for_same_inputs():
    a = InstrumentRecord(venue="kraken", pair="XBTUSD", asset_class="spot")
    b = InstrumentRecord(venue="kraken", pair="XBTUSD", asset_class="spot")
    assert a.instrument_id == b.instrument_id
    assert isinstance(a.instrument_id, str)


def test_instrument_id_differs_by_venue_or_pair():
    same = InstrumentRecord(venue="kraken", pair="XBTUSD", asset_class="spot").instrument_id
    other_venue = InstrumentRecord(venue="coinbase", pair="XBTUSD", asset_class="spot").instrument_id
    other_pair = InstrumentRecord(venue="kraken", pair="ETHUSD", asset_class="spot").instrument_id
    assert same != other_venue
    assert same != other_pair
    assert other_venue != other_pair


# ---- require_supported_stop ---------------------------------------------


def test_require_supported_stop_calls_submit_when_native():
    called = []

    def submit():
        called.append("submit")
        return "ok-native"

    result = require_supported_stop("native", submit)
    assert result == "ok-native"
    assert called == ["submit"]


def test_require_supported_stop_calls_submit_when_emulated():
    called = []

    def submit():
        called.append("submit")
        return "ok-emulated"

    result = require_supported_stop("emulated", submit)
    assert result == "ok-emulated"
    assert called == ["submit"]


def test_require_supported_stop_refuses_unsupported_and_skips_submit():
    called = []

    def submit():
        called.append("submit")
        return "should-never-happen"

    with pytest.raises(UnsupportedStop) as ei:
        require_supported_stop("unsupported", submit)
    assert ei.value.capability == "unsupported"
    assert called == []


def test_require_supported_stop_rejects_unknown_capability():
    with pytest.raises(ValueError):
        require_supported_stop("nope", lambda: None)


# ---- isolation from venue adapters --------------------------------------


def test_domain_module_does_not_import_krellbot_venues():
    """NS11a: do not import or call `krellbot.venues` from the domain layer."""
    for mod_name in ("krellbot.domain", "krellbot.domain.records"):
        mod = importlib.import_module(mod_name)
        for attr in dir(mod):
            if attr.startswith("__"):
                continue
            obj = getattr(mod, attr)
            mod_obj = getattr(obj, "__module__", "") or ""
            assert "krellbot.venues" not in mod_obj, (
                f"{mod_name}.{attr} resolves to {mod_obj!r}; the domain layer must not depend on venue adapters"
            )


def test_domain_module_does_not_call_into_venues(monkeypatch):
    """A tripwire: any import of `krellbot.venues` raises immediately."""
    import builtins

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "krellbot.venues" or name.startswith("krellbot.venues."):
            raise AssertionError(
                f"krellbot.domain must not import or call krellbot.venues (attempted import of {name!r})"
            )
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    importlib.reload(records_mod)
    importlib.reload(domain_mod)


# ---- re-exports -----------------------------------------------------------


def test_domain_package_reexports_public_symbols():
    for name in (
        "InstrumentRecord",
        "UnsupportedAssetClass",
        "UnsupportedStop",
        "make_instrument",
        "require_supported_stop",
        "SCHEMA_VERSION",
        "SPOT",
        "STOP_NATIVE",
        "STOP_EMULATED",
        "STOP_UNSUPPORTED",
    ):
        assert hasattr(domain_mod, name), name
