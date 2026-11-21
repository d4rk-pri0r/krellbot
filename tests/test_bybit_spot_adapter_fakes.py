"""Bybit spot adapter: Venue protocol behind injectable fakes.

CI must never open a network socket to Bybit. ``BybitVenue`` requires an
explicit ``Transport``; ``None`` refuses rather than defaulting to
``HttpTransport``. Order mutations still go through
``release_policy.ensure_live_orders_allowed``.
"""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlparse

import pytest
from fakes.fake_bybit import FakeBybitTransport

from krellbot.release_policy import PaperOnlyReleaseError
from krellbot.venues.base import WithdrawCapableError
from krellbot.venues.bybit import API_HOST, BASE_URL, BybitVenue, HttpTransport, sign_bybit

pytestmark = pytest.mark.usefixtures("live_capable_release")

WAVE_PAIR = "BTCUSDT"


def _venue(transport: FakeBybitTransport, **kwargs) -> BybitVenue:
    return BybitVenue(
        key_id="test-key",
        api_secret="test-secret",
        transport=transport,
        now_fn=lambda: 1_658_384_314_791,
        **kwargs,
    )


def test_bybit_venue_refuses_none_transport() -> None:
    """No silent HttpTransport default — tests must inject a fake."""
    with pytest.raises(ValueError, match="transport is required"):
        BybitVenue(key_id="k", api_secret="s", transport=None)  # type: ignore[arg-type]


def test_bybit_http_transport_is_not_used_by_adapter_default() -> None:
    """Constructor has no network default; HttpTransport is opt-in only."""
    transport = FakeBybitTransport()
    venue = _venue(transport)
    assert not isinstance(venue._transport, HttpTransport)
    assert venue._transport is transport


def test_bybit_rules_btc_usdt_from_public_instruments() -> None:
    transport = FakeBybitTransport()
    rules = _venue(transport).rules(WAVE_PAIR)
    assert rules.ordermin == Decimal("0.000011")
    assert rules.costmin == Decimal(5)
    assert rules.lot_decimals == 6
    assert rules.price_decimals == 1
    gets = [c for c in transport.calls if c.method == "GET"]
    assert gets
    assert "/v5/market/instruments-info" in gets[0].url
    assert "BTCUSDT" in gets[0].url
    assert "category=spot" in gets[0].url
    parsed = urlparse(gets[0].url)
    assert parsed.hostname == API_HOST
    assert gets[0].url.startswith(BASE_URL)


def test_bybit_snapshot_balances_orders_and_fills() -> None:
    transport = FakeBybitTransport(
        stops=[
            {
                "orderId": "stop-9",
                "orderLinkId": "stop-1",
                "symbol": WAVE_PAIR,
                "side": "Sell",
                "qty": "0.01",
                "triggerPrice": "90000",
            }
        ],
        fills=[
            {
                "execId": "7",
                "orderId": "1",
                "orderLinkId": "fill-1",
                "symbol": WAVE_PAIR,
                "side": "Buy",
                "execQty": "0.01",
                "execPrice": "100000",
                "execTime": "1700000000000",
            }
        ],
    )
    truth = _venue(transport).snapshot()
    assets = {b.asset: b for b in truth.balances}
    assert assets["USDT"].free == Decimal(1000)
    assert len(truth.open_orders) == 1
    assert truth.open_orders[0].stop_price == Decimal(90000)
    assert truth.recent_fills[0].side == "buy"
    for call in transport.calls:
        assert urlparse(call.url).hostname == API_HOST


def test_bybit_place_entry_with_stop_uses_signed_posts() -> None:
    transport = FakeBybitTransport()
    venue = _venue(transport)
    ref = venue.place_entry_with_stop("coid-entry", Decimal("0.01"), Decimal(90000), pair=WAVE_PAIR)
    assert ref.pair == WAVE_PAIR
    assert ref.side == "buy"
    assert ref.stop_price == Decimal("90000.0")
    posts = [c for c in transport.calls if c.method == "POST"]
    assert len(posts) == 2
    assert isinstance(posts[0].body, dict)
    assert posts[0].body["orderType"] == "Market"
    assert posts[0].body["marketUnit"] == "baseCoin"
    assert posts[0].body["qty"] == "0.010000"
    assert posts[0].body["orderLinkId"] == "coid-entry"
    assert posts[0].headers.get("X-BAPI-API-KEY") == "test-key"
    assert posts[0].headers.get("X-BAPI-SIGN")
    assert posts[0].headers.get("X-BAPI-RECV-WINDOW") == "5000"
    assert isinstance(posts[1].body, dict)
    assert posts[1].body["orderFilter"] == "StopOrder"
    assert posts[1].body["triggerDirection"] == 2
    assert posts[1].body["orderLinkId"] == "coid-entry_stop"
    posts_after = len(posts)
    second = venue.place_entry_with_stop("coid-entry", Decimal("0.01"), Decimal(90000), pair=WAVE_PAIR)
    assert second.id == ref.id
    assert len([c for c in transport.calls if c.method == "POST"]) == posts_after


def test_bybit_place_exit_cancel_stops_and_raise_stop() -> None:
    transport = FakeBybitTransport(
        stops=[
            {
                "orderId": "stop-9",
                "orderLinkId": "exit-coid_stop",
                "symbol": WAVE_PAIR,
                "side": "Sell",
                "qty": "0.01",
                "triggerPrice": "90000",
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
    venue.cancel_stops(WAVE_PAIR)
    venue.raise_stop(WAVE_PAIR, Decimal(91000))
    posts = [c for c in transport.calls if c.method == "POST" and isinstance(c.body, dict)]
    assert any(body.get("triggerPrice") == "91000.0" for body in (c.body for c in posts if isinstance(c.body, dict)))
    cancels = [c for c in transport.calls if c.method == "POST" and c.url.endswith("/v5/order/cancel")]
    assert cancels


def test_bybit_check_key_trade_only_and_withdraw_refused() -> None:
    ok = _venue(FakeBybitTransport()).check_key()
    assert ok.can_trade is True
    assert ok.can_withdraw is False
    bad = FakeBybitTransport(
        key_info={
            "retCode": 0,
            "result": {
                "readOnly": 0,
                "permissions": {"Spot": ["SpotTrade"], "Wallet": ["Withdraw"]},
            },
        }
    )
    with pytest.raises(WithdrawCapableError):
        _venue(bad).check_key()


def test_bybit_place_entry_blocked_when_paper_only_release(monkeypatch) -> None:
    from krellbot import release_policy

    monkeypatch.setattr(release_policy, "PAPER_ONLY_RELEASE", True)
    transport = FakeBybitTransport()
    with pytest.raises(PaperOnlyReleaseError):
        BybitVenue(
            key_id="k",
            api_secret="s",
            transport=transport,
            now_fn=lambda: 1,
        ).place_entry_with_stop("x", Decimal("0.01"), Decimal(1), pair=WAVE_PAIR)
    assert transport.calls == []


def test_bybit_sign_matches_documented_prehash() -> None:
    """HMAC of timestamp + api key + recv window + query, lowercase hex."""
    signature = sign_bybit(
        "secret",
        "1658384314791",
        "test-key",
        "5000",
        "category=spot&symbol=BTCUSDT",
    )
    assert signature == "f62b52faffc7989a776ef22417ea411575f8a864ad004347822b75e6856a61e2"
