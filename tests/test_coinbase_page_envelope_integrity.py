"""Synthetic page-envelope qualification; no live venue or performance claims."""

from __future__ import annotations

import json
import socket
import urllib.request
from collections import UserDict
from decimal import Decimal

import keyring
import pytest

from krellbot import tls
from krellbot.application.research import ResearchRequest, ResearchService
from krellbot.data.coinbase_public import (
    COINBASE_URL,
    MAX_REQUESTS,
    PAGE_LIMIT,
    HttpTransport,
    TransportError,
    fetch_coinbase_candles,
)

START = 1_700_000_000
STEP = 3600


def _row(index, close="10"):
    return {
        "start": str(START + index * STEP),
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": "1",
    }


def _healthy_page():
    return {"candles": [_row(0), _row(1, "11"), _row(2, "12")]}


class PageTransport:
    """Return exactly the supplied decoded bodies, with no implicit empty page."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, params):
        self.calls.append((url, dict(params)))
        assert self.pages, "unexpected additional request"
        return self.pages.pop(0)


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("real network/keyring access is forbidden")

    monkeypatch.setattr(HttpTransport, "get", forbidden)
    monkeypatch.setattr(tls, "urlopen", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    for name in ("get_keyring", "get_password", "set_password", "delete_password"):
        monkeypatch.setattr(keyring, name, forbidden)


MALFORMED_PAGES = [
    pytest.param({"error": "synthetic HTTP-200 error body"}, id="error-envelope"),
    pytest.param({}, id="missing-candles"),
    pytest.param({"candles": None}, id="null-candles"),
    pytest.param({"candles": {}}, id="object-candles"),
    pytest.param({"candles": {"start": "1700000000"}}, id="nonempty-object-candles"),
    pytest.param({"candles": ""}, id="empty-string-candles"),
    pytest.param({"candles": "error"}, id="string-candles"),
    pytest.param({"candles": False}, id="false-candles"),
    pytest.param({"candles": 0}, id="zero-candles"),
    pytest.param({"candles": 1}, id="number-candles"),
    pytest.param({"candles": ()}, id="tuple-candles"),
    pytest.param(None, id="null-body"),
    pytest.param([], id="list-body"),
    pytest.param("error", id="string-body"),
    pytest.param(False, id="boolean-body"),
    pytest.param(200, id="number-body"),
]


@pytest.mark.parametrize("malformed", MALFORMED_PAGES)
@pytest.mark.parametrize("later_page", [False, True], ids=["first-page", "second-page"])
def test_fetch_rejects_malformed_envelope_without_returning_partial_history(malformed, later_page):
    pages = ([_healthy_page()] if later_page else []) + [malformed]
    transport = PageTransport(pages)

    with pytest.raises(TransportError):
        fetch_coinbase_candles("SUI-USD", "1h", transport)

    assert len(transport.calls) == (2 if later_page else 1)
    assert transport.pages == []
    if later_page:
        assert transport.calls[1][1]["start"] == str(START + 3 * STEP)


@pytest.fixture
def research_request(tmp_path):
    pack = {
        "schema_version": 1,
        "id": "envelope-test",
        "version": "1.0.0",
        "label": "Synthetic envelope qualification",
        "author": "krellbot tests",
        "timeframe": "1h",
        "origin": "Synthetic test only.",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "coinbase", "pair": "SUI-USD"}],
    }
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(pack), encoding="utf-8")
    return ResearchRequest(pack_path=path, venue="coinbase")


def _research(tmp_path, request, transport):
    def fetch(venue, pair, tf):
        assert (venue, pair, tf) == ("coinbase", "SUI-USD", "1h")
        return fetch_coinbase_candles(pair, tf, transport)

    return ResearchService(home=tmp_path, fetch=fetch).run(request)


@pytest.mark.parametrize("malformed", MALFORMED_PAGES)
@pytest.mark.parametrize("later_page", [False, True], ids=["first-page", "second-page"])
def test_research_refuses_malformed_envelope_without_success_receipt(tmp_path, research_request, malformed, later_page):
    pages = ([_healthy_page()] if later_page else []) + [malformed]
    transport = PageTransport(pages)

    result = _research(tmp_path, research_request, transport)

    assert result.ok is False
    assert result.legacy_receipt is None
    assert result.refusal == {"code": "invalid_dataset", "message": "fetch failed: TransportError"}
    assert result.detail == {"schema_version": "1", "refusal": result.refusal}
    assert len(transport.calls) == (2 if later_page else 1)
    assert transport.pages == []


@pytest.mark.parametrize(
    "tf,step,granularity", [("1h", 3600, "ONE_HOUR"), ("4h", 14400, "FOUR_HOUR"), ("1d", 86400, "ONE_DAY")]
)
def test_valid_pages_keep_sort_dedup_cursor_and_request_parameters(tf, step, granularity):
    def row(index, close):
        return {**_row(index, close), "start": str(START + index * step)}

    transport = PageTransport(
        [
            {"candles": [row(2, "12"), row(0, "10"), row(1, "11"), row(0, "99")]},
            {"candles": [row(3, "13"), row(2, "99")]},
            {"candles": []},
        ]
    )
    end = START + 10 * step
    candles = fetch_coinbase_candles("SUI-USD", tf, transport, start_unix_s=START, end_unix_s=end)

    assert [c.ts_ms for c in candles] == [(START + i * step) * 1000 for i in range(4)]
    assert [c.close for c in candles] == [Decimal(10), Decimal(11), Decimal(12), Decimal(13)]
    assert transport.calls == [
        (
            COINBASE_URL.format(product_id="SUI-USD"),
            {"granularity": granularity, "limit": str(PAGE_LIMIT), "start": str(cursor), "end": str(end)},
        )
        for cursor in (START, START + 3 * step, START + 4 * step)
    ]
    assert transport.pages == []


def test_explicit_fresh_empty_list_returns_empty_without_extra_request():
    transport = PageTransport([{"candles": []}])
    assert fetch_coinbase_candles("SUI-USD", "1h", transport) == []
    assert len(transport.calls) == 1
    assert "start" not in transport.calls[0][1]


def test_mapping_envelope_is_admitted():
    transport = PageTransport([UserDict(_healthy_page()), UserDict({"candles": []})])
    assert len(fetch_coinbase_candles("SUI-USD", "1h", transport)) == 3
    assert len(transport.calls) == 2


def test_duplicate_only_page_still_terminates_without_extra_request():
    transport = PageTransport([_healthy_page(), _healthy_page()])
    assert len(fetch_coinbase_candles("SUI-USD", "1h", transport)) == 3
    assert len(transport.calls) == 2


def test_existing_bad_row_skipping_within_valid_list_is_unchanged():
    bad_rows = [None, "not-a-row", {}, {"start": "not-an-integer"}]
    transport = PageTransport([{"candles": [*bad_rows, _row(0)]}, {"candles": bad_rows}])
    candles = fetch_coinbase_candles("SUI-USD", "1h", transport)
    assert len(candles) == 1
    assert candles[0].ts_ms == START * 1000
    assert candles[0].close == Decimal(10)
    assert len(transport.calls) == 2


def test_valid_pages_keep_exact_request_cap():
    assert MAX_REQUESTS == 100
    assert PAGE_LIMIT == 350
    transport = PageTransport([{"candles": [_row(i)]} for i in range(MAX_REQUESTS + 1)])
    with pytest.raises(TransportError, match="pagination exceeded 100 requests"):
        fetch_coinbase_candles("SUI-USD", "1h", transport)
    assert len(transport.calls) == MAX_REQUESTS
    assert len(transport.pages) == 1


def test_explicit_empty_final_allowed_request_still_succeeds():
    pages = [{"candles": [_row(i)]} for i in range(MAX_REQUESTS - 1)] + [{"candles": []}]
    transport = PageTransport(pages)
    assert len(fetch_coinbase_candles("SUI-USD", "1h", transport)) == MAX_REQUESTS - 1
    assert len(transport.calls) == MAX_REQUESTS


@pytest.mark.parametrize("multi_page", [False, True], ids=["healthy-then-empty", "multi-then-empty"])
def test_research_valid_history_still_produces_success_receipt(tmp_path, research_request, multi_page):
    pages = [_healthy_page()]
    if multi_page:
        pages.append({"candles": [_row(3, "13"), _row(2, "99")]})
    transport = PageTransport([*pages, {"candles": []}])
    result = _research(tmp_path, research_request, transport)
    assert result.ok is True
    assert isinstance(result.legacy_receipt, dict)
    assert result.refusal is None
    assert result.detail["bar_count"] == (4 if multi_page else 3)
    assert len(transport.calls) == (3 if multi_page else 2)


def test_research_fresh_explicit_empty_remains_empty_dataset(tmp_path, research_request):
    transport = PageTransport([{"candles": []}])
    result = _research(tmp_path, research_request, transport)
    assert result.ok is False
    assert result.legacy_receipt is None
    assert result.refusal["code"] == "empty_dataset"
    assert len(transport.calls) == 1
