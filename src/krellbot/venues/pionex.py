"""Pionex spot venue adapter.

Docs:
- https://www.pionex.com/docs/api-docs/trade-api/common
- https://www.pionex.com/docs/api-docs/trade-api/trade
- Public symbols: ``GET /api/v1/common/symbols``
- Spot taker: Pionex Help Center regular rate 0.05%

Auth: hex HMAC-SHA256 of ``METHOD + path + ? + sorted query`` and, for
POST and DELETE, the JSON body. The key id is a ``PIONEX-KEY`` header and
is not part of the prehash. Tests inject a fake ``Transport`` and a
deterministic ``now_fn``. The constructor requires ``transport``.

Canonical pack/paper wave pair is ``BTC-USDT``. The adapter maps that to
the Pionex symbol ``BTC_USDT``. Spot market buys send quote ``amount``
(base qty times the public close). Sell size stays in base. Pionex spot
REST has no trigger order, so a stop is a resting limit sell at
``stop * (1 - 0.5%)`` with a ``-stop`` client id.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
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

API_HOST = "api.pionex.com"
BASE_URL = f"https://{API_HOST}"
WAVE_SYMBOL = "BTC_USDT"
STOP_BUFFER = Decimal("0.005")
STOP_SUFFIX = "-stop"
_WITHDRAW_TOKENS = {"withdraw", "withdrawal"}


class Transport(Protocol):
    """Anything with get/post/delete returning parsed JSON."""

    def get(self, url: str, headers: dict[str, str]) -> Any: ...

    def post(self, url: str, body: dict | None, headers: dict[str, str]) -> Any: ...

    def delete(self, url: str, body: dict | None, headers: dict[str, str]) -> Any: ...


class HttpTransport:
    """Real urllib transport. Tests must not call this directly.

    urllib and the TLS helper stay inside the methods, matching the Binance
    adapter, so importing this module does not open a network stack.
    """

    def get(self, url: str, headers: dict[str, str]) -> Any:
        import urllib.request

        from krellbot.tls import urlopen

        req = urllib.request.Request(url, headers=headers, method="GET")
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def post(self, url: str, body: dict | None, headers: dict[str, str]) -> Any:
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

    def delete(self, url: str, body: dict | None, headers: dict[str, str]) -> Any:
        import urllib.request

        from krellbot.tls import urlopen

        data = None
        hdrs = dict(headers)
        if body is not None:
            data = canonical_json(body).encode("utf-8")
            hdrs = {**hdrs, "content-type": "application/json"}
        req = urllib.request.Request(url, data=data, headers=hdrs, method="DELETE")
        with urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}


def canonical_json(body: dict) -> str:
    """Stable JSON for the Pionex signature and the request body."""
    return json.dumps(body, separators=(",", ":"), sort_keys=True)


def sorted_query(params: dict[str, str]) -> str:
    """Alphabetical ``key=value`` pairs. Signature values are not URL-encoded."""
    return "&".join(f"{key}={params[key]}" for key in sorted(params))


def sign_pionex(secret: str, method: str, path: str, query: str, body: str) -> str:
    """Lowercase hex HMAC-SHA256 of the Pionex prehash string.

    The key id is not hashed. Pionex puts it only in ``PIONEX-KEY``.
    """
    path_url = f"{path}?{query}" if query else path
    message = f"{method.upper()}{path_url}"
    if method.upper() != "GET" and body:
        message += body
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def venue_symbol(pack_pair: str) -> str:
    """Map a pack pair (``BTC-USDT``) to a Pionex symbol (``BTC_USDT``)."""
    if "_" in pack_pair:
        return pack_pair
    return pack_pair.replace("-", "_")


def _quantize(value: Decimal, decimals: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN)


def _optional_decimal(raw: Any) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except (ValueError, ArithmeticError, TypeError):
        return None


def _client_id(coid: str, *, stop: bool = False) -> str:
    """Pionex client ids are alphanumeric or hyphen, at most 64 characters."""
    cleaned = "".join(ch for ch in coid if ch.isalnum() or ch == "-")
    if not cleaned:
        cleaned = "kb"
    suffix = STOP_SUFFIX if stop else ""
    keep = 64 - len(suffix)
    return cleaned[:keep] + suffix


def _default_now_ms() -> int:
    return int(time.time() * 1000)


class PionexVenue:
    """Pionex spot adapter for balances / open orders / place+cancel seams.

    ``transport`` is mandatory. Passing ``None`` raises immediately rather
    than falling through to ``HttpTransport``. Order mutations call
    ``release_policy.ensure_live_orders_allowed()`` first.
    """

    def __init__(
        self,
        key_id: str,
        api_secret: str,
        transport: Transport,
        *,
        now_fn: Callable[[], int] | None = None,
    ) -> None:
        if transport is None:
            raise ValueError("pionex: transport is required; None must not silently call the network")
        sanitize.register_secret(key_id, api_secret)
        self._key_id = key_id
        self._api_secret = api_secret
        self._transport = transport
        self._now_fn = now_fn or _default_now_ms
        self._recent: dict[str, OrderRef] = {}
        self._prices: dict[str, Decimal] = {}
        self._lot_decimals: dict[str, int] = {}
        self._price_decimals: dict[str, int] = {}
        self._amount_decimals: dict[str, int] = {}

    def rules(self, pair: str) -> PairRules:
        if not pair:
            raise ValueError("pionex rules require a pair")
        symbol = venue_symbol(pair)
        payload = self._public_get("/api/v1/common/symbols", {"symbols": symbol, "type": "SPOT"})
        row = _symbol_row(payload, symbol)
        lot_decimals = _decimal_places(str(row.get("minTradeSize") or "1"))
        price_decimals = int(row.get("quotePrecision") or 0)
        amount_decimals = int(row.get("amountPrecision") or 8)
        self._lot_decimals[pair] = lot_decimals
        self._price_decimals[pair] = price_decimals
        self._amount_decimals[pair] = amount_decimals
        min_qty = Decimal(str(row.get("minTradeSize") or "0"))
        min_quote = _optional_decimal(row.get("minAmount")) or Decimal(1)
        return PairRules(
            ordermin=min_qty,
            costmin=min_quote,
            lot_decimals=lot_decimals,
            price_decimals=price_decimals,
        )

    def snapshot(self) -> Truth:
        balances = self._signed_get("/api/v1/account/balances")
        orders: list[OpenOrder] = []
        fills: list[Fill] = []
        for symbol in self._snapshot_symbols():
            orders.extend(_parse_orders(self._signed_get("/api/v1/trade/openOrders", {"symbol": symbol})))
            fills.extend(_parse_fills(self._signed_get("/api/v1/trade/fills", {"symbol": symbol})))
        return Truth(
            balances=_parse_balances(balances),
            open_orders=orders,
            recent_fills=fills,
        )

    def place_entry_with_stop(self, coid: str, qty: Decimal, stop: Decimal, *, pair: str) -> OrderRef:
        release_policy.ensure_live_orders_allowed()
        if coid in self._recent:
            return self._recent[coid]
        if not pair:
            raise ValueError("pionex entry requires a pair")
        symbol = venue_symbol(pair)
        rules = self.rules(pair)
        lot = _quantize(qty, rules.lot_decimals)
        price_stop = _quantize(stop, rules.price_decimals)
        last = self._reference_price(pair)
        _reject_size(lot, rules, last)
        quote_amount = _quantize(lot * last, self._amount_decimals.get(pair, 8))
        limit_price = _quantize(price_stop * (Decimal(1) - STOP_BUFFER), rules.price_decimals)
        entry = self._signed_post(
            "/api/v1/trade/order",
            {
                "IOC": True,
                "amount": format(quote_amount, "f"),
                "clientOrderId": _client_id(coid),
                "side": "BUY",
                "symbol": symbol,
                "type": "MARKET",
            },
        )
        if not _accepted(entry):
            raise RuntimeError("pionex entry was not accepted; stop not placed")
        stop_resp = self._signed_post(
            "/api/v1/trade/order",
            {
                "clientOrderId": _client_id(coid, stop=True),
                "price": format(limit_price, "f"),
                "side": "SELL",
                "size": format(lot, "f"),
                "symbol": symbol,
                "type": "LIMIT",
            },
        )
        if not _accepted(stop_resp):
            raise RuntimeError("pionex stop was not accepted")
        ref = OrderRef(
            id=_order_id(entry),
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
            raise ValueError("pionex exit requires a pair")
        symbol = venue_symbol(pair)
        rules = self.rules(pair)
        lot = _quantize(qty, rules.lot_decimals)
        _reject_size(lot, rules, self._reference_price(pair))
        resp = self._signed_post(
            "/api/v1/trade/order",
            {
                "IOC": True,
                "clientOrderId": _client_id(coid),
                "side": "SELL",
                "size": format(lot, "f"),
                "symbol": symbol,
                "type": "MARKET",
            },
        )
        if not _accepted(resp):
            raise RuntimeError("pionex exit was not accepted")
        return OrderRef(
            id=_order_id(resp),
            coid=coid,
            pair=pair,
            side="sell",
            qty=lot,
            filled_qty=lot,
            stop_price=None,
        )

    def cancel_stops(self, pair: str) -> None:
        release_policy.ensure_live_orders_allowed()
        symbol = venue_symbol(pair)
        for order in self._stop_orders(symbol):
            self._signed_delete("/api/v1/trade/order", {"orderId": order.id, "symbol": symbol})

    def raise_stop(self, pair: str, new_stop: Decimal) -> None:
        release_policy.ensure_live_orders_allowed()
        symbol = venue_symbol(pair)
        rules = self.rules(pair)
        price = _quantize(new_stop, rules.price_decimals)
        limit_price = _quantize(price * (Decimal(1) - STOP_BUFFER), rules.price_decimals)
        for order in self._stop_orders(symbol):
            self._signed_delete("/api/v1/trade/order", {"orderId": order.id, "symbol": symbol})
            self._signed_post(
                "/api/v1/trade/order",
                {
                    "clientOrderId": _client_id((order.coid or order.id) + "-raised", stop=True),
                    "price": format(limit_price, "f"),
                    "side": "SELL",
                    "size": format(order.qty, "f"),
                    "symbol": symbol,
                    "type": "LIMIT",
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
        """Read ``GET /api/v1/account/balances``.

        That payload does not list key scopes. When a ``permissions`` array
        or object is present, ``withdraw`` / ``withdrawal`` is refused.
        """
        payload = self._signed_get("/api/v1/account/balances")
        if not isinstance(payload, dict) or payload.get("result") is False:
            raise TypeError("pionex balances response missing")
        tokens = _permission_tokens(payload)
        if tokens & _WITHDRAW_TOKENS:
            raise WithdrawCapableError("pionex key can withdraw; trade-only keys refused")
        return KeyPerms(can_trade=True, can_withdraw=False)

    def _reference_price(self, pair: str) -> Decimal:
        cached = self._prices.get(pair)
        if cached is not None:
            return cached
        symbol = venue_symbol(pair)
        payload = self._public_get("/api/v1/market/tickers", {"symbol": symbol, "type": "SPOT"})
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("tickers") if isinstance(data, dict) else None
        for raw in rows or []:
            if isinstance(raw, dict) and str(raw.get("symbol") or "") == symbol:
                last = _optional_decimal(raw.get("close"))
                if last is not None and last > 0:
                    self._prices[pair] = last
                    return last
        raise ValueError("pionex order requires a reference price")

    def _snapshot_symbols(self) -> list[str]:
        symbols = {venue_symbol(pair) for pair in self._lot_decimals}
        symbols.add(WAVE_SYMBOL)
        return sorted(symbols)

    def _stop_orders(self, symbol: str) -> list[OpenOrder]:
        payload = self._signed_get("/api/v1/trade/openOrders", {"symbol": symbol})
        return [order for order in _parse_orders(payload) if order.pair == symbol and _is_stop(order)]

    def _headers(self, signature: str) -> dict[str, str]:
        return {"PIONEX-KEY": self._key_id, "PIONEX-SIGNATURE": signature}

    def _timestamp(self) -> str:
        return str(int(self._now_fn()))

    def _public_get(self, path: str, params: dict[str, str] | None = None) -> Any:
        query = sorted_query(params) if params else ""
        url = f"{BASE_URL}{path}?{query}" if query else f"{BASE_URL}{path}"
        return self._transport.get(url, {})

    def _signed_get(self, path: str, params: dict[str, str] | None = None) -> Any:
        query_params = dict(params or {})
        query_params["timestamp"] = self._timestamp()
        query = sorted_query(query_params)
        signature = sign_pionex(self._api_secret, "GET", path, query, "")
        return self._transport.get(f"{BASE_URL}{path}?{query}", self._headers(signature))

    def _signed_post(self, path: str, body: dict) -> Any:
        payload = canonical_json(body)
        query = sorted_query({"timestamp": self._timestamp()})
        signature = sign_pionex(self._api_secret, "POST", path, query, payload)
        return self._transport.post(
            f"{BASE_URL}{path}?{query}",
            body,
            {**self._headers(signature), "content-type": "application/json"},
        )

    def _signed_delete(self, path: str, body: dict) -> Any:
        payload = canonical_json(body)
        query = sorted_query({"timestamp": self._timestamp()})
        signature = sign_pionex(self._api_secret, "DELETE", path, query, payload)
        resp = self._transport.delete(
            f"{BASE_URL}{path}?{query}",
            body,
            {**self._headers(signature), "content-type": "application/json"},
        )
        if isinstance(resp, dict) and resp.get("result") is False:
            raise RuntimeError("pionex cancel was not accepted")
        return resp


def _decimal_places(raw: str) -> int:
    try:
        number = Decimal(raw)
    except (ValueError, ArithmeticError):
        return 0
    exponent = number.normalize().as_tuple().exponent
    if isinstance(exponent, int) and exponent < 0:
        return -exponent
    return 0


def _symbol_row(payload: Any, symbol: str) -> dict:
    if not isinstance(payload, dict):
        raise TypeError("pionex symbols body is not a JSON object")
    if payload.get("result") is False or payload.get("code"):
        raise ValueError("pionex symbols request was refused")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    rows = data.get("symbols") if isinstance(data, dict) else None
    for raw in rows or []:
        if (
            isinstance(raw, dict)
            and str(raw.get("symbol") or "") == symbol
            and str(raw.get("type") or "SPOT") == "SPOT"
        ):
            return raw
    raise ValueError(f"pionex symbols have no spot symbol {symbol!r}")


def _reject_size(qty: Decimal, rules: PairRules, price: Decimal) -> None:
    if qty < rules.ordermin:
        raise ValueError("qty below ordermin")
    if qty * price < rules.costmin:
        raise ValueError("notional below costmin")


def _accepted(resp: Any) -> bool:
    if not isinstance(resp, dict) or resp.get("result") is False or resp.get("code"):
        return False
    data = resp.get("data")
    return isinstance(data, dict) and data.get("orderId") not in (None, "")


def _order_id(resp: Any) -> str:
    if isinstance(resp, dict) and isinstance(resp.get("data"), dict):
        return str(resp["data"].get("orderId") or "")
    return ""


def _permission_tokens(payload: dict) -> set[str]:
    raw = payload.get("permissions")
    data = payload.get("data")
    if raw is None and isinstance(data, dict):
        raw = data.get("permissions")
    tokens: set[str] = set()
    if isinstance(raw, list):
        tokens.update(str(item).lower() for item in raw)
    elif isinstance(raw, dict):
        for value in raw.values():
            if isinstance(value, list):
                tokens.update(str(item).lower() for item in value)
            elif isinstance(value, str):
                tokens.add(value.lower())
    return tokens


def _rows(payload: Any, key: str) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    source = data if isinstance(data, dict) else payload
    rows = source.get(key) if isinstance(source, dict) else None
    if isinstance(rows, list):
        return [item for item in rows if isinstance(item, dict)]
    return []


def _parse_balances(payload: Any) -> list[Balance]:
    out: list[Balance] = []
    for raw in _rows(payload, "balances"):
        free = _optional_decimal(raw.get("free"))
        locked = _optional_decimal(raw.get("frozen")) or Decimal(0)
        if free is None or (free == 0 and locked == 0):
            continue
        out.append(Balance(asset=str(raw.get("coin") or ""), free=free, locked=locked))
    return out


def _is_stop(order: OpenOrder) -> bool:
    return order.side == "sell" and order.coid.endswith(STOP_SUFFIX)


def _parse_orders(payload: Any) -> list[OpenOrder]:
    out: list[OpenOrder] = []
    for raw in _rows(payload, "orders"):
        qty = _optional_decimal(raw.get("size"))
        if qty is None:
            continue
        coid = str(raw.get("clientOrderId") or "")
        stop = _optional_decimal(raw.get("price")) if coid.endswith(STOP_SUFFIX) else None
        out.append(
            OpenOrder(
                id=str(raw.get("orderId") or ""),
                coid=coid,
                pair=str(raw.get("symbol") or ""),
                side=str(raw.get("side") or "").lower(),
                qty=qty,
                stop_price=stop,
            )
        )
    return out


def _parse_fills(payload: Any) -> list[Fill]:
    out: list[Fill] = []
    for raw in _rows(payload, "fills"):
        qty = _optional_decimal(raw.get("size"))
        price = _optional_decimal(raw.get("price"))
        if qty is None or price is None:
            continue
        out.append(
            Fill(
                id=str(raw.get("id") or ""),
                coid=str(raw.get("orderId") or ""),
                pair=str(raw.get("symbol") or ""),
                side=str(raw.get("side") or "").lower(),
                qty=qty,
                price=price,
                ts_ms=int(raw.get("timestamp") or 0),
            )
        )
        return out
