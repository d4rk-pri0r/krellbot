"""KuCoin spot adapter: Venue protocol behind injectable fakes.

CI must never open a network socket to KuCoin. ``KucoinVenue`` requires an
explicit ``Transport``; ``None`` refuses rather than defaulting to
``HttpTransport``. Order mutations still go through
``release_policy.ensure_live_orders_allowed``.
"""

from __future__ import annotations

import re
from decimal import Decimal
from urllib.parse import urlparse

import pytest
from fakes.fake_kucoin import FakeKucoinTransport

from krellbot.release_policy import PAPER_ONLY_RELEASE, PaperOnlyReleaseError
from krellbot.venues.base import WithdrawCapableError
from krellbot.venues.kucoin import (
    API_HOST,
    BASE_URL,
    HttpTransport,
    KucoinVenue,
    canonical_json,
    sign_kucoin,
    sign_kucoin_broker_tag,
)

pytestmark = pytest.mark.usefixtures("live_capable_release")

WAVE_PAIR = "BTC-USDT"
_PACK_PAIR = re.compile(r"^[A-Z0-9]{2,16}(-[A-Z0-9]{2,16})?$")
_SECRET = "KUCOIN-SYNTHETIC-SECRET"
_KEY = "KUCOIN-SYNTHETIC-KEY"
_TAG = "KUCOIN-SYNTHETIC-TAG"


def _venue(transport: FakeKucoinTransport, **kwargs) -> KucoinVenue:
    return KucoinVenue(
        key_id=_KEY,
        api_secret=_SECRET,
        sign_tag=_TAG,
        transport=transport,
        now_fn=lambda: 1_541_993_715_000,
        **kwargs,
    )


def test_kucoin_wave_pair_matches_pack_pattern() -> None:
    """The paper wave pair is the hyphenated pack form, not a second venue id."""
    assert _PACK_PAIR.fullmatch(WAVE_PAIR)
    assert WAVE_PAIR == "BTC-USDT"


def test_kucoin_venue_refuses_none_transport() -> None:
    """No silent HttpTransport default — tests must inject a fake."""
    with pytest.raises(ValueError, match="transport is required"):
        KucoinVenue(key_id="k", api_secret="s", sign_tag="p", transport=None)  # type: ignore[arg-type]


def test_kucoin_http_transport_is_not_used_by_adapter_default() -> None:
    """Constructor has no network default; HttpTransport is opt-in only."""
    transport = FakeKucoinTransport()
    venue = _venue(transport)
    assert not isinstance(venue._transport, HttpTransport)
    assert venue._transport is transport


def test_kucoin_rules_use_btc_usdt_symbol() -> None:
    transport = FakeKucoinTransport()
    rules = _venue(transport).rules(WAVE_PAIR)
    assert rules.ordermin == Decimal("0.00001")
    assert rules.costmin == Decimal("0.1")
    assert rules.lot_decimals == 8
    assert rules.price_decimals == 1
    gets = [c for c in transport.calls if c.method == "GET"]
    assert gets
    assert gets[0].url == f"{BASE_URL}/api/v2/symbols/BTC-USDT"
    assert urlparse(gets[0].url).hostname == API_HOST


