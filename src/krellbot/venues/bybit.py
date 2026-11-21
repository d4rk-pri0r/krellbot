"""Bybit spot venue adapter.

Docs:
- https://bybit-exchange.github.io/docs/v5/guide
- https://bybit-exchange.github.io/docs/v5/market/instrument
- https://bybit-exchange.github.io/docs/v5/order/create-order
- https://bybit-exchange.github.io/docs/v5/user/apikey-info

Auth: HMAC-SHA256 of ``timestamp + api_key + recv_window + queryOrBody``,
lowercase hex, sent as ``X-BAPI-SIGN``. Tests inject a fake ``Transport``
and a deterministic ``now_fn``. The constructor requires ``transport`` —
there is no silent ``HttpTransport`` default.

Canonical pack/paper wave pair spelling is ``BTCUSDT`` (Bybit ``symbol``;
see ``docs/pack-format.md``). Spot market orders set ``marketUnit=baseCoin``
so ``qty`` is base quantity. Sell stops are spot conditional orders
(``orderFilter=StopOrder``, ``triggerDirection=2``).

``bybiteu`` (``api.bybit.eu``) stays in this family and is not this adapter.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import urllib.parse
from collections.abc import Callable
from decimal import ROUND_DOWN, Decimal
from typing import Any, Protocol

from krellbot import release_policy, sanitize
from krellbot.venues.base import (
    Balance,
    Fill,
    KeyPerms,
    OpenOrder,
    OrderRef,
    PairRules,
    Truth,
    WithdrawCapableError,
)

API_HOST = "api.bybit.com"
BASE_URL = f"https://{API_HOST}"
RECV_WINDOW = "5000"
STOP_BUFFER = Decimal("0.005")  # limit = stop * (1 - 0.5%)


class Transport(Protocol):
    """Anything with get/post returning parsed JSON dicts."""

    def get(self, url: str, headers: dict[str, str]) -> dict: ...

    def post(self, url: str, body: dict | None, headers: dict[str, str]) -> dict: ...


class HttpTransport:
    """Real urllib transport. Tests must not call this directly.

    urllib and the TLS helper stay inside the methods, matching the Binance
    adapter, so importing this module does not open a network stack.
    """

    def get(self, url: str, headers: dict[str, str]) -> dict:
        import urllib.request

        from krellbot.tls import urlopen

        req = urllib.request.Request(url, headers=headers, method="GET")
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def post(self, url: str, body: dict | None, headers: dict[str, str]) -> dict:
        import urllib.request

        from krellbot.tls import urlopen

        data = None
        hdrs = dict(headers)
        if body is not None:
            data = canonical_json(body).encode("utf-8")
            hdrs = {**hdrs, "content-type": "application/json"}
        req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))


def canonical_json(body: dict) -> str:
    """Stable JSON for the Bybit signature and the POST body."""
    return json.dumps(body, separators=(",", ":"), sort_keys=True)


def sign_bybit(secret: str, timestamp: str, api_key: str, recv_window: str, payload: str) -> str:
    """Lowercase hex HMAC-SHA256 of the Bybit v5 prehash string."""
    prehash = f"{timestamp}{api_key}{recv_window}{payload}"
    key = secret.encode("utf-8")
    msg = prehash.encode("utf-8")
    # Bybit v5 requires this HMAC-SHA256. It signs the request; it is not a password hash.
    return hmac.new(key, msg, hashlib.sha256).hexdigest()  # lgtm[py/weak-sensitive-data-hashing]


def _quantize_qty(value: Decimal, decimals: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN)


def _quantize_price(value: Decimal, decimals: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN)


def _decimals(increment: str) -> int:
    exp = Decimal(increment).as_tuple().exponent
    if not isinstance(exp, int) or exp >= 0:
        return 0
    return -exp


def _optional_decimal(raw: Any) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except (ValueError, ArithmeticError, TypeError):
        return None


def _order_link_id(coid: str) -> str:
    cleaned = "".join(ch for ch in coid if ch.isalnum() or ch in "-_")
    if not cleaned:
        cleaned = "kb"
    return cleaned[:36]


def _default_now_ms() -> int:
    import time as _time

    return int(_time.time() * 1000)


class BybitVenue:
    """Bybit spot adapter for balances / open orders / place+cancel seams.

    ``transport`` is mandatory. Passing ``None`` raises immediately rather
    than falling through to ``HttpTransport``. Order mutations call
    ``release_policy.ensure_live_orders_allowed()`` first.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        transport: Transport,
        *,
        now_fn: Callable[[], int] | None = None,
    ) -> None:
        if transport is None:
            raise ValueError("bybit: transport is required; None must not silently call the network")
        sanitize.register_secret(api_key, api_secret)
        self._api_key = api_key
        self._api_secret = api_secret
        self._transport = transport
        self._now_fn = now_fn or _default_now_ms
        self._recent: dict[str, OrderRef] = {}
        self._prices: dict[str, Decimal] = {}

    def rules(self, pair: str) -> PairRules:
        if not pair:
            raise ValueError("bybit rules require a pair")
        payload = self._public_get("/v5/market/instruments-info", {"category": "spot", "symbol": pair})
        row = _instrument_row(payload, pair)
        lot = row.get("lotSizeFilter") if isinstance(row.get("lotSizeFilter"), dict) else {}
        price = row.get("priceFilter") if isinstance(row.get("priceFilter"), dict) else {}
        step = str(lot.get("basePrecision") or lot.get("qtyStep") or "1")
        tick = str(price.get("tickSize") or "1")
        min_qty = Decimal(str(lot.get("minOrderQty") or "0"))
        min_amt = _optional_decimal(lot.get("minOrderAmt")) or _optional_decimal(lot.get("minNotionalValue"))
        return PairRules(
            ordermin=min_qty,
            costmin=min_amt if min_amt is not None else Decimal(1),
            lot_decimals=_decimals(step),
            price_decimals=_decimals(tick),
        )

    def snapshot(self) -> Truth:
        balances = self._signed_get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        orders = self._signed_get("/v5/order/realtime", {"category": "spot", "orderFilter": "Order"})
        stops = self._signed_get("/v5/order/realtime", {"category": "spot", "orderFilter": "StopOrder"})
        fills = self._signed_get("/v5/execution/list", {"category": "spot", "limit": "50"})
        return Truth(
            balances=_parse_balances(balances),
            open_orders=[*_parse_orders(orders, stop=False), *_parse_orders(stops, stop=True)],
            recent_fills=_parse_fills(fills),
        )

    def place_entry_with_stop(self, coid: str, qty: Decimal, stop: Decimal, *, pair: str) -> OrderRef:
        release_policy.ensure_live_orders_allowed()
        if coid in self._recent:
            return self._recent[coid]
        if not pair:
            raise ValueError("bybit entry requires a pair")
        rules = self.rules(pair)
        lot = _quantize_qty(qty, rules.lot_decimals)
        price_stop = _quantize_price(stop, rules.price_decimals)
        _reject_size(lot, rules, self._reference_price(pair))
        limit_price = _quantize_price(price_stop * (Decimal(1) - STOP_BUFFER), rules.price_decimals)
        entry = self._signed_post(
            "/v5/order/create",
            {
                "category": "spot",
                "symbol": pair,
                "side": "Buy",
                "orderType": "Market",
                "qty": format(lot, "f"),
                "marketUnit": "baseCoin",
                "orderLinkId": _order_link_id(coid),
                "isLeverage": 0,
                "orderFilter": "Order",
            },
        )
        if not _accepted(entry):
            raise RuntimeError("bybit entry was not accepted; stop not placed")
        stop_resp = self._signed_post(
            "/v5/order/create",
            {
                "category": "spot",
                "symbol": pair,
                "side": "Sell",
                "orderType": "Limit",
                "qty": format(lot, "f"),
                "price": format(limit_price, "f"),
                "triggerPrice": format(price_stop, "f"),
                "triggerDirection": 2,
                "timeInForce": "GTC",
                "orderLinkId": _order_link_id(coid + "_stop"),
                "orderFilter": "StopOrder",
            },
        )
        if not _accepted(stop_resp):
            raise RuntimeError("bybit stop was not accepted")
        ref = OrderRef(
            id=_result_id(entry),
            coid=coid,
            pair=pair,
            side="buy",
            qty=lot,
            filled_qty=lot,
            stop_price=price_stop,
        )
        self._recent[coid] = ref
        return ref

    def place_exit(self, coid: str, qty: Decimal, *, pair: str) -> OrderRef:
        release_policy.ensure_live_orders_allowed()
        if not pair:
            raise ValueError("bybit exit requires a pair")
        rules = self.rules(pair)
        lot = _quantize_qty(qty, rules.lot_decimals)
        _reject_size(lot, rules, self._reference_price(pair))
        resp = self._signed_post(
            "/v5/order/create",
            {
                "category": "spot",
                "symbol": pair,
                "side": "Sell",
                "orderType": "Market",
                "qty": format(lot, "f"),
                "marketUnit": "baseCoin",
                "orderLinkId": _order_link_id(coid),
                "isLeverage": 0,
                "orderFilter": "Order",
            },
        )
        if not _accepted(resp):
            raise RuntimeError("bybit exit was not accepted")
        return OrderRef(
            id=_result_id(resp),
            coid=coid,
            pair=pair,
            side="sell",
            qty=lot,
            filled_qty=lot,
            stop_price=None,
        )

    def cancel_stops(self, pair: str) -> None:
        release_policy.ensure_live_orders_allowed()
        for order in self._stop_orders(pair):
            self._signed_post(
                "/v5/order/cancel",
                {
                    "category": "spot",
                    "symbol": pair,
                    "orderId": order.id,
                    "orderFilter": "StopOrder",
                },
            )

    def raise_stop(self, pair: str, new_stop: Decimal) -> None:
        release_policy.ensure_live_orders_allowed()
        rules = self.rules(pair)
        price = _quantize_price(new_stop, rules.price_decimals)
        limit_price = _quantize_price(price * (Decimal(1) - STOP_BUFFER), rules.price_decimals)
        for order in self._stop_orders(pair):
            self._signed_post(
                "/v5/order/cancel",
                {
                    "category": "spot",
                    "symbol": pair,
                    "orderId": order.id,
                    "orderFilter": "StopOrder",
                },
            )
            self._signed_post(
                "/v5/order/create",
                {
                    "category": "spot",
                    "symbol": pair,
                    "side": "Sell",
                    "orderType": "Limit",
                    "qty": format(order.qty, "f"),
                    "price": format(limit_price, "f"),
                    "triggerPrice": format(price, "f"),
                    "triggerDirection": 2,
                    "timeInForce": "GTC",
                    "orderLinkId": _order_link_id((order.coid or order.id) + "_raised"),
                    "orderFilter": "StopOrder",
                },
            )

    def order_by_coid(self, coid: str) -> OpenOrder | None:
        ref = self._recent.get(coid)
        if ref is None:
            return None
        return OpenOrder(
            id=ref.id,
            coid=ref.coid,
            pair=ref.pair,
            side=ref.side,
            qty=ref.qty,
            stop_price=ref.stop_price,
        )

    def check_key(self) -> KeyPerms:
        payload = self._signed_get("/v5/user/query-api")
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict) or str(payload.get("retCode")) not in {"0", "0.0"}:
            raise TypeError("bybit api key response missing")
        permissions = result.get("permissions") if isinstance(result.get("permissions"), dict) else {}
        tokens: set[str] = set()
        for values in permissions.values():
            if isinstance(values, list):
                tokens.update(str(item) for item in values)
        if "Withdraw" in tokens:
            raise WithdrawCapableError("bybit key can withdraw; trade-only keys refused")
        spot = permissions.get("Spot") if isinstance(permissions.get("Spot"), list) else []
        can_trade = result.get("readOnly") in (0, "0") and "SpotTrade" in {str(item) for item in spot}
        return KeyPerms(can_trade=can_trade, can_withdraw=False)

    def _reference_price(self, pair: str) -> Decimal | None:
        cached = self._prices.get(pair)
        if cached is not None:
            return cached
        payload = self._public_get("/v5/market/tickers", {"category": "spot", "symbol": pair})
        rows = _result_list(payload)
        if rows:
            last = _optional_decimal(rows[0].get("lastPrice"))
            if last is not None and last > 0:
                self._prices[pair] = last
                return last
        return None

    def _stop_orders(self, pair: str) -> list[OpenOrder]:
        payload = self._signed_get(
            "/v5/order/realtime",
            {"category": "spot", "symbol": pair, "orderFilter": "StopOrder"},
        )
        return [order for order in _parse_orders(payload, stop=True) if order.pair == pair]

    def _headers(self, timestamp: str, signature: str) -> dict[str, str]:
        return {
            "X-BAPI-API-KEY": self._api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
        }

    def _public_get(self, path: str, params: dict[str, str] | None = None) -> Any:
        request_path = _request_path(path, params)
        return self._transport.get(f"{BASE_URL}{request_path}", {})

    def _signed_get(self, path: str, params: dict[str, str] | None = None) -> Any:
        query = urllib.parse.urlencode(params) if params else ""
        request_path = f"{path}?{query}" if query else path
        timestamp = str(int(self._now_fn()))
        signature = sign_bybit(self._api_secret, timestamp, self._api_key, RECV_WINDOW, query)
        return self._transport.get(f"{BASE_URL}{request_path}", self._headers(timestamp, signature))

    def _signed_post(self, path: str, body: dict) -> Any:
        payload = canonical_json(body)
        timestamp = str(int(self._now_fn()))
        signature = sign_bybit(self._api_secret, timestamp, self._api_key, RECV_WINDOW, payload)
        return self._transport.post(f"{BASE_URL}{path}", body, self._headers(timestamp, signature))


