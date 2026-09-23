"""Fake Kraken transport for tests.

Records every POST and GET. Private POST responses are queued. Public GETs
return AssetPairs and Ticker shapes. OpenOrders and ClosedOrders do not
consume the AddOrder queue.
"""

from __future__ import annotations

from dataclasses import dataclass

_DEFAULT_PAIR = {
    "ordermin": "0.0001",
    "costmin": "0.5",
    "lot_decimals": 8,
    "pair_decimals": 5,
}


@dataclass
class RecordedCall:
    """One POST the venue made through the transport."""

    url: str
    form: dict[str, str]
    headers: dict[str, str]


class FakeKrakenTransport:
    """Returns the next body in `responses` for each non-lookup POST.

    `rate_limit_first_n` makes that many AddOrder posts return
    `EAPI:Rate limit exceeded`. `open_orders` / `closed_orders` are returned
    whole for those endpoints.
    """

    def __init__(
        self,
        responses: list[dict] | None = None,
        *,
        withdraw_methods: list | dict | None = None,
        rate_limit_first_n: int = 0,
        permission_error_on: set[str] | None = None,
        asset_pairs: dict | None = None,
        ticker_last: str = "100000",
        open_orders: dict | None = None,
        closed_orders: dict | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._withdraw_methods = withdraw_methods
        self._rate_limit_first = rate_limit_first_n
        self._permission_error_on = permission_error_on or set()
        self._asset_pairs = asset_pairs
        self._ticker_last = ticker_last
        self._open_orders = open_orders
        self._closed_orders = closed_orders
        self.calls: list[RecordedCall] = []
        self.gets: list[str] = []

    def get(self, url: str, headers: dict[str, str] | None = None) -> dict:
        del headers
        self.gets.append(url)
        pair = _query_value(url, "pair") or "XBTUSD"
        if "AssetPairs" in url:
            row = dict(_DEFAULT_PAIR)
            if self._asset_pairs and pair in self._asset_pairs:
                row = dict(self._asset_pairs[pair])
            elif self._asset_pairs:
                row = dict(next(iter(self._asset_pairs.values())))
            return {"error": [], "result": {pair: row}}
        if "Ticker" in url:
            return {"error": [], "result": {pair: {"c": [self._ticker_last, "1"]}}}
        return {"error": [], "result": {}}

    def post(self, url: str, form: dict[str, str], headers: dict[str, str]) -> dict:
        self.calls.append(RecordedCall(url=url, form=dict(form), headers=dict(headers)))
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint in self._permission_error_on:
            return {"error": ["EAPI:Invalid key: Permission denied"]}
        if endpoint == "OpenOrders":
            return self._open_orders or {"error": [], "result": {"open": {}}}
        if endpoint == "ClosedOrders":
            return self._closed_orders or {"error": [], "result": {"closed": {}}}
        if endpoint == "AddOrder" and self._rate_limit_first > 0:
            self._rate_limit_first -= 1
            return {"error": ["EAPI:Rate limit exceeded"]}
        if endpoint == "WithdrawMethods":
            if self._withdraw_methods is None:
                return {"error": ["EAPI:Invalid key: Permission denied"]}
            if isinstance(self._withdraw_methods, list):
                return {"result": self._withdraw_methods}
            return self._withdraw_methods
        if not self._responses:
            return {"error": [], "result": {}}
        return self._responses.pop(0)


def _query_value(url: str, key: str) -> str:
    marker = f"{key}="
    if marker not in url:
        return ""
    return url.split(marker, 1)[1].split("&", 1)[0]
