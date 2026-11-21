"""Pionex wave pair instrument rules: production snapshot write.

The production ``ensure_instrument_rules`` path must persist
``$KRELLBOT_HOME/run/instrument-rules.json`` coverage for the agreed
Pionex pack pair (``BTC-USDT``), mapped to symbol ``BTC_USDT``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.data.instruments import (
    METADATA_UNAVAILABLE,
    PAPER_WAVE_PIONEX_BTC_USDT,
    PIONEX_SYMBOLS_URL,
    InstrumentMetadataClient,
    InstrumentMetadataError,
    ensure_instrument_rules,
)

PIONEX_BTC_USDT_SYMBOL = {
    "symbol": "BTC_USDT",
    "type": "SPOT",
    "baseCurrency": "BTC",
    "quoteCurrency": "USDT",
    "basePrecision": 6,
    "quotePrecision": 2,
    "amountPrecision": 8,
    "minAmount": "10",
    "minTradeSize": "0.000001",
    "enable": True,
}


class _PionexSymbolTransport:
    """Serves the public symbols payload for the wave BTC-USDT market."""

    def __init__(self, *, payload: dict | None = None) -> None:
        symbol = dict(payload) if payload is not None else dict(PIONEX_BTC_USDT_SYMBOL)
        self.payload = {"result": True, "data": {"symbols": [symbol]}, "timestamp": 1}
        if payload is not None and payload.get("result") is False:
            self.payload = dict(payload)
        self.calls: list[tuple[str, str]] = []

    def get(self, url, headers=None):
        self.calls.append(("GET", str(url)))
        if "/api/v1/common/symbols" in str(url):
            return dict(self.payload)
        return {}


def test_agreed_pionex_wave_pair_spelling() -> None:
    """Wave Pionex pack spelling is BASE-QUOTE; the venue symbol uses an underscore."""
    assert PAPER_WAVE_PIONEX_BTC_USDT == "BTC-USDT"


def test_fetch_rules_pionex_btc_usdt_from_symbols() -> None:
    transport = _PionexSymbolTransport()
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)

    record = client.fetch_rules("pionex", PAPER_WAVE_PIONEX_BTC_USDT)

    assert record.venue == "pionex"
    assert record.canonical_pair == PAPER_WAVE_PIONEX_BTC_USDT
    assert record.venue_symbol == "BTC_USDT"
    assert record.base_asset == "BTC"
    assert record.quote_asset == "USDT"
    assert Decimal(record.min_quantity) == Decimal("0.000001")
    assert Decimal(record.min_notional) == Decimal(10)
    assert Decimal(record.quantity_increment) == Decimal("0.000001")
    assert Decimal(record.price_increment) == Decimal("0.01")
    assert record.source["endpoint"] == PIONEX_SYMBOLS_URL
    assert transport.calls
    assert "symbols=BTC_USDT" in transport.calls[0][1]


def test_ensure_instrument_rules_persists_pionex_wave_pair(home: Path) -> None:
    transport = _PionexSymbolTransport()
    path = ensure_instrument_rules(
        home,
        venue="pionex",
        pairs=[PAPER_WAVE_PIONEX_BTC_USDT],
        transport=transport,
        clock=lambda: 1_700_000_000.0,
    )
    assert path is not None
    body = json.loads(path.read_text(encoding="utf-8"))
    stored = body["records"]["pionex"][PAPER_WAVE_PIONEX_BTC_USDT]
    assert stored["canonical_pair"] == "BTC-USDT"
    assert stored["venue_symbol"] == "BTC_USDT"
    assert stored["quote_asset"] == "USDT"


def test_pionex_symbols_error_label_is_metadata_unavailable() -> None:
    transport = _PionexSymbolTransport(payload={"result": False, "code": "SYMBOL_NOT_FOUND", "message": "missing"})
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    with pytest.raises(InstrumentMetadataError) as raised:
        client.fetch_rules("pionex", PAPER_WAVE_PIONEX_BTC_USDT)
    assert raised.value.code == METADATA_UNAVAILABLE
