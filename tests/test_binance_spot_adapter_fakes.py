"""Binance-class spot adapter: Venue protocol behind injectable fakes.

CI must never open a network socket to Binance. ``BinanceVenue`` requires an
explicit ``Transport``; ``None`` refuses rather than defaulting to
``HttpTransport``. Order mutations still go through
``release_policy.ensure_live_orders_allowed``.
"""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlparse

import pytest
from fakes.fake_binance import FakeBinanceTransport

from krellbot.release_policy import PaperOnlyReleaseError
from krellbot.venues.base import WithdrawCapableError
from krellbot.venues.binance import API_HOST, BASE_URL, BinanceVenue, HttpTransport, sign_query

pytestmark = pytest.mark.usefixtures("live_capable_release")

WAVE_PAIR = "BTCUSDT"


def _venue(transport: FakeBinanceTransport, **kwargs) -> BinanceVenue:
    return BinanceVenue(
        api_key="test-key",
        api_secret="test-secret",
        transport=transport,
        now_fn=lambda: 1_700_000_000_000,
        **kwargs,
    )


def test_binance_venue_refuses_none_transport() -> None:
    """No silent HttpTransport default — tests must inject a fake."""
    with pytest.raises(ValueError, match="transport is required"):
        BinanceVenue(api_key="k", api_secret="s", transport=None)  # type: ignore[arg-type]


def test_binance_http_transport_is_not_used_by_adapter_default() -> None:
    """Constructor has no network default; HttpTransport is opt-in only."""
    transport = FakeBinanceTransport()
    venue = _venue(transport)
    assert not isinstance(venue._transport, HttpTransport)
    assert venue._transport is transport


def test_binance_rules_btc_usdt_from_exchange_info() -> None:
    transport = FakeBinanceTransport()
    rules = _venue(transport).rules(WAVE_PAIR)
    assert rules.ordermin == Decimal("0.00001")
    assert rules.costmin == Decimal(5)
    assert rules.lot_decimals == 5
    assert rules.price_decimals == 2
    gets = [c for c in transport.calls if c.method == "GET"]
    assert gets
    assert "exchangeInfo" in gets[0].url
    assert WAVE_PAIR in gets[0].url


def test_binance_snapshot_balances_and_open_orders() -> None:
    transport = FakeBinanceTransport(
        open_orders=[
            {
                "orderId": 9,
                "clientOrderId": "stop-1",
                "symbol": WAVE_PAIR,
                "side": "SELL",
                "origQty": "0.01",
                "stopPrice": "90000",
                "status": "NEW",
            }
        ],
        fills=[
            {
                "id": 7,
                "orderId": 1,
                "symbol": WAVE_PAIR,
                "qty": "0.01",
                "price": "100000",
                "isBuyer": True,
                "time": 1_700_000_000_000,
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
        parsed = urlparse(call.url)
        assert parsed.scheme == "https"
        assert parsed.hostname == API_HOST
        assert call.url.startswith(BASE_URL)


def test_binance_place_entry_with_stop_uses_signed_posts() -> None:
    transport = FakeBinanceTransport(
        post_responses=[
            {"orderId": 11, "status": "FILLED", "executedQty": "0.01000"},
            {"orderId": 12, "status": "NEW"},
        ]
    )
    venue = _venue(transport)
    ref = venue.place_entry_with_stop(
        "coid-entry",
        Decimal("0.01"),
        Decimal(90000),
        pair=WAVE_PAIR,
    )
    assert ref.pair == WAVE_PAIR
    assert ref.filled_qty == Decimal("0.01000")
    assert ref.stop_price == Decimal("90000.00")
    posts = [c for c in transport.calls if c.method == "POST"]
    assert len(posts) == 2
    assert posts[0].body is not None
    assert posts[0].body["type"] == "MARKET"
    assert posts[0].body["newClientOrderId"] == "coid-entry"
    assert "signature" in posts[0].body
    assert posts[0].headers.get("X-MBX-APIKEY") == "test-key"
    assert posts[1].body is not None
    assert posts[1].body["type"] == "STOP_LOSS_LIMIT"
    assert posts[1].body["newClientOrderId"] == "coid-entry_stop"
    # Duplicate coid must not resend.
    posts_after = len([c for c in transport.calls if c.method == "POST"])
    second = venue.place_entry_with_stop(
        "coid-entry",
        Decimal("0.01"),
        Decimal(90000),
        pair=WAVE_PAIR,
    )
    assert second.id == ref.id
    assert len([c for c in transport.calls if c.method == "POST"]) == posts_after


def test_binance_place_exit_cancel_stops_raise_stop_and_order_by_coid() -> None:
    transport = FakeBinanceTransport(
        post_responses=[
            {"orderId": 31, "status": "FILLED", "executedQty": "0.01000"},
            {"orderId": 32, "status": "NEW"},
            {"orderId": 33, "status": "FILLED", "executedQty": "0.01000"},
            {"orderId": 34, "status": "NEW"},
        ],
        open_orders=[
            {
                "orderId": 32,
                "clientOrderId": "exit-coid_stop",
                "symbol": WAVE_PAIR,
                "side": "SELL",
                "origQty": "0.01",
                "stopPrice": "90000",
                "status": "NEW",
            }
        ],
    )
    venue = _venue(transport)
    entry = venue.place_entry_with_stop("exit-coid", Decimal("0.01"), Decimal(90000), pair=WAVE_PAIR)
    found = venue.order_by_coid("exit-coid")
    assert found is not None
    assert found.id == entry.id
    exit_ref = venue.place_exit("exit-flat", Decimal("0.01"), pair=WAVE_PAIR)
    assert exit_ref.side == "sell"
    venue.cancel_stops(WAVE_PAIR)
    deletes = [c for c in transport.calls if c.method == "DELETE"]
    assert deletes
    venue.raise_stop(WAVE_PAIR, Decimal(91000))
    posts = [c for c in transport.calls if c.method == "POST"]
    assert any(c.body and c.body.get("stopPrice") == "91000.00" for c in posts)


def test_binance_check_key_trade_only_and_withdraw_refused() -> None:
    ok = _venue(FakeBinanceTransport()).check_key()
    assert ok.can_trade is True
    assert ok.can_withdraw is False
    bad = FakeBinanceTransport(api_restrictions={"enableWithdrawals": True, "enableSpotAndMarginTrading": True})
    with pytest.raises(WithdrawCapableError):
        _venue(bad).check_key()


def test_binance_place_entry_blocked_when_paper_only_release(monkeypatch) -> None:
    from krellbot import release_policy

    monkeypatch.setattr(release_policy, "PAPER_ONLY_RELEASE", True)
    transport = FakeBinanceTransport()
    with pytest.raises(PaperOnlyReleaseError):
        BinanceVenue(
            api_key="k",
            api_secret="s",
            transport=transport,
            now_fn=lambda: 1,
        ).place_entry_with_stop("x", Decimal("0.01"), Decimal(1), pair=WAVE_PAIR)
    assert transport.calls == []


def test_binance_sign_query_is_hmac_sha256_hex() -> None:
    sig = sign_query("secret", "symbol=BTCUSDT&timestamp=1")
    assert len(sig) == 64
    assert all(c in "0123456789abcdef" for c in sig)
