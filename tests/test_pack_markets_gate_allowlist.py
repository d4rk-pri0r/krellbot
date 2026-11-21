"""Pack markets allow-list admits Gate venue id ``gate``."""

from __future__ import annotations

from krellbot.pack.lint import check

_MINIMAL = {
    "schema_version": 1,
    "id": "gate-markets",
    "version": "1.0.0",
    "label": "Gate markets",
    "author": "krellbot tests",
    "timeframe": "1h",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", ">", "sma2"],
    "exit": ["close", "<", "sma2"],
    "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
}


def test_pack_validate_accepts_gate_btc_usdt_market() -> None:
    pack = {
        **_MINIMAL,
        "markets": [{"venue": "gate", "pair": "BTC-USDT"}],
    }
    assert check(pack) == []


def test_pack_validate_rejects_unknown_venue_id_with_typed_field_error() -> None:
    pack = {
        **_MINIMAL,
        "markets": [{"venue": "not_a_venue", "pair": "BTC-USDT"}],
    }
    errors = check(pack)
    assert errors
    assert any((item.get("field") or "").startswith("markets") for item in errors), errors