def test_kucoin_snapshot_balances_orders_and_fills() -> None:
    transport = FakeKucoinTransport(
        stops=[
            {
                "id": "9",
                "symbol": WAVE_PAIR,
                "side": "sell",
                "size": "0.01",
                "stopPrice": "89550",
                "clientOid": "coid-entry-stop",
            }
        ],
        fills=[
            {
                "tradeId": "7",
                "orderId": "1",
                "symbol": WAVE_PAIR,
                "side": "buy",
                "size": "0.01",
                "price": "100000",
                "createdAt": 1_700_000_000_000,
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


def test_kucoin_place_entry_buys_quote_funds_and_places_stop() -> None:
    transport = FakeKucoinTransport()
    venue = _venue(transport)
    ref = venue.place_entry_with_stop("coid-entry", Decimal("0.01"), Decimal(90000), pair=WAVE_PAIR)
    assert ref.pair == WAVE_PAIR
    assert ref.side == "buy"
    assert ref.qty == Decimal("0.01")
    assert ref.stop_price == Decimal("90000.0")
    posts = [c for c in transport.calls if c.method == "POST"]
    assert len(posts) == 2
    assert isinstance(posts[0].body, dict)
    assert posts[0].body["type"] == "market"
    assert posts[0].body["side"] == "buy"
    assert posts[0].body["symbol"] == WAVE_PAIR
    assert Decimal(posts[0].body["funds"]) == Decimal(1000)
    assert "size" not in posts[0].body
    assert posts[0].body["clientOid"] == "coid-entry"
    assert posts[0].url.endswith("/api/v1/hf/orders")
    assert posts[0].headers.get("KC-API-KEY") == _KEY
    assert posts[0].headers.get("KC-API-KEY-VERSION") == "2"
    assert posts[0].headers.get("KC-API-TIMESTAMP") == "1541993715000"
    assert posts[0].headers.get("KC-API-SIGN") == sign_kucoin(
        _SECRET,
        "1541993715000",
        "POST",
        "/api/v1/hf/orders",
        canonical_json(posts[0].body),
    )
    assert posts[0].headers.get("KC-API-PASSPHRASE") == sign_kucoin_broker_tag(_SECRET, _TAG)
    assert isinstance(posts[1].body, dict)
    assert posts[1].url.endswith("/api/v1/stop-order")
    assert posts[1].body["type"] == "limit"
    assert posts[1].body["side"] == "sell"
    assert Decimal(posts[1].body["price"]) == Decimal("89550.0")
    assert Decimal(posts[1].body["stopPrice"]) == Decimal("90000.0")
    assert posts[1].body["clientOid"] == "coid-entry-stop"
    posts_after = len(posts)
    second = venue.place_entry_with_stop("coid-entry", Decimal("0.01"), Decimal(90000), pair=WAVE_PAIR)
    assert second.id == ref.id
    assert len([c for c in transport.calls if c.method == "POST"]) == posts_after


def test_kucoin_place_exit_cancel_stops_and_raise_stop() -> None:
    transport = FakeKucoinTransport(
        stops=[
            {
                "id": "9",
                "symbol": WAVE_PAIR,
                "side": "sell",
                "size": "0.01",
                "stopPrice": "89550",
                "clientOid": "exit-coid-stop",
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
        and c.body.get("side") == "sell"
        and c.body.get("type") == "market"
    ]
    assert sells
    assert Decimal(sells[0]["size"]) == Decimal("0.01")
    venue.cancel_stops(WAVE_PAIR)
    venue.raise_stop(WAVE_PAIR, Decimal(91000))
    deletes = [c for c in transport.calls if c.method == "DELETE"]
    assert deletes
    assert deletes[0].url.endswith("/api/v1/stop-order/9")
    raised = [
        c.body
        for c in transport.calls
        if c.method == "POST"
        and isinstance(c.body, dict)
        and c.body.get("type") == "limit"
        and Decimal(str(c.body.get("stopPrice"))) == Decimal("91000.0")
    ]
    assert raised
    assert Decimal(str(raised[0]["price"])) == Decimal("90545.0")


def test_kucoin_check_key_trade_only_and_withdraw_refused() -> None:
    ok = _venue(FakeKucoinTransport()).check_key()
    assert ok.can_trade is True
    assert ok.can_withdraw is False
    bad = FakeKucoinTransport(permission="General,Spot,Withdraw")
    with pytest.raises(WithdrawCapableError):
        _venue(bad).check_key()


def test_kucoin_place_entry_blocked_when_paper_only_release(monkeypatch) -> None:
    from krellbot import release_policy

    assert PAPER_ONLY_RELEASE is True
    monkeypatch.setattr(release_policy, "PAPER_ONLY_RELEASE", True)
    transport = FakeKucoinTransport()
    with pytest.raises(PaperOnlyReleaseError):
        KucoinVenue(
            key_id="k",
            api_secret="s",
            sign_tag="p",
            transport=transport,
            now_fn=lambda: 1,
        ).place_entry_with_stop("x", Decimal("0.01"), Decimal(1), pair=WAVE_PAIR)
    assert transport.calls == []


def test_kucoin_sign_matches_documented_prehash() -> None:
    """GET accounts prehash is timestamp + method + endpoint + body. The key id is not hashed."""
    signature = sign_kucoin(
        "KUCOIN-SYNTHETIC-SECRET",
        "1680885532722",
        "GET",
        "/api/v1/accounts",
        "",
    )
    assert signature == "IKdpH+REMjaVmtCUxlEWSzl9hmF6qVReC5j6+TXFEjQ="
    tag = sign_kucoin_broker_tag("KUCOIN-SYNTHETIC-SECRET", "KUCOIN-SYNTHETIC-TAG")
    assert tag == "cVpzIGADcCdKbvpdzsLaA8bwfZQl5eiAHIv8bHuL9ks="
