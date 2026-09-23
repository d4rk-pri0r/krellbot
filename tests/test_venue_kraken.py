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
    call = next(c for c in transport.calls if c.url.endswith("/AddOrder"))
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
    nonces = [int(call.form["nonce"]) for call in second_transport.calls]
    assert nonces == sorted(set(nonces))
    assert int(nonce_path.read_text(encoding="utf-8").strip()) == nonces[-1]


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
    adds = [c for c in transport.calls if c.url.endswith("/AddOrder")]
    assert adds[0].headers["API-Sign"] != adds[1].headers["API-Sign"]


def test_kraken_rules_reads_asset_pairs(home):
    """SUIUSD minimums come from AssetPairs, not a hardcoded 0.0001."""
    transport = FakeKrakenTransport(
        asset_pairs={
            "SUIUSD": {
                "ordermin": "5",
                "costmin": "0.5",
                "lot_decimals": 5,
                "pair_decimals": 4,
            }
        }
    )
    venue = _build_venue(transport, home)
    rules = venue.rules("SUIUSD")
    assert rules.ordermin == Decimal(5)
    assert rules.costmin == Decimal("0.5")
    assert rules.lot_decimals == 5
    assert rules.price_decimals == 4


def test_kraken_rejects_qty_below_ordermin(home):
    transport = FakeKrakenTransport(
        asset_pairs={
            "SUIUSD": {
                "ordermin": "5",
                "costmin": "0.5",
                "lot_decimals": 5,
                "pair_decimals": 4,
            }
        },
        ticker_last="1",
    )
    venue = _build_venue(transport, home)
    with pytest.raises(ValueError, match="ordermin"):
        venue.place_entry_with_stop("coid-small", Decimal(1), Decimal(1), pair="SUIUSD")
    assert not any(c.url.endswith("/AddOrder") for c in transport.calls)


def test_kraken_rejects_notional_below_costmin(home):
    transport = FakeKrakenTransport(
        asset_pairs={
            "SUIUSD": {
                "ordermin": "1",
                "costmin": "10",
                "lot_decimals": 5,
                "pair_decimals": 4,
            }
        },
        ticker_last="1",
    )
    venue = _build_venue(transport, home)
    with pytest.raises(ValueError, match="costmin"):
        venue.place_entry_with_stop("coid-dust", Decimal(2), Decimal(1), pair="SUIUSD")
    assert not any(c.url.endswith("/AddOrder") for c in transport.calls)


def test_kraken_snapshot_parses_documented_envelope(home):
    open_book = {
        "O-STOP": {
            "userref": 1,
            "cl_ord_id": "stop-1",
            "vol": "1.25",
            "stopprice": "30000.0",
            "descr": {
                "pair": "XBTUSD",
                "type": "sell",
                "ordertype": "stop-loss",
                "price": "30000.0",
            },
        },
        "O-LIMIT": {
            "userref": 2,
            "vol": "0.1",
            "stopprice": "0.00000",
            "descr": {
                "pair": "XBTUSD",
                "type": "buy",
                "ordertype": "limit",
                "price": "10.0",
            },
        },
    }
    transport = FakeKrakenTransport(
        responses=[
            {"error": [], "result": {"XXBT": "1.5", "ZUSD": "20"}},
            {"error": [], "result": {"trades": {}}},
        ],
        open_orders={"error": [], "result": {"open": open_book}},
    )
    venue = _build_venue(transport, home)
    truth = venue.snapshot()
    assert {b.asset: b.free for b in truth.balances} == {
        "XXBT": Decimal("1.5"),
        "ZUSD": Decimal(20),
    }
    stops = [o for o in truth.open_orders if o.stop_price is not None]
    assert len(stops) == 1
    assert stops[0].id == "O-STOP"
    assert stops[0].pair == "XBTUSD"
    assert stops[0].stop_price == Decimal("30000.0")


def test_kraken_duplicate_userref_is_not_resent(home):
    userref = coid_userref("coid-again")
    transport = FakeKrakenTransport(
        open_orders={
            "error": [],
            "result": {
                "open": {
                    "O-EXISTING": {
                        "userref": userref,
                        "cl_ord_id": "coid-again",
                        "vol": "1.25",
                        "stopprice": "37500.0",
                        "descr": {
                            "pair": "XBTUSD",
                            "type": "buy",
                            "ordertype": "market",
                            "price": "0",
                        },
                    }
                }
            },
        }
    )
    venue = _build_venue(transport, home)
    ref = venue.place_entry_with_stop("coid-again", Decimal("1.25"), Decimal(37500), pair="XBTUSD")
    assert ref.id == "O-EXISTING"
    assert not any(c.url.endswith("/AddOrder") for c in transport.calls)


def test_kraken_rate_limit_retries_then_journals(home):
    waits: list[float] = []
    transport = FakeKrakenTransport(rate_limit_first_n=3)
    venue = KrakenVenue(
        api_key=KRAKEN_TEST_KEY,
        secret_b64=KRAKEN_TEST_SECRET,
        transport=transport,
        now_ms=lambda: 1_700_000_000_000_000,
        min_interval_ms=0,
        home=home,
        sleep=waits.append,
    )
    with pytest.raises(Exception, match="rate limit") as ei:
        venue.place_entry_with_stop("coid-rl", Decimal("1.25"), Decimal(100), pair="XBTUSD")
    assert KRAKEN_TEST_SECRET not in str(ei.value)
    assert waits == [300.0, 600.0]
    add_orders = [c for c in transport.calls if c.url.endswith("/AddOrder")]
    assert len(add_orders) == 3
    journal = home / "journal" / "2023-11.jsonl"
    text = journal.read_text(encoding="utf-8")
    assert '"kind":"rate_limit"' in text
    assert '"detail":"rate limit"' in text
    assert KRAKEN_TEST_SECRET not in text
    assert KRAKEN_TEST_KEY not in text
