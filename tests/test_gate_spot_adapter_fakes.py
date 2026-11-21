"""Gate spot adapter: Venue protocol behind injectable fakes.

CI must never open a network socket to Gate. ``GateVenue`` requires an
explicit ``Transport``; ``None`` refuses rather than defaulting to
``HttpTransport``. Order mutations still go through
``release_policy.ensure_live_orders_allowed``.
"""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlparse

import pytest
from fakes.fake_gate import FakeGateTransport

from krellbot.release_policy import PaperOnlyReleaseError
from krellbot.venues.base import WithdrawCapableError
from krellbot.venues.gate import API_HOST, BASE_URL, GateVenue, HttpTransport, sign_gate

pytestmark = pytest.mark.usefixtures("live_capable_release")

WAVE_PAIR = "BTC-USDT"
VENUE_SYMBOL = "BTC_USDT"


def _venue(transport: FakeGateTransport, **kwargs) -> GateVenue:
    return GateVenue(
        api_key="test-key",
        api_secret="secret",
        transport=transport,
        now_fn=lambda: 1_541_993_715_000,
        **kwargs,
    )


def test_gate_venue_refuses_none_transport() -> None:
    """No silent HttpTransport default — tests must inject a fake."""
    with pytest.raises(ValueError, match="transport is required"):
        GateVenue(api_key="k", api_secret="s", transport=None)  # type: ignore[arg-type]


def test_gate_http_transport_is_not_used_by_adapter_default() -> None:
    """Constructor has no network default; HttpTransport is opt-in only."""
    transport = FakeGateTransport()
    venue = _venue(transport)
    assert not isinstance(venue._transport, HttpTransport)
    assert venue._transport is transport


def test_gate_rules_map_btc_usdt_pack_pair_to_currency_pair() -> None:
    transport = FakeGateTransport()
    rules = _venue(transport).rules(WAVE_PAIR)
    assert rules.ordermin == Decimal("0.00001")
    assert rules.costmin == Decimal(1)
    assert rules.lot_decimals == 6
    assert rules.price_decimals == 1
    gets = [c for c in transport.calls if c.method == "GET"]
    assert gets
    assert "/api/v4/spot/currency_pairs/BTC_USDT" in gets[0].url
    parsed = urlparse(gets[0].url)
    assert parsed.hostname == API_HOST
    assert gets[0].url.startswith(BASE_URL)


def test_gate_snapshot_balances_orders_and_fills() -> None:
    transport = FakeGateTransport(
        stops=[
            {
                "id": 9,
                "market": VENUE_SYMBOL,
                "trigger": {"price": "90000", "rule": "<="},
                "put": {"side": "sell", "amount": "0.01", "price": "89550", "text": "t-stop-1"},
            }
        ],
        fills=[
            {
                "id": "7",
                "order_id": "1",
                "currency_pair": VENUE_SYMBOL,
                "side": "buy",
                "amount": "0.01",
                "price": "100000",
                "create_time_ms": "1700000000000",
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


def test_gate_place_entry_buys_quote_amount_and_places_stop() -> None:
    transport = FakeGateTransport()
    venue = _venue(transport)
    ref = venue.place_entry_with_stop("coid-entry", Decimal("0.01"), Decimal(90000), pair=WAVE_PAIR)
    assert ref.pair == WAVE_PAIR
    assert ref.side == "buy"
    assert ref.qty == Decimal("0.010000")
    assert ref.stop_price == Decimal("90000.0")
    posts = [c for c in transport.calls if c.method == "POST"]
    assert len(posts) == 2
    assert isinstance(posts[0].body, dict)
    assert posts[0].body["type"] == "market"
    assert posts[0].body["side"] == "buy"
    assert posts[0].body["currency_pair"] == VENUE_SYMBOL
    assert Decimal(posts[0].body["amount"]) == Decimal(1000)
    assert posts[0].body["text"] == "t-coid-entry"
    assert posts[0].headers.get("KEY") == "test-key"
    assert posts[0].headers.get("Timestamp") == "1541993715"
    assert posts[0].headers.get("SIGN")
    assert isinstance(posts[1].body, dict)
    assert posts[1].body["market"] == VENUE_SYMBOL
    assert posts[1].body["trigger"]["rule"] == "<="
    assert posts[1].body["put"]["side"] == "sell"
    assert posts[1].body["put"]["text"] == "t-coid-entry_stop"
    posts_after = len(posts)
    second = venue.place_entry_with_stop("coid-entry", Decimal("0.01"), Decimal(90000), pair=WAVE_PAIR)
    assert second.id == ref.id
    assert len([c for c in transport.calls if c.method == "POST"]) == posts_after


def test_gate_place_exit_cancel_stops_and_raise_stop() -> None:
    transport = FakeGateTransport(
        stops=[
            {
                "id": 9,
                "market": VENUE_SYMBOL,
                "trigger": {"price": "90000", "rule": "<="},
                "put": {"side": "sell", "amount": "0.01", "text": "t-exit-coid_stop"},
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
        if c.method == "POST" and isinstance(c.body, dict) and c.body.get("side") == "sell"
    ]
    assert sells
    assert Decimal(sells[0]["amount"]) == Decimal("0.01")
    venue.cancel_stops(WAVE_PAIR)
    venue.raise_stop(WAVE_PAIR, Decimal(91000))
    deletes = [c for c in transport.calls if c.method == "DELETE" and "/spot/price_orders/" in c.url]
    assert deletes
    raised = [
        c.body
        for c in transport.calls
        if c.method == "POST"
        and isinstance(c.body, dict)
        and isinstance(c.body.get("trigger"), dict)
        and c.body["trigger"].get("price") == "91000.0"
    ]
    assert raised


def test_gate_check_key_trade_only_and_withdraw_refused() -> None:
    ok = _venue(FakeGateTransport()).check_key()
    assert ok.can_trade is True
    assert ok.can_withdraw is False
    bad = FakeGateTransport(detail={"user_id": 10001, "permissions": ["spot", "withdrawal"]})
    with pytest.raises(WithdrawCapableError):
        _venue(bad).check_key()


def test_gate_place_entry_blocked_when_paper_only_release(monkeypatch) -> None:
    from krellbot import release_policy

    monkeypatch.setattr(release_policy, "PAPER_ONLY_RELEASE", True)
    transport = FakeGateTransport()
    with pytest.raises(PaperOnlyReleaseError):
        GateVenue(
            api_key="k",
            api_secret="s",
            transport=transport,
            now_fn=lambda: 1,
        ).place_entry_with_stop("x", Decimal("0.01"), Decimal(1), pair=WAVE_PAIR)
    assert transport.calls == []


def test_gate_sign_matches_documented_prehash() -> None:
    """Official APIv4 example: GET futures orders, secret ``secret``."""
    signature = sign_gate(
        "secret",
        "GET",
        "/api/v4/futures/orders",
        "contract=BTC_USD&status=finished&limit=50",
        "",
        "1541993715",
    )
    assert signature == (
        "55f84ea195d6fe57ce62464daaa7c3c02fa9d1dde954e4c898289c9a2407a3d6"
        "fb3faf24deff16790d726b66ac9f74526668b13bd01029199cc4fcc522418b8a"
    )
