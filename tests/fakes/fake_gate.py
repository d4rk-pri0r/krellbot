"""Fake Gate spot transport for tests.

Records every GET / POST / DELETE. Never opens a network socket. Default
currency pair is the wave market ``BTC_USDT``.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

_DEFAULT_PAIR = {
    "id": "BTC_USDT",
    "base": "BTC",
    "quote": "USDT",
    "min_base_amount": "0.00001",
    "min_quote_amount": "1",
    "amount_precision": 6,
    "precision": 1,
    "trade_status": "tradable",
}

_DEFAULT_TICKER = [{"currency_pair": "BTC_USDT", "last": "100000"}]

_DEFAULT_ACCOUNTS = [
    {"currency": "USDT", "available": "1000", "locked": "0"},
    {"currency": "BTC", "available": "0", "locked": "0"},
]

_DEFAULT_DETAIL = {"user_id": 10001, "key": {"mode": 1}}


@dataclass
class RecordedCall:
    """One HTTP call the venue made through the transport."""

    method: str
    url: str
    headers: dict[str, str]
    body: dict | None = None


class FakeGateTransport:
    """Returns canned Gate spot payloads; records every call."""

    def __init__(
        self,
        *,
        pair: dict | None = None,
        ticker: list | None = None,
        accounts: list | None = None,
        orders: list | None = None,
        stops: list | None = None,
        fills: list | None = None,
        detail: dict | None = None,
    ) -> None:
        self._pair = pair if pair is not None else dict(_DEFAULT_PAIR)
        self._ticker = list(ticker) if ticker is not None else list(_DEFAULT_TICKER)
        self._accounts = list(accounts) if accounts is not None else list(_DEFAULT_ACCOUNTS)
        self._orders = list(orders) if orders is not None else []
        self._stops = list(stops) if stops is not None else []
        self._fills = list(fills) if fills is not None else []
        self._detail = detail if detail is not None else dict(_DEFAULT_DETAIL)
        self.calls: list[RecordedCall] = []
        self._posts = 0

    def get(self, url: str, headers: dict[str, str]) -> dict | list:
        self.calls.append(RecordedCall(method="GET", url=url, headers=dict(headers)))
        path = urlparse(url).path
        if "/spot/currency_pairs/" in path:
            return dict(self._pair)
        if path.endswith("/spot/tickers"):
            return list(self._ticker)
        if path.endswith("/spot/accounts"):
            return list(self._accounts)
        if path.endswith("/spot/open_orders"):
            return [{"currency_pair": "BTC_USDT", "total": len(self._orders), "orders": list(self._orders)}]
        if path.endswith("/spot/price_orders"):
            market = (parse_qs(urlparse(url).query).get("market") or [None])[0]
            rows = self._stops
            if market:
                rows = [row for row in rows if str(row.get("market") or "") == market]
            return list(rows)
        if path.endswith("/spot/my_trades"):
            return list(self._fills)
        if path.endswith("/account/detail"):
            return dict(self._detail)
        return {}

    def post(self, url: str, body: dict | None, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="POST", url=url, headers=dict(headers), body=body))
        self._posts += 1
        path = urlparse(url).path
        if path.endswith("/spot/price_orders"):
            return {"id": 9000 + self._posts}
        text = body.get("text") if isinstance(body, dict) else ""
        return {"id": f"ord-{self._posts}", "text": text, "currency_pair": "BTC_USDT"}

    def delete(self, url: str, headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(method="DELETE", url=url, headers=dict(headers)))
        order_id = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        return {"id": order_id}
