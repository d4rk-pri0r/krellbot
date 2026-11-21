"""Pionex spot adapter: Venue protocol behind injectable fakes.

CI must never open a network socket to Pionex. ``PionexVenue`` requires an
explicit ``Transport``; ``None`` refuses rather than defaulting to
``HttpTransport``. Order mutations still go through
``release_policy.ensure_live_orders_allowed``.
"""

from __future__ import annotations

import re
from decimal import Decimal
from urllib.parse import urlparse

import pytest
from fakes.fake_pionex import FakePionexTransport

from krellbot.release_policy import PAPER_ONLY_RELEASE, PaperOnlyReleaseError
from krellbot.venues.base import WithdrawCapableError
from krellbot.venues.pionex import API_HOST, BASE_URL, HttpTransport, PionexVenue, sign_pionex

pytestmark = pytest.mark.usefixtures("live_capable_release")

WAVE_PAIR = "BTC-USDT"
VENUE_SYMBOL = "BTC_USDT"
_PACK_PAIR = re.compile(r"^[A-Z0-9]{2,16}(-[A-Z0-9]{2,16})?$")


def _venue(transport: FakePionexTransport, **kwargs) -> PionexVenue:
    return PionexVenue(
        key_id="PIONEX-SYNTHETIC-KEY",
        api_secret="PIONEX-SYNTHETIC-SECRET",
        transport=transport,
        now_fn=lambda: 1_541_993_715_000,
        **kwargs,
    )


def test_pionex_wave_pair_matches_pack_pattern() -> None:
    """The paper wave pair is the hyphenated pack form, not a second venue id."""
    assert _PACK_PAIR.fullmatch(WAVE_PAIR)
    assert WAVE_PAIR == "BTC-USDT"


def test_pionex_venue_refuses_none_transport() -> None:
    """No silent HttpTransport default — tests must inject a fake."""
    with pytest.raises(ValueError, match="transport is required"):
        PionexVenue(key_id="k", api_secret="s", transport=None)  # type: ignore[arg-type]


def test_pionex_http_transport_is_not_used_by_adapter_default() -> None:
    """Constructor has no network default; HttpTransport is opt-in only."""
    transport = FakePionexTransport()
    venue = _venue(transport)
    assert not isinstance(venue._transport, HttpTransport)
    assert venue._transport is transport


def test_pionex_rules_map_btc_usdt_pack_pair_to_symbol() -> None:
    transport = FakePionexTransport()
    rules = _venue(transport).rules(WAVE_PAIR)
    assert rules.ordermin == Decimal("0.000001")
    assert rules.costmin == Decimal(10)
    assert rules.lot_decimals == 6
    assert rules.price_decimals == 2
    gets = [c for c in transport.calls if c.method == "GET"]
    assert gets
    assert "/api/v1/common/symbols" in gets[0].url
    assert "symbols=BTC_USDT" in gets[0].url
    parsed = urlparse(gets[0].url)
    assert parsed.hostname == API_HOST
    assert gets[0].url.startswith(BASE_URL)


def test_pionex_snapshot_balances_orders_and_fills() -> None:
    transport = FakePionexTransport(
        orders=[
            {
                "orderId": 9,
                "symbol": VENUE_SYMBOL,
                "side": "SELL",
                "type": "LIMIT",
                "size": "0.01",
                "price": "89550",
                "clientOrderId": "coid-entry-stop",
            }
        ],
        fills=[
            {
                "id": "7",
                "orderId": "1",
                "symbol": VENUE_SYMBOL,
                "side": "BUY",
                "size": "0.01",
                "price": "100000",
                "timestamp": 1_700_000_000_000,
            }
        ],
    )
    truth = _venue(transport).snapshot()
    assets = {b.asset: b for b in truth.balances}
    assert assets["USDT"].free == Decimal(1000)
    assert len(truth.open_orders) == 1
    assert truth.open_orders[0].stop_price == Decimal(89550)
    assert truth.recent_fills[0].side == "buy"
    for call in transport.calls:
        assert urlparse(call.url).hostname == API_HOST


