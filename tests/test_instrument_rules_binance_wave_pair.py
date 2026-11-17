"""Binance wave pair instrument rules: production snapshot write.

M14.4: the production ``ensure_instrument_rules`` path must persist
``$KRELLBOT_HOME/run/instrument-rules.json`` coverage for the agreed
Binance BTC/USDT symbol (``BTCUSDT``) from public exchangeInfo (fake
transport in tests).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from krellbot.data.instruments import (
    BINANCE_EXCHANGE_INFO_URL,
    METADATA_SYMBOL_MISMATCH,
    METADATA_UNAVAILABLE,
    PAPER_WAVE_BINANCE_BTC_USDT,
    SNAPSHOT_FILENAME,
    InstrumentMetadataClient,
    InstrumentMetadataError,
    ensure_instrument_rules,
)

# Labeled Binance spot exchangeInfo shape for BTCUSDT. Values mirror the
# M14.2 fake transport; no live endpoint is contacted.
BINANCE_BTC_USDT_EXCHANGE_INFO = {
    "symbols": [
        {
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "baseAsset": "BTC",
            "quoteAsset": "USDT",
            "filters": [
                {
                    "filterType": "LOT_SIZE",
                    "minQty": "0.00001",
                    "maxQty": "9000",
                    "stepSize": "0.00001",
                },
                {
                    "filterType": "PRICE_FILTER",
                    "minPrice": "0.01",
                    "maxPrice": "1000000",
                    "tickSize": "0.01",
                },
                {
                    "filterType": "NOTIONAL",
                    "minNotional": "5",
                },
            ],
        }
    ]
}


class _BinanceExchangeInfoTransport:
    """Serves exchangeInfo for the wave BTCUSDT pair; records every call."""

    def __init__(self, *, payload: dict | None = None) -> None:
        self.payload = dict(payload) if payload is not None else dict(BINANCE_BTC_USDT_EXCHANGE_INFO)
        self.calls: list[tuple[str, str]] = []

    def get(self, url, headers=None):
        self.calls.append(("GET", str(url)))
        if "exchangeInfo" in str(url):
            return dict(self.payload)
        return {}


def test_agreed_binance_wave_pair_spelling() -> None:
    """Wave Binance BTC/USDT spelling is the spot exchangeInfo symbol."""
    assert PAPER_WAVE_BINANCE_BTC_USDT == "BTCUSDT"


def test_fetch_rules_binance_btc_usdt_from_exchange_info() -> None:
    """InstrumentMetadataClient normalizes exchangeInfo into InstrumentRulesV1."""
    transport = _BinanceExchangeInfoTransport()
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)

    record = client.fetch_rules("binance", PAPER_WAVE_BINANCE_BTC_USDT)

    assert record.venue == "binance"
    assert record.canonical_pair == PAPER_WAVE_BINANCE_BTC_USDT
    assert record.venue_symbol == PAPER_WAVE_BINANCE_BTC_USDT
    assert record.base_asset == "BTC"
    assert record.quote_asset == "USDT"
    assert Decimal(record.min_quantity) == Decimal("0.00001")
    assert Decimal(record.min_notional) == Decimal(5)
    assert Decimal(record.quantity_increment) == Decimal("0.00001")
    assert Decimal(record.price_increment) == Decimal("0.01")
    assert record.source["endpoint"] == BINANCE_EXCHANGE_INFO_URL
    assert any("exchangeInfo" in url and "BTCUSDT" in url for _, url in transport.calls)


def test_ensure_instrument_rules_persists_binance_btc_usdt(home: Path) -> None:
    """Production ensure path writes run/instrument-rules.json for BTCUSDT."""
    snapshot_before = home / "run" / SNAPSHOT_FILENAME
    assert not snapshot_before.exists()

    transport = _BinanceExchangeInfoTransport()
    path = ensure_instrument_rules(
        home,
        venue="binance",
        pairs=[PAPER_WAVE_BINANCE_BTC_USDT],
        transport=transport,
        clock=lambda: 1_700_000_000.0,
    )

    assert path is not None
    assert path.is_file()
    body = json.loads(path.read_text(encoding="utf-8"))
    records = body.get("records") or {}
    binance = records.get("binance") or {}
    assert PAPER_WAVE_BINANCE_BTC_USDT in binance, binance.keys()
    wave = binance[PAPER_WAVE_BINANCE_BTC_USDT]
    assert wave["canonical_pair"] == PAPER_WAVE_BINANCE_BTC_USDT
    assert wave["venue_symbol"] == PAPER_WAVE_BINANCE_BTC_USDT
    assert wave["base_asset"] == "BTC"
    assert wave["quote_asset"] == "USDT"
    assert Decimal(wave["min_quantity"]) == Decimal("0.00001")
    assert Decimal(wave["min_notional"]) == Decimal(5)
    assert Decimal(wave["quantity_increment"]) == Decimal("0.00001")
    assert Decimal(wave["price_increment"]) == Decimal("0.01")
    assert any("exchangeInfo" in url for _, url in transport.calls)


def test_ensure_instrument_rules_binance_missing_symbol_writes_nothing(home: Path) -> None:
    """When exchangeInfo cannot supply the symbol, nothing is invented."""
    transport = _BinanceExchangeInfoTransport(payload={"symbols": []})
    path = ensure_instrument_rules(
        home,
        venue="binance",
        pairs=[PAPER_WAVE_BINANCE_BTC_USDT],
        transport=transport,
        clock=lambda: 1_700_000_000.0,
    )
    assert path is None
    assert not (home / "run" / SNAPSHOT_FILENAME).exists()


def test_fetch_rules_binance_error_code_is_unavailable() -> None:
    transport = _BinanceExchangeInfoTransport(payload={"code": -1121, "msg": "Invalid symbol."})
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    try:
        client.fetch_rules("binance", PAPER_WAVE_BINANCE_BTC_USDT)
    except InstrumentMetadataError as exc:
        assert exc.code == METADATA_UNAVAILABLE
    else:
        raise AssertionError("expected InstrumentMetadataError")


def test_fetch_rules_binance_wrong_symbol_is_mismatch() -> None:
    transport = _BinanceExchangeInfoTransport(
        payload={
            "symbols": [
                {
                    "symbol": "ETHUSDT",
                    "baseAsset": "ETH",
                    "quoteAsset": "USDT",
                    "filters": [
                        {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
                        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                        {"filterType": "NOTIONAL", "minNotional": "5"},
                    ],
                }
            ]
        }
    )
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    try:
        client.fetch_rules("binance", PAPER_WAVE_BINANCE_BTC_USDT)
    except InstrumentMetadataError as exc:
        assert exc.code == METADATA_SYMBOL_MISMATCH
    else:
        raise AssertionError("expected InstrumentMetadataError")
