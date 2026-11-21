"""Pack markets allow-list admits KuCoin venue id ``kucoin``."""

from __future__ import annotations

from krellbot.pack.lint import check

_MINIMAL = {
    "schema_version": 1,
    "id": "kucoin-markets",
    "version": "1.0.0",
    "label": "KuCoin markets",
    "author": "krellbot tests",
    "timeframe": "1h",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", ">", "sma2"],
    "exit": ["close", "<", "sma2"],
    "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
}


def test_pack_validate_accepts_kucoin_btc_usdt_market() -> None:
    pack = {
        **_MINIMAL,
        "markets": [{"venue": "kucoin", "pair": "BTC-USDT"}],
    }
    assert check(pack) == []


def test_pack_validate_rejects_kucoineu_as_a_separate_venue_id() -> None:
    """``kucoineu`` stays in the KuCoin family and is not its own id."""
    pack = {
        **_MINIMAL,
        "markets": [{"venue": "kucoineu", "pair": "BTC-USDT"}],
    }
    errors = check(pack)
    assert errors
    assert any((item.get("field") or "").startswith("markets") for item in errors), errors