def test_pionex_place_entry_buys_quote_amount_and_places_limit_stop() -> None:
    transport = FakePionexTransport()
    venue = _venue(transport)
    ref = venue.place_entry_with_stop("coid-entry", Decimal("0.01"), Decimal(90000), pair=WAVE_PAIR)
    assert ref.pair == WAVE_PAIR
    assert ref.side == "buy"
    assert ref.qty == Decimal("0.010000")
    assert ref.stop_price == Decimal("90000.00")
    posts = [c for c in transport.calls if c.method == "POST"]
    assert len(posts) == 2
    assert isinstance(posts[0].body, dict)
    assert posts[0].body["type"] == "MARKET"
    assert posts[0].body["side"] == "BUY"
    assert posts[0].body["symbol"] == VENUE_SYMBOL
    assert posts[0].body["IOC"] is True
    assert Decimal(posts[0].body["amount"]) == Decimal(1000)
    assert posts[0].body["clientOrderId"] == "coid-entry"
    assert posts[0].headers.get("PIONEX-KEY") == "PIONEX-SYNTHETIC-KEY"
    assert "timestamp=1541993715000" in posts[0].url
    assert posts[0].headers.get("PIONEX-SIGNATURE")
    assert isinstance(posts[1].body, dict)
    assert posts[1].body["type"] == "LIMIT"
    assert posts[1].body["side"] == "SELL"
    assert posts[1].body["symbol"] == VENUE_SYMBOL
    assert Decimal(posts[1].body["price"]) == Decimal("89550.00")
    assert posts[1].body["clientOrderId"] == "coid-entry-stop"
    posts_after = len(posts)
    second = venue.place_entry_with_stop("coid-entry", Decimal("0.01"), Decimal(90000), pair=WAVE_PAIR)
    assert second.id == ref.id
    assert len([c for c in transport.calls if c.method == "POST"]) == posts_after


def test_pionex_place_exit_cancel_stops_and_raise_stop() -> None:
    transport = FakePionexTransport(
        orders=[
            {
                "orderId": 9,
                "symbol": VENUE_SYMBOL,
                "side": "SELL",
                "type": "LIMIT",
                "size": "0.01",
                "price": "89550",
                "clientOrderId": "exit-coid-stop",
            }
        ]
    )
    venue = _venue(transport)
    entry = venue.place_entry_with_stop("exit-coid", Decimal("0.01"), Decimal(90000), pair=WAVE_PAIR)
    found = venue.order_by_coid("exit-coid")
    assert found is not None
    assert found.id == entry.id
    exit_ref = venue.place_exit("exit-flat", Decimal("0.01"), pair=WAVE_PAIR)
    assert exit_ref.side == "sell"
    sells = [
        c.body
        for c in transport.calls
        if c.method == "POST"
        and isinstance(c.body, dict)
        and c.body.get("side") == "SELL"
        and c.body.get("type") == "MARKET"
    ]
    assert sells
    assert Decimal(sells[0]["size"]) == Decimal("0.01")
    venue.cancel_stops(WAVE_PAIR)
    venue.raise_stop(WAVE_PAIR, Decimal(91000))
    deletes = [c for c in transport.calls if c.method == "DELETE"]
    assert deletes
    assert deletes[0].body == {"orderId": "9", "symbol": VENUE_SYMBOL}
    raised = [
        c.body
        for c in transport.calls
        if c.method == "POST"
        and isinstance(c.body, dict)
        and c.body.get("type") == "LIMIT"
        and Decimal(str(c.body.get("price"))) == Decimal("90545.00")
    ]
    assert raised


def test_pionex_check_key_trade_only_and_withdraw_refused() -> None:
    ok = _venue(FakePionexTransport()).check_key()
    assert ok.can_trade is True
    assert ok.can_withdraw is False
    bad = FakePionexTransport(permissions=["spot", "withdrawal"])
    with pytest.raises(WithdrawCapableError):
        _venue(bad).check_key()


def test_pionex_place_entry_blocked_when_paper_only_release(monkeypatch) -> None:
    from krellbot import release_policy

    assert PAPER_ONLY_RELEASE is True
    monkeypatch.setattr(release_policy, "PAPER_ONLY_RELEASE", True)
    transport = FakePionexTransport()
    with pytest.raises(PaperOnlyReleaseError):
        PionexVenue(
            key_id="k",
            api_secret="s",
            transport=transport,
            now_fn=lambda: 1,
        ).place_entry_with_stop("x", Decimal("0.01"), Decimal(1), pair=WAVE_PAIR)
    assert transport.calls == []


def test_pionex_sign_matches_documented_prehash() -> None:
    """GET balances prehash: method, path, sorted query. The key id is not hashed."""
    signature = sign_pionex(
        "secret",
        "GET",
        "/api/v1/account/balances",
        "timestamp=1541993715000",
        "",
    )
    assert signature == "8f2d65375f46d5cf4588da205c371083d731a141a1a65fb031d66d63ee0d1f49"
