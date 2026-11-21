"""KuCoin wave pair instrument rules: production snapshot write.

The production ``ensure_instrument_rules`` path must persist
``$KRELLBOT_HOME/run/instrument-rules.json`` coverage for the agreed
KuCoin pack pair (``BTC-USDT``), which is also the venue symbol.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.data.instruments import (
    KUCOIN_SYMBOLS_URL,
    METADATA_UNAVAILABLE,
    PAPER_WAVE_KUCOIN_BTC_USDT,
    InstrumentMetadataClient,
    InstrumentMetadataError,
    ensure_instrument_rules,
)

KUCOIN_BTC_USDT_SYMBOL = {
    "symbol": "BTC-USDT",
    "baseCurrency": "BTC",
    "quoteCurrency": "USDT",
    "baseMinSize": "0.00001",
    "quoteMinSize": "0.1",
    "baseIncrement": "0.00000001",
    "quoteIncrement": "0.000001",
    "priceIncrement": "0.1",
    "minFunds": "0.1",
    "enableTrading": True,
}


class _KucoinSymbolTransport:
    """Serves the public symbol payload for the wave BTC-USDT market."""

    def __init__(self, *, payload: dict | None = None) -> None:
        symbol = dict(payload) if payload is not None else dict(KUCOIN_BTC_USDT_SYMBOL)
        self.payload = {"code": "200000", "data": symbol}
        if payload is not None and payload.get("code") not in (None, "200000"):
            self.payload = dict(payload)
        self.calls: list[tuple[str, str]] = []

    def get(self, url, headers=None):
        self.calls.append(("GET", str(url)))
        if "/api/v2/symbols/" in str(url):
            return dict(self.payload)
        return {}


def test_agreed_kucoin_wave_pair_spelling() -> None:
    """Wave KuCoin pack spelling and the venue symbol are both BTC-USDT."""
    assert PAPER_WAVE_KUCOIN_BTC_USDT == "BTC-USDT"


def test_fetch_rules_kucoin_btc_usdt_from_symbols() -> None:
    transport = _KucoinSymbolTransport()
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)

    record = client.fetch_rules("kucoin", PAPER_WAVE_KUCOIN_BTC_USDT)

    assert record.venue == "kucoin"
    assert record.canonical_pair == PAPER_WAVE_KUCOIN_BTC_USDT
    assert record.venue_symbol == "BTC-USDT"
    assert record.base_asset == "BTC"
    assert record.quote_asset == "USDT"
    assert Decimal(record.min_quantity) == Decimal("0.00001")
    assert Decimal(record.min_notional) == Decimal("0.1")
    assert Decimal(record.quantity_increment) == Decimal("0.00000001")
    assert Decimal(record.price_increment) == Decimal("0.1")
    assert record.source["endpoint"] == KUCOIN_SYMBOLS_URL
    assert transport.calls
    assert transport.calls[0][1].endswith("/api/v2/symbols/BTC-USDT")


def test_ensure_instrument_rules_persists_kucoin_wave_pair(home: Path) -> None:
    transport = _KucoinSymbolTransport()
    ensure_instrument_rules(
        home,
        venue="kucoin",
        pairs=[PAPER_WAVE_KUCOIN_BTC_USDT],
        transport=transport,
        clock=lambda: 1_700_000_000.0,
    )
    body = json.loads((home / "run" / "instrument-rules.json").read_text(encoding="utf-8"))
    stored = body["records"]["kucoin"][PAPER_WAVE_KUCOIN_BTC_USDT]
    assert stored["venue_symbol"] == "BTC-USDT"
    assert stored["base_asset"] == "BTC"


def test_kucoin_symbols_error_label_is_metadata_unavailable() -> None:
    transport = _KucoinSymbolTransport(payload={"code": "400100", "msg": "missing"})
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    with pytest.raises(InstrumentMetadataError) as caught:
        client.fetch_rules("kucoin", PAPER_WAVE_KUCOIN_BTC_USDT)
    assert caught.value.code == METADATA_UNAVAILABLE
