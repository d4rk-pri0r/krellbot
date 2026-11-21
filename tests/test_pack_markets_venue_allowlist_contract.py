"""Pack markets venue allow-list must stay documented and fail closed.

Undocumented venue ids must not be accepted by pack validate. Every venue id
in the pack JSON Schema enum must appear in ``docs/pack-format.md``. The
Binance-class spot id ``binance`` and its concatenated ``BASEQUOTE`` pair
spelling (wave pair ``BTCUSDT``) are named in that doc; the schema enum must
stay a subset of the documented allow-list.
"""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path

from krellbot.pack.lint import check

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACK_FORMAT = _REPO_ROOT / "docs" / "pack-format.md"

# Documented allow-list for pack markets (must match docs/pack-format.md).
DOCUMENTED_PACK_MARKET_VENUES = frozenset({"kraken", "coinbase", "binance", "gate", "pionex", "okx"})

_MINIMAL_PACK = {
    "schema_version": 1,
    "id": "allowlist-contract",
    "version": "1.0.0",
    "label": "Allow-list contract",
    "author": "krellbot tests",
    "timeframe": "1h",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", ">", "sma2"],
    "exit": ["close", "<", "sma2"],
    "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
}


def _schema_market_venues() -> frozenset[str]:
    raw = resources.files("krellbot.pack").joinpath("schema.json").read_text(encoding="utf-8")
    schema = json.loads(raw)
    enum = schema["$defs"]["market"]["properties"]["venue"]["enum"]
    return frozenset(enum)


def test_pack_format_documents_binance_venue_id_and_pair_rules() -> None:
    text = _PACK_FORMAT.read_text(encoding="utf-8")
    assert re.search(r"\bbinance\b", text), "docs/pack-format.md must name venue id binance"
    assert re.search(r"Binance", text), "docs/pack-format.md must name Binance-class spot"
    assert "BTCUSDT" in text, "docs/pack-format.md must name Binance wave pair BTCUSDT"
    assert "BASEQUOTE" in text or "concatenated" in text.lower()
    for method in (
        "rules",
        "snapshot",
        "place_entry_with_stop",
        "place_exit",
        "cancel_stops",
        "raise_stop",
        "order_by_coid",
        "check_key",
    ):
        assert method in text, f"docs/pack-format.md must name Venue method {method}"


def test_schema_venues_are_subset_of_documented_allowlist() -> None:
    """Fail closed: schema must not admit a venue the docs never named."""
    schema_venues = _schema_market_venues()
    undocumented = schema_venues - DOCUMENTED_PACK_MARKET_VENUES
    assert not undocumented, (
        f"pack schema admits undocumented venue id(s) {sorted(undocumented)}; "
        "update docs/pack-format.md markets allow-list before expanding the enum"
    )
    for venue in schema_venues:
        assert venue in _PACK_FORMAT.read_text(encoding="utf-8"), (
            f"venue {venue!r} is in schema enum but missing from docs/pack-format.md"
        )


def test_pack_validate_rejects_undocumented_venue_id() -> None:
    """Pack validate must refuse a venue id that is not on the allow-list."""
    pack = {
        **_MINIMAL_PACK,
        "markets": [{"venue": "undocumented_xyz", "pair": "BTCUSDT"}],
    }
    errors = check(pack)
    assert errors, "expected pack validate to reject undocumented venue id"
    joined = " ".join(f"{e.get('field', '')} {e.get('message', '')}" for e in errors).lower()
    assert "venue" in joined or "enum" in joined or "undocumented_xyz" in joined


def test_documented_binance_id_is_named_for_future_admission() -> None:
    """Pin the chosen Binance-class id so later tasks do not rename silently."""
    assert "binance" in DOCUMENTED_PACK_MARKET_VENUES
    text = _PACK_FORMAT.read_text(encoding="utf-8")
    assert "`binance`" in text or '"binance"' in text or "| `binance`" in text
