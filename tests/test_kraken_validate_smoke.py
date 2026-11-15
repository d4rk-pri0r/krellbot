"""Validate-only Kraken smoke refuses bodies that omit validate=true.

Uses a spy transport and never contacts the network. Credentials are fake.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from krellbot.venues.kraken import (
    ADD_ORDER,
    BASE_URL,
    PRIVATE_PATH,
    build_entry_with_stop_form,
)
from scripts.kraken_validate_smoke import (
    PAIR,
    ValidateOnlyTransport,
    build_btc_usd_validate_form,
    post_validate_only,
)

ADD_ORDER_URL = f"{BASE_URL}{PRIVATE_PATH}/{ADD_ORDER}"


class SpyTransport:
    """Records every POST; returns an empty success body."""

    def __init__(self) -> None:
        self.posts: list[dict] = []

    def post(self, url: str, form: dict[str, str], headers: dict[str, str]) -> dict:
        self.posts.append({"url": url, "form": dict(form), "headers": dict(headers)})
        return {"error": [], "result": {}}

    def get(self, url: str, headers: dict[str, str] | None = None) -> dict:
        del url, headers
        return {"error": [], "result": {}}


def test_post_validate_only_refuses_body_without_validate() -> None:
    """Spy sees no POST when the body lacks validate=true."""
    spy = SpyTransport()
    body = build_entry_with_stop_form(
        "coid-smoke",
        Decimal("0.0001"),
        Decimal(90000),
        pair=PAIR,
        lot_decimals=8,
        price_decimals=1,
    )
    assert "validate" not in body
    with pytest.raises(ValueError, match="validate=true"):
        post_validate_only(spy, ADD_ORDER_URL, body, {})
    assert spy.posts == []


def test_validate_only_transport_refuses_add_order_without_validate() -> None:
    """Transport proxy refuses AddOrder bodies missing validate=true."""
    spy = SpyTransport()
    guarded = ValidateOnlyTransport(spy)
    body = {"pair": PAIR, "ordertype": "market", "type": "buy", "volume": "0.0001"}
    with pytest.raises(ValueError, match="validate=true"):
        guarded.post(ADD_ORDER_URL, body, {})
    assert spy.posts == []
    assert guarded.refused == [body]


def test_post_validate_only_forwards_when_validate_true() -> None:
    """With validate=true the spy records exactly one AddOrder POST."""
    spy = SpyTransport()
    body = build_btc_usd_validate_form(
        qty=Decimal("0.0001"),
        stop=Decimal(90000),
        lot_decimals=8,
        price_decimals=1,
    )
    assert body["validate"] == "true"
    assert body["pair"] == PAIR
    assert body["close[ordertype]"] == "stop-loss"
    result = post_validate_only(spy, ADD_ORDER_URL, body, {"API-Key": "fake"})
    assert result == {"error": [], "result": {}}
    assert len(spy.posts) == 1
    assert spy.posts[0]["form"]["validate"] == "true"
    assert spy.posts[0]["url"] == ADD_ORDER_URL
