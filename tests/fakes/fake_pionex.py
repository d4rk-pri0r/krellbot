"""Fake Pionex spot transport for tests.

Records every GET / POST / DELETE. Never opens a network socket. Default
symbol is the wave market ``BTC_USDT``.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

_DEFAULT_SYMBOL = {
    "symbol": "BTC_USDT",
    "type": "SPOT",
    "baseCurrency": "BTC",
    "quoteCurrency": "USDT",
    "basePrecision": 6,
    "quotePrecision": 2,
    "amountPrecision": 8,
    "minAmount": "10",
    "minTradeSize": "0.000001",
    "enable": True,
}

_DEFAULT_TICKER = [{"symbol": "BTC_USDT", "close": "100000"}]

_DEFAULT_BALANCES = [{"coin": "USDT", "free": "1000", "frozen": "0"}]


@dataclass
class RecordedCall:
    """One HTTP call the venue made through the transport."""

    method: str
    url: str
    headers: dict[str, str]
    body: dict | None = None


class FakePionexTransport:
    """Returns canned Pionex spot envelopes; records every call."""

    def __init__(
        self,
        *,
        symbol: dict | None = None,
        tickers: list | None = None,
        balances: list | None = None,
        orders: list | None = None,
        fills: list | None = None,
        permissions: list | None = None,
        symbols_refused: bool = False,
    ) -> None:
        self._symbol = symbol if symbol is not None else dict(_DEFAULT_SYMBOL)
        self._tickers = list(tickers) if tickers is not None else list(_DEFAULT_TICKER)
        self._balances = list(balances) if balances is not None else list(_DEFAULT_BALANCES)
        self._orders = list(orders) if orders is not None else []
        self._fills = list(fills) if fills is not None else []
        self._permissions = list(permissions) if permissions is not None else None
        self._symbols_refused = symbols_refused
        self.calls: list[RecordedCall] = []
        self._orders_placed = 0

    def get(self, url: str, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="GET", url=url, headers=dict(headers)))
        path = urlparse(url).path
        if path.endswith("/common/symbols"):
            if self._symbols_refused:
                return {"result": False, "code": "SYMBOL_NOT_FOUND", "message": "refused", "timestamp": 1}
            return {"result": True, "data": {"symbols": [dict(self._symbol)]}, "timestamp": 1}
        if path.endswith("/market/tickers"):
            return {"result": True, "data": {"tickers": list(self._tickers)}, "timestamp": 1}
        if path.endswith("/account/balances"):
            body: dict = {"result": True, "data": {"balances": list(self._balances)}, "timestamp": 1}
            if self._permissions is not None:
                body["permissions"] = list(self._permissions)
            return body
        if path.endswith("/trade/openOrders"):
            return {"result": True, "data": {"orders": list(self._orders)}, "timestamp": 1}
        if path.endswith("/trade/fills"):
            return {"result": True, "data": {"fills": list(self._fills)}, "timestamp": 1}
        return {"result": False, "code": "UNKNOWN", "message": path, "timestamp": 1}

    def post(self, url: str, body: dict | None, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="POST", url=url, headers=dict(headers), body=dict(body or {})))
        self._orders_placed += 1
        return {"result": True, "data": {"orderId": self._orders_placed}, "timestamp": 1}

    def delete(self, url: str, body: dict | None, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="DELETE", url=url, headers=dict(headers), body=dict(body or {})))
        return {"result": True, "timestamp": 1}
