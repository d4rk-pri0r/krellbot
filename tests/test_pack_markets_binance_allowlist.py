"""Pack markets allow-list admits Binance-class venue id ``binance``.

Pack validate accepts ``{venue: binance, pair: BTCUSDT}`` within the existing
1–4 market limit and rejects unknown venue ids with a field-scoped lint error.
Starters may stay on Kraken.
"""

from __future__ import annotations

from krellbot.pack.lint import check

_MINIMAL = {
    "schema_version": 1,
    "id": "binance-markets",
    "version": "1.0.0",
    "label": "Binance markets",
    "author": "krellbot tests",
    "timeframe": "1h",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", ">", "sma2"],
    "exit": ["close", "<", "sma2"],
    "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
}


def test_pack_validate_accepts_binance_btc_usdt_market() -> None:
    pack = {
        **_MINIMAL,
        "markets": [{"venue": "binance", "pair": "BTCUSDT"}],
    }
    assert check(pack) == []


def test_pack_validate_accepts_binance_among_mixed_venues_within_limit() -> None:
    pack = {
        **_MINIMAL,
        "markets": [
            {"venue": "kraken", "pair": "SUIUSD"},
            {"venue": "coinbase", "pair": "BTC-USD"},
            {"venue": "binance", "pair": "BTCUSDT"},
        ],
    }
    assert check(pack) == []


def test_pack_validate_rejects_unknown_venue_id_with_typed_field_error() -> None:
    pack = {
        **_MINIMAL,
        "markets": [{"venue": "not_a_venue", "pair": "BTCUSDT"}],
    }
    errors = check(pack)
    assert errors, "expected refusal for unknown venue id"
    assert any(
        (e.get("field") or "").startswith("markets")
        and (
            "venue" in (e.get("field") or "")
            or "enum" in (e.get("message") or "").lower()
            or "not_a_venue" in (e.get("message") or "")
        )
        for e in errors
    ), errors
    # Typed shape: lint errors are dicts with field + message (not bare strings).
    for err in errors:
        assert isinstance(err, dict)
        assert "field" in err and "message" in err
        assert isinstance(err["field"], str) and isinstance(err["message"], str)


def test_pack_validate_still_enforces_market_count_limit() -> None:
    pack = {
        **_MINIMAL,
        "markets": [
            {"venue": "binance", "pair": "BTCUSDT"},
            {"venue": "binance", "pair": "ETHUSDT"},
            {"venue": "kraken", "pair": "SUIUSD"},
            {"venue": "coinbase", "pair": "BTC-USD"},
            {"venue": "kraken", "pair": "XXBTZUSD"},
        ],
    }
    errors = check(pack)
    assert errors
    joined = " ".join(f"{e.get('field')} {e.get('message')}" for e in errors).lower()
    assert "markets" in joined
