"""Fake Binance spot transport for tests.

Records every GET / POST / DELETE. Never opens a network socket. Default
exchangeInfo covers the M14 wave pair ``BTCUSDT``.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

_DEFAULT_EXCHANGE_INFO = {
    "symbols": [
        {
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "baseAsset": "BTC",
            "quoteAsset": "USDT",
            "lastPrice": "100000",
            "filters": [
                {
                    "filterType": "LOT_SIZE",
                    "minQty": "0.00001",
                    "maxQty": "9000",
                    "stepSize": "0.00001",
                },
                {
                    "filterType": "PRICE_FILTER",
                    "minPrice": "0.01",
                    "maxPrice": "1000000",
                    "tickSize": "0.01",
                },
                {
                    "filterType": "NOTIONAL",
                    "minNotional": "5",
                },
            ],
        }
    ]
}

_DEFAULT_ACCOUNT = {
    "balances": [
        {"asset": "USDT", "free": "1000", "locked": "0"},
        {"asset": "BTC", "free": "0", "locked": "0"},
    ]
}

_DEFAULT_RESTRICTIONS = {
    "ipRestrict": False,
    "enableWithdrawals": False,
    "enableInternalTransfer": False,
    "enableReading": True,
    "enableSpotAndMarginTrading": True,
}


@dataclass
class RecordedCall:
    """One HTTP call the venue made through the transport."""

    method: str
    url: str
    headers: dict[str, str]
    body: dict | None = None


class FakeBinanceTransport:
    """Returns canned Binance spot payloads; records every call."""

    def __init__(
        self,
        *,
        exchange_info: dict | None = None,
        account: dict | None = None,
        open_orders: list | None = None,
        fills: list | None = None,
        api_restrictions: dict | None = None,
        post_responses: list[dict] | None = None,
        delete_responses: list[dict] | None = None,
        raise_on: set[str] | None = None,
    ) -> None:
        self._exchange_info = exchange_info if exchange_info is not None else dict(_DEFAULT_EXCHANGE_INFO)
        self._account = account if account is not None else dict(_DEFAULT_ACCOUNT)
        self._open_orders = list(open_orders) if open_orders is not None else []
        self._fills = list(fills) if fills is not None else []
        self._api_restrictions = dict(api_restrictions) if api_restrictions is not None else dict(_DEFAULT_RESTRICTIONS)
        self._post_responses = list(post_responses or [])
        self._delete_responses = list(delete_responses or [])
        self._raise_on = set(raise_on or ())
        self.calls: list[RecordedCall] = []

    def get(self, url: str, headers: dict[str, str]) -> dict | list:
        self.calls.append(RecordedCall(method="GET", url=url, headers=dict(headers)))
        self._maybe_raise(url)
        path = urlparse(url).path
        if path.endswith("/api/v3/exchangeInfo"):
            return dict(self._exchange_info)
        if path.endswith("/api/v3/account"):
            return dict(self._account)
        if path.endswith("/api/v3/openOrders"):
            return list(self._open_orders)
        if path.endswith("/api/v3/myTrades"):
            return list(self._fills)
        if path.endswith("/sapi/v1/account/apiRestrictions"):
            return dict(self._api_restrictions)
        return {}

    def post(self, url: str, body: dict | None, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="POST", url=url, headers=dict(headers), body=dict(body or {})))
        self._maybe_raise(url)
        if self._post_responses:
            return self._post_responses.pop(0)
        return {"orderId": 1, "status": "FILLED", "executedQty": body.get("quantity") if body else "0"}

    def delete(self, url: str, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="DELETE", url=url, headers=dict(headers)))
        self._maybe_raise(url)
        if self._delete_responses:
            return self._delete_responses.pop(0)
        query = parse_qs(urlparse(url).query)
        order_ids = query.get("orderId", ["0"])
        return {"orderId": int(order_ids[0]), "status": "CANCELED"}

    def _maybe_raise(self, url: str) -> None:
        for marker in self._raise_on:
            if marker in url:
                raise RuntimeError(f"fake binance unreachable on {marker}")
