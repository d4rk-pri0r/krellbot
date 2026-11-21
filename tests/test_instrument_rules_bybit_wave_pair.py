"""Bybit wave pair instrument rules: production snapshot write.

The production ``ensure_instrument_rules`` path must persist
``$KRELLBOT_HOME/run/instrument-rules.json`` coverage for the agreed
Bybit BTC/USDT symbol (``BTCUSDT``) from public instruments-info (fake
transport in tests).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.data.instruments import (
    BYBIT_INSTRUMENTS_URL,
    METADATA_UNAVAILABLE,
    PAPER_WAVE_BYBIT_BTC_USDT,
    InstrumentMetadataClient,
    InstrumentMetadataError,
    ensure_instrument_rules,
)

BYBIT_BTC_USDT_INSTRUMENTS = {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
        "category": "spot",
        "list": [
            {
                "symbol": "BTCUSDT",
                "baseCoin": "BTC",
                "quoteCoin": "USDT",
                "lotSizeFilter": {
                    "basePrecision": "0.000001",
                    "minOrderQty": "0.000011",
                    "minOrderAmt": "5",
                },
                "priceFilter": {"tickSize": "0.1"},
            }
        ],
    },
}


class _BybitInstrumentsTransport:
    """Serves public instruments for the wave BTCUSDT pair."""

    def __init__(self, *, payload: dict | None = None) -> None:
        self.payload = dict(payload) if payload is not None else dict(BYBIT_BTC_USDT_INSTRUMENTS)
        self.calls: list[tuple[str, str]] = []

    def get(self, url, headers=None):
        self.calls.append(("GET", str(url)))
        if "/v5/market/instruments-info" in str(url):
            return dict(self.payload)
        return {}


def test_agreed_bybit_wave_pair_spelling() -> None:
    """Wave Bybit BTC/USDT spelling is the concatenated spot symbol."""
    assert PAPER_WAVE_BYBIT_BTC_USDT == "BTCUSDT"


def test_fetch_rules_bybit_btc_usdt_from_instruments() -> None:
    """InstrumentMetadataClient normalizes Bybit instruments into InstrumentRulesV1."""
    transport = _BybitInstrumentsTransport()
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)

    record = client.fetch_rules("bybit", PAPER_WAVE_BYBIT_BTC_USDT)

    assert record.venue == "bybit"
    assert record.canonical_pair == PAPER_WAVE_BYBIT_BTC_USDT
    assert record.venue_symbol == PAPER_WAVE_BYBIT_BTC_USDT
    assert record.base_asset == "BTC"
    assert record.quote_asset == "USDT"
    assert Decimal(record.min_quantity) == Decimal("0.000011")
    assert Decimal(record.min_notional) == Decimal(5)
    assert Decimal(record.quantity_increment) == Decimal("0.000001")
    assert Decimal(record.price_increment) == Decimal("0.1")
    assert record.source["endpoint"] == BYBIT_INSTRUMENTS_URL
    assert transport.calls
    assert "symbol=BTCUSDT" in transport.calls[0][1]


def test_ensure_instrument_rules_persists_bybit_wave_pair(home: Path) -> None:
    transport = _BybitInstrumentsTransport()
    path = ensure_instrument_rules(
        home,
        venue="bybit",
        pairs=[PAPER_WAVE_BYBIT_BTC_USDT],
        transport=transport,
        clock=lambda: 1_700_000_000.0,
    )
    assert path is not None
    body = json.loads(path.read_text(encoding="utf-8"))
    stored = body["records"]["bybit"][PAPER_WAVE_BYBIT_BTC_USDT]
    assert stored["venue_symbol"] == "BTCUSDT"
    assert stored["quote_asset"] == "USDT"


def test_bybit_instruments_error_code_is_metadata_unavailable() -> None:
    transport = _BybitInstrumentsTransport(payload={"retCode": 10001, "retMsg": "params error", "result": {}})
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    with pytest.raises(InstrumentMetadataError) as raised:
        client.fetch_rules("bybit", PAPER_WAVE_BYBIT_BTC_USDT)
    assert raised.value.code == METADATA_UNAVAILABLE
