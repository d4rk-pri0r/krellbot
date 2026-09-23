"""Kraken venue adapter tests.

All HTTP is fake. Tests inject the clock, the transport, and `KRELLBOT_HOME`
through the `home` fixture so no file lands under `~/.krellbot`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fakes.fake_kraken import FakeKrakenTransport

from krellbot.venues.base import WithdrawCapableError
from krellbot.venues.kraken import (
    NONCE_FILENAME,
    KrakenVenue,
    coid_userref,
    sign,
)

KRAKEN_TEST_KEY = "FAKE_KEY_FOR_KRAKEN_TESTS"
KRAKEN_TEST_SECRET = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="


def _now_ms_constant(start_ms: int):
    """Return a clock that hands out a monotonic counter starting at start_ms."""
    state = {"t": start_ms}

    def _now():
        state["t"] += 1
        return state["t"]

    return _now


def _build_venue(transport, home, *, now_ms=None, min_interval_ms=0):
    return KrakenVenue(
        api_key=KRAKEN_TEST_KEY,
        secret_b64=KRAKEN_TEST_SECRET,
        transport=transport,
        now_ms=now_ms or (lambda: 1700000000000),
        min_interval_ms=min_interval_ms,
        home=home,
    )


def test_kraken_sign_matches_doc_example(home):
    """Locked Kraken auth vector from the public docs must round-trip exactly."""

    secret = KRAKEN_TEST_SECRET
    nonce = "1616492376594"
    postdata = "nonce=1616492376594&ordertype=limit&pair=XBTUSD&price=37500&type=buy&volume=1.25"
    path = "/0/private/AddOrder"
    expected = "4/dpxb3iT4tp/ZCVEwSnEsLxx0bqyhLpdfOpc6fn7OR8+UClSV5n9E6aSS8MPtnRfp32bAb0nmbRn6H8ndwLUQ=="
    assert sign(secret, path, nonce, postdata) == expected


def test_kraken_entry_attaches_conditional_stop(home):
    """Entry must be a market order with a stop-loss attached via `close[...]`.

    The form must carry `ordertype=market`, the stop-loss instructions in the
    `close` group, the `cl_ord_id` echo, and the masked userref of `coid`.
    """
    transport = FakeKrakenTransport(
        responses=[{"result": {"txid": ["AAABBBCCC"]}}],
    )
    venue = _build_venue(transport, home, min_interval_ms=0)
    ref = venue.place_entry_with_stop("mycoid-1", Decimal("1.25"), Decimal(37500), pair="XBTUSD")

    assert ref.id == "AAABBBCCC"
    assert ref.side == "buy"
    assert transport.calls, "transport must record the post"
    call = transport.calls[0]
    assert call.url.endswith("/0/private/AddOrder")
    assert call.form["pair"] == "XBTUSD"
    assert call.form["ordertype"] == "market"
    assert call.form["type"] == "buy"
    assert call.form["volume"] == "1.25000000"
    assert call.form["close[ordertype]"] == "stop-loss"
    assert call.form["close[price]"] == "37500.00000"
    assert call.form["cl_ord_id"] == "mycoid-1"
    assert int(call.form["userref"]) == coid_userref("mycoid-1")
    # Header is signed under API-Sign.
    assert call.headers["API-Key"] == KRAKEN_TEST_KEY
    assert call.headers["API-Sign"] and len(call.headers["API-Sign"]) > 16


def test_kraken_nonce_monotonic_across_restarts(home):
    """Two venues against one nonce file: second must never reuse a value."""
    first_transport = FakeKrakenTransport(
        responses=[{"result": {"txid": ["TX1"]}}],
    )
    first = _build_venue(
        first_transport,
        home,
        now_ms=lambda: 1700000000000,
        min_interval_ms=0,
    )
    first.place_entry_with_stop("coid-A", Decimal("0.1"), Decimal(100), pair="XBTUSD")

    nonce_path = home / "run" / NONCE_FILENAME
    assert nonce_path.exists()
    first_nonce_written = int(nonce_path.read_text(encoding="utf-8").strip())
    assert first_nonce_written >= 1700000000000

    # Second "restart": a fresh venue reads the persisted file, sees a
    # backward clock, and must still emit a nonce strictly greater than the
    # one that was persisted.
    second_transport = FakeKrakenTransport(
        responses=[{"result": {"txid": ["TX2"]}}],
    )
    second = _build_venue(
        second_transport,
        home,
        now_ms=lambda: 1,  # wall clock way in the past
        min_interval_ms=0,
    )
    second.place_entry_with_stop("coid-B", Decimal("0.1"), Decimal(100), pair="XBTUSD")

    second_call_nonce = int(second_transport.calls[0].form["nonce"])
    assert second_call_nonce > first_nonce_written
    on_disk = int(nonce_path.read_text(encoding="utf-8").strip())
    assert on_disk == second_call_nonce


def test_kraken_withdraw_capable_key_refused(home):
    """WithdrawMethods returning >0 methods means the key can withdraw: refused."""
    transport = FakeKrakenTransport(
        responses=[],
        withdraw_methods=[{"method": "Bitcoin", "address": "abc"}],
    )
    venue = _build_venue(transport, home, min_interval_ms=0)
    with pytest.raises(WithdrawCapableError) as excinfo:
        venue.check_key()
    assert KRAKEN_TEST_KEY not in str(excinfo.value)
    assert KRAKEN_TEST_SECRET not in str(excinfo.value)


def test_kraken_signature_header_uses_postdata_body(home):
    """Sanity: a different postdata must yield a different API-Sign.

    Locks the formula against silent substitutions (e.g. SHA256 vs HMAC-SHA512,
    or wrong header encoding).
    """
    transport = FakeKrakenTransport(
        responses=[
            {"result": {"txid": ["T1"]}},
            {"result": {"txid": ["T2"]}},
        ],
    )
    clock = _now_ms_constant(1700000000000)
    venue = _build_venue(transport, home, now_ms=clock, min_interval_ms=0)
    venue.place_entry_with_stop("coid-X", Decimal("0.10"), Decimal(100), pair="XBTUSD")
    venue.place_entry_with_stop("coid-Y", Decimal("0.10"), Decimal(100), pair="XBTUSD")
    s1 = transport.calls[0].headers["API-Sign"]
    s2 = transport.calls[1].headers["API-Sign"]
    assert s1 != s2
