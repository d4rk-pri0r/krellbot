"""Pin the Kraken adapter to documented REST response shapes (M1.6).

Fixtures under ``tests/fixtures/venues/kraken/`` are derived from Kraken's
REST documentation, not recorded from a real account. Each fixture maps to
exactly one ``KrakenDocumentedOutcome`` via ``classify_documented_response``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from krellbot.venues.kraken import KrakenDocumentedOutcome, classify_documented_response

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "venues" / "kraken"

PROVENANCE_MARKER = "derived from Kraken's REST documentation, not recorded from a real account"

CASES = (
    ("order_accepted", KrakenDocumentedOutcome.ORDER_ACCEPTED),
    ("insufficient_funds", KrakenDocumentedOutcome.INSUFFICIENT_FUNDS),
    ("order_minimum_not_met", KrakenDocumentedOutcome.ORDER_MINIMUM_NOT_MET),
    ("rate_limit", KrakenDocumentedOutcome.RATE_LIMIT),
    ("invalid_nonce", KrakenDocumentedOutcome.INVALID_NONCE),
    ("no_response", KrakenDocumentedOutcome.NO_RESPONSE),
    ("partially_filled", KrakenDocumentedOutcome.PARTIALLY_FILLED),
    ("stop_triggered", KrakenDocumentedOutcome.STOP_TRIGGERED),
    ("cancel_accepted", KrakenDocumentedOutcome.CANCEL_ACCEPTED),
)


def _load_fixture(name: str) -> object:
    path = FIXTURES / f"{name}.json"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines, f"empty fixture: {path}"
    assert lines[0].startswith("#"), f"fixture must start with a comment: {path}"
    assert PROVENANCE_MARKER.lower() in lines[0].lower(), f"fixture missing provenance comment: {path}"
    body = "\n".join(lines[1:]).strip()
    return json.loads(body)


@pytest.mark.parametrize(("fixture_name", "expected"), CASES)
def test_documented_kraken_fixture_maps_to_typed_outcome(fixture_name: str, expected: str) -> None:
    """Each documented fixture classifies to exactly one typed adapter outcome."""
    payload = _load_fixture(fixture_name)
    assert classify_documented_response(payload) == expected
    assert expected in KrakenDocumentedOutcome.values()
