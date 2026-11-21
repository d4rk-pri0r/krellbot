"""Gate wave pair instrument rules: production snapshot write.

The production ``ensure_instrument_rules`` path must persist
``$KRELLBOT_HOME/run/instrument-rules.json`` coverage for the agreed
Gate pack pair (``BTC-USDT``), mapped to currency pair ``BTC_USDT``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.data.instruments import (
    GATE_CURRENCY_PAIR_URL,
    METADATA_UNAVAILABLE,
    PAPER_WAVE_GATE_BTC_USDT,
    InstrumentMetadataClient,
    InstrumentMetadataError,
    ensure_instrument_rules,
)

GATE_BTC_USDT_PAIR = {
    "id": "BTC_USDT",
    "base": "BTC",
    "quote": "USDT",
    "min_base_amount": "0.00001",
    "min_quote_amount": "1",
    "amount_precision": 6,
    "precision": 1,
    "trade_status": "tradable",
}


class _GatePairTransport:
    """Serves the public currency pair for the wave BTC-USDT market."""

    def __init__(self, *, payload: dict | None = None) -> None:
        self.payload = dict(payload) if payload is not None else dict(GATE_BTC_USDT_PAIR)
        self.calls: list[tuple[str, str]] = []

    def get(self, url, headers=None):
        self.calls.append(("GET", str(url)))
        if "/spot/currency_pairs/" in str(url):
            return dict(self.payload)
        return {}


def test_agreed_gate_wave_pair_spelling() -> None:
    """Wave Gate pack spelling is BASE-QUOTE; the venue symbol uses an underscore."""
    assert PAPER_WAVE_GATE_BTC_USDT == "BTC-USDT"


def test_fetch_rules_gate_btc_usdt_from_currency_pair() -> None:
    transport = _GatePairTransport()
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)

    record = client.fetch_rules("gate", PAPER_WAVE_GATE_BTC_USDT)

    assert record.venue == "gate"
    assert record.canonical_pair == PAPER_WAVE_GATE_BTC_USDT
    assert record.venue_symbol == "BTC_USDT"
    assert record.base_asset == "BTC"
    assert record.quote_asset == "USDT"
    assert Decimal(record.min_quantity) == Decimal("0.00001")
    assert Decimal(record.min_notional) == Decimal(1)
    assert Decimal(record.quantity_increment) == Decimal("0.000001")
    assert Decimal(record.price_increment) == Decimal("0.1")
    assert record.source["endpoint"] == GATE_CURRENCY_PAIR_URL
    assert transport.calls
    assert transport.calls[0][1].endswith("/spot/currency_pairs/BTC_USDT")


def test_ensure_instrument_rules_persists_gate_wave_pair(home: Path) -> None:
    transport = _GatePairTransport()
    path = ensure_instrument_rules(
        home,
        venue="gate",
        pairs=[PAPER_WAVE_GATE_BTC_USDT],
        transport=transport,
        clock=lambda: 1_700_000_000.0,
    )
    assert path is not None
    body = json.loads(path.read_text(encoding="utf-8"))
    stored = body["records"]["gate"][PAPER_WAVE_GATE_BTC_USDT]
    assert stored["canonical_pair"] == "BTC-USDT"
    assert stored["venue_symbol"] == "BTC_USDT"
    assert stored["quote_asset"] == "USDT"


def test_gate_currency_pair_error_label_is_metadata_unavailable() -> None:
    transport = _GatePairTransport(payload={"label": "INVALID_CURRENCY_PAIR", "message": "Invalid pair"})
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    with pytest.raises(InstrumentMetadataError) as raised:
        client.fetch_rules("gate", PAPER_WAVE_GATE_BTC_USDT)
    assert raised.value.code == METADATA_UNAVAILABLE