def _request_path(path: str, params: dict[str, str] | None) -> str:
    if not params:
        return path
    return f"{path}?{urllib.parse.urlencode(params)}"


def _result_list(payload: Any) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    result = payload.get("result")
    if isinstance(result, dict):
        data = result.get("list")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    return []


def _instrument_row(payload: Any, pair: str) -> dict:
    if not isinstance(payload, dict):
        raise TypeError("bybit instruments body is not a JSON object")
    if str(payload.get("retCode") if payload.get("retCode") is not None else "0") not in {"0", "0.0"}:
        raise ValueError("bybit instruments request was refused")
    for item in _result_list(payload):
        if str(item.get("symbol") or "") == pair:
            return item
    raise ValueError(f"bybit instruments has no symbol {pair!r}")


def _reject_size(qty: Decimal, rules: PairRules, price: Decimal | None) -> None:
    if qty < rules.ordermin:
        raise ValueError("qty below ordermin")
    if price is None:
        raise ValueError("bybit order requires a reference price for the quote minimum")
    if qty * price < rules.costmin:
        raise ValueError("notional below costmin")


def _accepted(resp: Any) -> bool:
    return isinstance(resp, dict) and str(resp.get("retCode")) in {"0", "0.0"}


def _result_id(resp: Any) -> str:
    result = resp.get("result") if isinstance(resp, dict) else None
    if isinstance(result, dict):
        return str(result.get("orderId") or "")
    return ""


