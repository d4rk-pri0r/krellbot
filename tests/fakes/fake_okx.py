"""Fake OKX spot transport for tests.

Records every GET / POST. Never opens a network socket. Default
instruments cover the wave pair ``BTC-USDT``.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

_DEFAULT_INSTRUMENTS = {
    "code": "0",
    "data": [
        {
            "instType": "SPOT",
            "instId": "BTC-USDT",
            "baseCcy": "BTC",
            "quoteCcy": "USDT",
            "lotSz": "0.00000001",
            "minSz": "0.00001",
            "tickSz": "0.1",
            "state": "live",
        }
    ],
}

_DEFAULT_BALANCE = {
    "code": "0",
    "data": [
        {
            "details": [
                {"ccy": "USDT", "availBal": "1000", "frozenBal": "0"},
                {"ccy": "BTC", "availBal": "0", "frozenBal": "0"},
            ]
        }
    ],
}

_DEFAULT_CONFIG = {"code": "0", "data": [{"perm": "read_only,trade"}]}


@dataclass
class RecordedCall:
    """One HTTP call the venue made through the transport."""

    method: str
    url: str
    headers: dict[str, str]
    body: dict | list | None = None


class FakeOkxTransport:
    """Returns canned OKX spot payloads; records every call."""

    def __init__(
        self,
        *,
        instruments: dict | None = None,
        balance: dict | None = None,
        orders: list | None = None,
        algos: list | None = None,
        fills: list | None = None,
        config: dict | None = None,
    ) -> None:
        self._instruments = instruments if instruments is not None else dict(_DEFAULT_INSTRUMENTS)
        self._balance = balance if balance is not None else dict(_DEFAULT_BALANCE)
        self._orders = list(orders) if orders is not None else []
        self._algos = list(algos) if algos is not None else []
        self._fills = list(fills) if fills is not None else []
        self._config = config if config is not None else dict(_DEFAULT_CONFIG)
        self.calls: list[RecordedCall] = []

    def get(self, url: str, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="GET", url=url, headers=dict(headers)))
        path = urlparse(url).path
        if path.endswith("/api/v5/public/instruments"):
            return dict(self._instruments)
        if path.endswith("/api/v5/account/balance"):
            return dict(self._balance)
        if path.endswith("/api/v5/account/config"):
            return dict(self._config)
        if path.endswith("/api/v5/trade/orders-pending"):
            return {"code": "0", "data": list(self._orders)}
        if path.endswith("/api/v5/trade/orders-algo-pending"):
            return {"code": "0", "data": list(self._algos)}
        if path.endswith("/api/v5/trade/fills"):
            return {"code": "0", "data": list(self._fills)}
        return {"code": "0", "data": []}

    def post(self, url: str, body: dict | list | None, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="POST", url=url, headers=dict(headers), body=body))
        path = urlparse(url).path
        if path.endswith("/api/v5/trade/order-algo"):
            return {"code": "0", "data": [{"algoId": "algo-1", "sCode": "0"}]}
        if path.endswith("/api/v5/trade/cancel-algos"):
            return {"code": "0", "data": [{"sCode": "0"}]}
        if path.endswith("/api/v5/trade/order"):
            return {"code": "0", "data": [{"ordId": "ord-1", "sCode": "0"}]}
        return {"code": "0", "data": [{"sCode": "0"}]}
