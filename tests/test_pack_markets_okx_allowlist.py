"""Pack markets allow-list admits OKX venue id ``okx``.

Pack validate accepts ``{venue: okx, pair: BTC-USDT}`` within the existing
market-count limits and still rejects an unknown venue id.
"""

from __future__ import annotations

from krellbot.pack.lint import check

_PACK = {
    "schema_version": 1,
    "id": "okx-markets",
    "version": "1.0.0",
    "label": "OKX markets",
    "author": "krellbot tests",
    "timeframe": "1h",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", ">", "sma2"],
    "exit": ["close", "<", "sma2"],
    "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
}


def test_pack_validate_accepts_okx_btc_usdt_market() -> None:
    pack = {**_PACK, "markets": [{"venue": "okx", "pair": "BTC-USDT"}]}
    assert check(pack) == []


def test_pack_validate_still_rejects_unknown_venue_beside_okx() -> None:
    pack = {**_PACK, "markets": [{"venue": "not-a-venue", "pair": "BTC-USDT"}]}
    errors = check(pack)
    assert errors
    joined = " ".join(f"{e.get('field', '')} {e.get('message', '')}" for e in errors).lower()
    assert "venue" in joined or "enum" in joined
