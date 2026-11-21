"""Fake Bybit spot transport for tests.

Records every GET / POST. Never opens a network socket. Default
instruments cover the wave pair ``BTCUSDT``.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

_DEFAULT_INSTRUMENTS = {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
        "category": "spot",
        "list": [
            {
                "symbol": "BTCUSDT",
                "baseCoin": "BTC",
                "quoteCoin": "USDT",
                "status": "Trading",
                "lotSizeFilter": {
                    "basePrecision": "0.000001",
                    "minOrderQty": "0.000011",
                    "minOrderAmt": "5",
                },
                "priceFilter": {"tickSize": "0.1"},
            }
        ],
    },
}

_DEFAULT_TICKER = {
    "retCode": 0,
    "retMsg": "OK",
    "result": {"category": "spot", "list": [{"symbol": "BTCUSDT", "lastPrice": "100000"}]},
}

_DEFAULT_WALLET = {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
        "list": [
            {
                "accountType": "UNIFIED",
                "coin": [
                    {"coin": "USDT", "walletBalance": "1000", "locked": "0"},
                    {"coin": "BTC", "walletBalance": "0", "locked": "0"},
                ],
            }
        ]
    },
}

_DEFAULT_KEY = {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
        "readOnly": 0,
        "permissions": {"Spot": ["SpotTrade"], "Wallet": []},
    },
}


@dataclass
class RecordedCall:
    """One HTTP call the venue made through the transport."""

    method: str
    url: str
    headers: dict[str, str]
    body: dict | None = None


class FakeBybitTransport:
    """Returns canned Bybit spot payloads; records every call."""

    def __init__(
        self,
        *,
        instruments: dict | None = None,
        ticker: dict | None = None,
        wallet: dict | None = None,
        orders: list | None = None,
        stops: list | None = None,
        fills: list | None = None,
        key_info: dict | None = None,
    ) -> None:
        self._instruments = instruments if instruments is not None else dict(_DEFAULT_INSTRUMENTS)
        self._ticker = ticker if ticker is not None else dict(_DEFAULT_TICKER)
        self._wallet = wallet if wallet is not None else dict(_DEFAULT_WALLET)
        self._orders = list(orders) if orders is not None else []
        self._stops = list(stops) if stops is not None else []
        self._fills = list(fills) if fills is not None else []
        self._key_info = key_info if key_info is not None else dict(_DEFAULT_KEY)
        self.calls: list[RecordedCall] = []
        self._posts = 0

    def get(self, url: str, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="GET", url=url, headers=dict(headers)))
        path = urlparse(url).path
        query = parse_qs(urlparse(url).query)
        if path.endswith("/v5/market/instruments-info"):
            return dict(self._instruments)
        if path.endswith("/v5/market/tickers"):
            return dict(self._ticker)
        if path.endswith("/v5/account/wallet-balance"):
            return dict(self._wallet)
        if path.endswith("/v5/order/realtime"):
            order_filter = (query.get("orderFilter") or ["Order"])[0]
            rows = self._stops if order_filter == "StopOrder" else self._orders
            return {"retCode": 0, "retMsg": "OK", "result": {"list": list(rows)}}
        if path.endswith("/v5/execution/list"):
            return {"retCode": 0, "retMsg": "OK", "result": {"list": list(self._fills)}}
        if path.endswith("/v5/user/query-api"):
            return dict(self._key_info)
        return {"retCode": 0, "retMsg": "OK", "result": {}}

    def post(self, url: str, body: dict | None, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="POST", url=url, headers=dict(headers), body=body))
        self._posts += 1
        path = urlparse(url).path
        if path.endswith("/v5/order/cancel"):
            return {"retCode": 0, "retMsg": "OK", "result": {"orderId": "cancel-1"}}
        order_id = (
            "stop-1" if isinstance(body, dict) and body.get("orderFilter") == "StopOrder" else f"ord-{self._posts}"
        )
        link = body.get("orderLinkId") if isinstance(body, dict) else ""
        return {"retCode": 0, "retMsg": "OK", "result": {"orderId": order_id, "orderLinkId": link}}
