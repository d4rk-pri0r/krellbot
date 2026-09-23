"""Fake Coinbase transport for tests.

Records every GET and POST. `product` is the public product payload. `orders`
is the list-orders payload. `key_permissions` is what `check_key` sees.
"""

from __future__ import annotations

from dataclasses import dataclass

_DEFAULT_PRODUCT = {
    "product_id": "BTC-USD",
    "base_increment": "0.00000001",
    "quote_increment": "0.01",
    "base_min_size": "0.00000001",
    "quote_min_size": "1",
    "price": "100000",
}


@dataclass
class RecordedCall:
    """One HTTP call the venue made through the transport."""

    method: str
    url: str
    headers: dict[str, str]
    body: dict | None = None


class FakeCoinbaseTransport:
    """Returns the next response per method."""

    def __init__(
        self,
        post_responses: list[dict] | None = None,
        get_responses: list[dict] | None = None,
        *,
        key_permissions: dict | list | None = None,
        product: dict | None = None,
        orders: dict | None = None,
    ) -> None:
        self._post_responses = list(post_responses or [])
        self._get_responses = list(get_responses or [])
        self._key_permissions = key_permissions
        self._product = product
        self._orders = orders
        self.calls: list[RecordedCall] = []

    def post(self, url: str, body: dict, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="POST", url=url, headers=dict(headers), body=dict(body)))
        if not self._post_responses:
            return {"success": True}
        return self._post_responses.pop(0)

    def get(self, url: str, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="GET", url=url, headers=dict(headers)))
        if "key_permissions" in url:
            if self._key_permissions is None:
                return {"scopes": []}
            return self._key_permissions
        if "market/products" in url:
            return self._product or dict(_DEFAULT_PRODUCT)
        if "orders/historical/batch" in url:
            if self._orders is not None:
                return self._orders
            if self._get_responses:
                return self._get_responses.pop(0)
            return {"orders": [], "has_next": False}
        if not self._get_responses:
            return {}
        return self._get_responses.pop(0)