def _parse_balances(payload: Any) -> list[Balance]:
    out: list[Balance] = []
    for account in _result_list(payload):
        coins = account.get("coin")
        if not isinstance(coins, list):
            continue
        for raw in coins:
            if not isinstance(raw, dict):
                continue
            locked = _optional_decimal(raw.get("locked")) or Decimal(0)
            wallet = _optional_decimal(raw.get("walletBalance"))
            if wallet is None:
                continue
            free = wallet - locked
            if free == 0 and locked == 0:
                continue
            out.append(Balance(asset=str(raw.get("coin") or ""), free=free, locked=locked))
    return out


def _parse_orders(payload: Any, *, stop: bool) -> list[OpenOrder]:
    out: list[OpenOrder] = []
    for raw in _result_list(payload):
        qty = _optional_decimal(raw.get("qty"))
        if qty is None:
            continue
        trigger = _optional_decimal(raw.get("triggerPrice"))
        if stop and (trigger is None or trigger == 0):
            continue
        out.append(
            OpenOrder(
                id=str(raw.get("orderId") or ""),
                coid=str(raw.get("orderLinkId") or ""),
                pair=str(raw.get("symbol") or ""),
                side=str(raw.get("side") or "").lower(),
                qty=qty,
                stop_price=trigger if stop else None,
            )
        )
    return out


def _parse_fills(payload: Any) -> list[Fill]:
    out: list[Fill] = []
    for raw in _result_list(payload):
        qty = _optional_decimal(raw.get("execQty"))
        price = _optional_decimal(raw.get("execPrice"))
        if qty is None or price is None:
            continue
        out.append(
            Fill(
                id=str(raw.get("execId") or ""),
                coid=str(raw.get("orderLinkId") or raw.get("orderId") or ""),
                pair=str(raw.get("symbol") or ""),
                side=str(raw.get("side") or "").lower(),
                qty=qty,
                price=price,
                ts_ms=int(raw.get("execTime") or 0),
            )
        )
    return out
