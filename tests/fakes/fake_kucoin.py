"""Fake KuCoin spot transport for tests.

Records every GET / POST / DELETE. Never opens a network socket. Default
symbol is the wave market ``BTC-USDT``.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

_DEFAULT_SYMBOL = {
    "symbol": "BTC-USDT",
    "baseCurrency": "BTC",
    "quoteCurrency": "USDT",
    "baseMinSize": "0.00001",
    "quoteMinSize": "0.1",
    "baseIncrement": "0.00000001",
    "quoteIncrement": "0.000001",
    "priceIncrement": "0.1",
    "minFunds": "0.1",
    "enableTrading": True,
}

_DEFAULT_ACCOUNTS = [{"currency": "USDT", "available": "1000", "holds": "0", "type": "trade"}]


@dataclass
class RecordedCall:
    """One HTTP call the venue made through the transport."""

    method: str
    url: str
    headers: dict[str, str]
    body: dict | None = None


class FakeKucoinTransport:
    """Returns canned KuCoin spot envelopes; records every call."""

    def __init__(
        self,
        *,
        symbol: dict | None = None,
        price: str = "100000",
        accounts: list | None = None,
        orders: list | None = None,
        stops: list | None = None,
        fills: list | None = None,
        permission: str | None = "General,Spot",
        permissions: list | None = None,
        symbols_refused: bool = False,
    ) -> None:
        self._symbol = symbol if symbol is not None else dict(_DEFAULT_SYMBOL)
        self._price = price
        self._accounts = list(accounts) if accounts is not None else list(_DEFAULT_ACCOUNTS)
        self._orders = list(orders) if orders is not None else []
        self._stops = list(stops) if stops is not None else []
        self._fills = list(fills) if fills is not None else []
        self._permission = permission
        self._permissions = list(permissions) if permissions is not None else None
        self._symbols_refused = symbols_refused
        self.calls: list[RecordedCall] = []
        self._orders_placed = 0

    def get(self, url: str, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="GET", url=url, headers=dict(headers)))
        path = urlparse(url).path
        if path.startswith("/api/v2/symbols"):
            if self._symbols_refused:
                return {"code": "400100", "msg": "refused"}
            return {"code": "200000", "data": dict(self._symbol)}
        if path.endswith("/market/orderbook/level1"):
            return {"code": "200000", "data": {"symbol": "BTC-USDT", "price": self._price}}
        if path.endswith("/accounts"):
            return {"code": "200000", "data": list(self._accounts)}
        if path.endswith("/hf/orders/active"):
            return {"code": "200000", "data": list(self._orders)}
        if path.endswith("/hf/fills"):
            return {"code": "200000", "data": {"items": list(self._fills)}}
        if path == "/api/v1/stop-order":
            return {"code": "200000", "data": {"items": list(self._stops)}}
        if path.endswith("/user/api-key"):
            data: dict = {}
            if self._permission is not None:
                data["permission"] = self._permission
            if self._permissions is not None:
                data["permissions"] = list(self._permissions)
            return {"code": "200000", "data": data}
        return {"code": "400100", "msg": path}

    def post(self, url: str, body: dict | None, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="POST", url=url, headers=dict(headers), body=dict(body or {})))
        self._orders_placed += 1
        return {"code": "200000", "data": {"orderId": str(self._orders_placed)}}

    def delete(self, url: str, body: dict | None, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="DELETE", url=url, headers=dict(headers), body=dict(body or {})))
        return {"code": "200000", "data": {}}
