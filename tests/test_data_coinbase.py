"""Data: coinbase_public.py - candles parser + paginated transport."""

from __future__ import annotations

from decimal import Decimal

import pytest

from krellbot.data.coinbase_public import (
    COINBASE_URL,
    MAX_REQUESTS,
    PAGE_LIMIT,
    fetch_coinbase_candles,
    parse_coinbase_candles,
)


class FakeTransport:
    """Records every GET and returns pages of candles in order.

    `pages` is a list of bodies, each a `{"candles": [...]}`. The transport
    serves them one by one; the next page is empty when the list is
    exhausted, which the engine treats as the end of pagination.
    """

    def __init__(self, pages: list[dict]):
        self.pages = pages
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: dict[str, str]):
        self.calls.append((url, dict(params)))
        if not self.pages:
            return {"candles": []}
        return self.pages.pop(0)


def _row(start_unix_s: int, close: str) -> dict:
    return {
        "start": str(start_unix_s),
        "low": close,
        "high": close,
        "open": close,
        "close": close,
        "volume": "1",
    }


def test_coinbase_second_page_is_requested():
    """The fake returns two pages; the engine must request at least two."""
    page1 = {"candles": [_row(1_700_000_000, "10"), _row(1_700_003_600, "11")]}
    page2 = {"candles": [_row(1_700_007_200, "12"), _row(1_700_010_800, "13")]}
    transport = FakeTransport([page1, page2])
    candles = fetch_coinbase_candles("SUI-USD", "1h", transport)
    assert len(transport.calls) >= 2, f"expected at least 2 requests, got {len(transport.calls)}"
    second_page_params = transport.calls[1][1]
    assert "start" in second_page_params, "second page must use a cursor"
    assert len(candles) == 4
    assert [c.close for c in candles] == [Decimal(10), Decimal(11), Decimal(12), Decimal(13)]


def test_coinbase_pagination_stops_when_empty():
    """When a page is empty, pagination stops."""
    transport = FakeTransport([{"candles": [_row(1_700_000_000, "10")]}, {"candles": []}])
    candles = fetch_coinbase_candles("SUI-USD", "1h", transport)
    assert len(candles) == 1
    assert len(transport.calls) == 2


def test_coinbase_dedupes_across_pages():
    """Same start twice keeps the first."""
    page1 = {"candles": [_row(1_700_000_000, "10"), _row(1_700_003_600, "11")]}
    page2 = {"candles": [_row(1_700_003_600, "11"), _row(1_700_007_200, "12")]}
    transport = FakeTransport([page1, page2])
    candles = fetch_coinbase_candles("SUI-USD", "1h", transport)
    assert len(candles) == 3
    assert candles[1].close == Decimal(11)


def test_coinbase_pagination_caps_requests():
    """100 identical pages still terminate (no new rows -> stop)."""
    same = {"candles": [_row(1_700_000_000, "10")]}
    transport = FakeTransport([same] * MAX_REQUESTS)
    fetch_coinbase_candles("SUI-USD", "1h", transport)
    # Pagination stops when a window adds nothing -> 2 requests total.
    assert len(transport.calls) == 2


def test_coinbase_exceeds_cap_raises():
    """If every page returns new rows forever, raise after MAX_REQUESTS."""
    # Each page returns a fresh row. The cursor advances by 1 tf (3600s).
    # After MAX_REQUESTS, raise.
    pages = []
    for i in range(MAX_REQUESTS + 5):
        pages.append({"candles": [_row(1_700_000_000 + i * 3600, str(10 + i))]})
    transport = FakeTransport(pages)
    with pytest.raises(RuntimeError):
        fetch_coinbase_candles("SUI-USD", "1h", transport)


def test_coinbase_parses_single_body_sorted():
    """parse_coinbase_candles sorts ascending and dedupes on start."""
    body = {
        "candles": [
            _row(1_700_007_200, "12"),
            _row(1_700_000_000, "10"),
            _row(1_700_000_000, "10"),  # duplicate
        ]
    }
    candles = parse_coinbase_candles(body)
    assert [c.close for c in candles] == [Decimal(10), Decimal(12)]


def test_coinbase_page_limit_is_350():
    """The page limit is locked at 350."""
    assert PAGE_LIMIT == 350


def test_coinbase_url_template():
    """URL contains the product id."""
    assert "{product_id}" in COINBASE_URL
