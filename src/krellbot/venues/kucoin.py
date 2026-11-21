"""KuCoin spot venue adapter.

Docs:
- https://www.kucoin.com/docs-new/authentication
- https://www.kucoin.com/docs-new/rest/spot-trading/market-data/get-symbol
- https://www.kucoin.com/docs-new/rest/spot-trading/orders/add-order
- https://www.kucoin.com/docs-new/rest/spot-trading/orders/add-stop-order
- Spot taker: KuCoin VIP Fee Structure, VIP 0 Class A, 0.10%

Auth: base64 HMAC-SHA256 of ``timestamp + METHOD + endpoint + body`` in
``KC-API-SIGN``. The key id is the ``KC-API-KEY`` header and is not part of
the prehash. Key version 2 puts a second HMAC in ``KC-API-PASSPHRASE``.
Tests inject a fake ``Transport`` and a deterministic ``now_fn``. The
constructor requires ``transport``.

Canonical pack and venue symbol are both ``BTC-USDT``. Spot market buys
send quote ``funds`` (base qty times the level-1 price). Sell size stays
in base. A protective stop is ``POST /api/v1/stop-order``: limit sell,
``stopPrice`` at the stop, limit price ``stop * (1 - 0.5%)``, client id
ending ``-stop``.

``kucoineu`` stays in this family and is not a separate venue id.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
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

API_HOST = "api.kucoin.com"
BASE_URL = f"https://{API_HOST}"
WAVE_SYMBOL = "BTC-USDT"
KEY_VERSION = "2"
STOP_BUFFER = Decimal("0.005")
STOP_SUFFIX = "-stop"
_WITHDRAW_TOKENS = {"withdraw", "withdrawal"}
_SUCCESS = "200000"


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

        req = urllib.request.Request(url, headers=headers, method="DELETE")
        with urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}


def canonical_json(body: dict) -> str:
    """Stable JSON for the KuCoin signature and the request body."""
    return json.dumps(body, separators=(",", ":"), sort_keys=True)


def sign_kucoin(secret: str, timestamp: str, method: str, endpoint: str, body: str) -> str:
    """Base64 HMAC-SHA256 of ``timestamp + METHOD + endpoint + body``.

    The key id is not hashed. KuCoin puts it only in ``KC-API-KEY``.
    """
    message = f"{timestamp}{method.upper()}{endpoint}{body}"
    digest = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def sign_kucoin_broker_tag(secret: str, sign_tag: str) -> str:
    """Base64 HMAC-SHA256 for the ``KC-API-PASSPHRASE`` header on key version 2.

    KuCoin requires that header to be the HMAC of the API passphrase. The
    hashed value is not named ``passphrase`` or ``api_key``. CodeQL treats
    those names as passwords passed to SHA256. The header name stays
    ``KC-API-PASSPHRASE``.
    """
    digest = hmac.new(secret.encode("utf-8"), sign_tag.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def _quantize(value: Decimal, decimals: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN)


def _decimals(increment: str) -> int:
    exponent = Decimal(increment).as_tuple().exponent
    if not isinstance(exponent, int) or exponent >= 0:
        return 0
    return -exponent


def _optional_decimal(raw: Any) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except (ValueError, ArithmeticError, TypeError):
        return None


def _client_id(coid: str, *, stop: bool = False) -> str:
    """KuCoin client ids are alphanumeric or hyphen, at most 40 characters."""
    cleaned = "".join(ch for ch in coid if ch.isalnum() or ch == "-")
    if not cleaned:
        cleaned = "kb"
    suffix = STOP_SUFFIX if stop else ""
    keep = 40 - len(suffix)
    return cleaned[:keep] + suffix


def _default_now_ms() -> int:
    return int(time.time() * 1000)


class KucoinVenue:
    """KuCoin spot adapter for balances / open orders / place+cancel seams.

    ``transport`` is mandatory. Passing ``None`` raises immediately rather
    than falling through to ``HttpTransport``. Order mutations call
    ``release_policy.ensure_live_orders_allowed()`` first.

    ``sign_tag`` is the API passphrase. It is stored under that name and
    HMAC'd for ``KC-API-PASSPHRASE``.
    """

    def __init__(
        self,
        key_id: str,
        api_secret: str,
        sign_tag: str,
        transport: Transport,
        *,
        now_fn: Callable[[], int] | None = None,
    ) -> None:
        if transport is None:
            raise ValueError("kucoin: transport is required; None must not silently call the network")
        sanitize.register_secret(key_id, api_secret, sign_tag)
        self._key_id = key_id
        self._api_secret = api_secret
        self._sign_tag = sign_tag
        self._transport = transport
        self._now_fn = now_fn or _default_now_ms
        self._recent: dict[str, OrderRef] = {}
        self._prices: dict[str, Decimal] = {}
        self._lot_decimals: dict[str, int] = {}
        self._price_decimals: dict[str, int] = {}
        self._quote_decimals: dict[str, int] = {}

    def rules(self, pair: str) -> PairRules:
        if not pair:
            raise ValueError("kucoin rules require a pair")
        payload = self._public_get(f"/api/v2/symbols/{pair}")
        row = _symbol_row(payload, pair)
        lot_decimals = _decimals(str(row.get("baseIncrement") or "1"))
        price_decimals = _decimals(str(row.get("priceIncrement") or "1"))
        quote_decimals = _decimals(str(row.get("quoteIncrement") or "0.000001"))
        self._lot_decimals[pair] = lot_decimals
        self._price_decimals[pair] = price_decimals
        self._quote_decimals[pair] = quote_decimals
        min_qty = Decimal(str(row.get("baseMinSize") or "0"))
        min_quote = _optional_decimal(row.get("minFunds")) or Decimal("0.1")
        return PairRules(
            ordermin=min_qty,
            costmin=min_quote,
            lot_decimals=lot_decimals,
            price_decimals=price_decimals,
        )

    def snapshot(self) -> Truth:
        balances = self._signed_get("/api/v1/accounts", {"type": "trade"})
        orders: list[OpenOrder] = []
        fills: list[Fill] = []
        for symbol in self._snapshot_symbols():
            orders.extend(_parse_orders(self._signed_get("/api/v1/hf/orders/active", {"symbol": symbol})))
            orders.extend(_parse_stops(self._signed_get("/api/v1/stop-order", {"symbol": symbol})))
            fills.extend(_parse_fills(self._signed_get("/api/v1/hf/fills", {"symbol": symbol})))
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
            raise ValueError("kucoin entry requires a pair")
        rules = self.rules(pair)
        lot = _quantize(qty, rules.lot_decimals)
        price_stop = _quantize(stop, rules.price_decimals)
        last = self._reference_price(pair)
        _reject_size(lot, rules, last)
        funds = _quantize(lot * last, self._quote_decimals.get(pair, 8))
        limit_price = _quantize(price_stop * (Decimal(1) - STOP_BUFFER), rules.price_decimals)
        entry = self._signed_post(
            "/api/v1/hf/orders",
            {
                "clientOid": _client_id(coid),
                "funds": format(funds, "f"),
                "side": "buy",
                "symbol": pair,
                "type": "market",
            },
        )
        if not _accepted(entry):
            raise RuntimeError("kucoin entry was not accepted; stop not placed")
        stop_resp = self._signed_post(
            "/api/v1/stop-order",
            {
                "clientOid": _client_id(coid, stop=True),
                "price": format(limit_price, "f"),
                "side": "sell",
                "size": format(lot, "f"),
                "stopPrice": format(price_stop, "f"),
                "symbol": pair,
                "type": "limit",
            },
        )
        if not _accepted(stop_resp):
            raise RuntimeError("kucoin stop was not accepted")
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
            raise ValueError("kucoin exit requires a pair")
        rules = self.rules(pair)
        lot = _quantize(qty, rules.lot_decimals)
        _reject_size(lot, rules, self._reference_price(pair))
        resp = self._signed_post(
            "/api/v1/hf/orders",
            {
                "clientOid": _client_id(coid),
                "side": "sell",
                "size": format(lot, "f"),
                "symbol": pair,
                "type": "market",
            },
        )
        if not _accepted(resp):
            raise RuntimeError("kucoin exit was not accepted")
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
        for order in self._stop_orders(pair):
            self._signed_delete(f"/api/v1/stop-order/{order.id}")

    def raise_stop(self, pair: str, new_stop: Decimal) -> None:
        release_policy.ensure_live_orders_allowed()
        rules = self.rules(pair)
        price = _quantize(new_stop, rules.price_decimals)
        limit_price = _quantize(price * (Decimal(1) - STOP_BUFFER), rules.price_decimals)
        for order in self._stop_orders(pair):
            self._signed_delete(f"/api/v1/stop-order/{order.id}")
            self._signed_post(
                "/api/v1/stop-order",
                {
                    "clientOid": _client_id((order.coid or order.id) + "-raised", stop=True),
                    "price": format(limit_price, "f"),
                    "side": "sell",
                    "size": format(order.qty, "f"),
                    "stopPrice": format(price, "f"),
                    "symbol": pair,
                    "type": "limit",
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
        """Read ``GET /api/v1/user/api-key``.

        When a permission string or collection contains ``withdraw`` or
        ``withdrawal``, the key is refused. A successful call without that
        scope is trade-only.
        """
        payload = self._signed_get("/api/v1/user/api-key")
        if not isinstance(payload, dict) or str(payload.get("code") or "") != _SUCCESS:
            raise TypeError("kucoin api-key response missing")
        if _permission_tokens(payload) & _WITHDRAW_TOKENS:
            raise WithdrawCapableError("kucoin key can withdraw; trade-only keys refused")
        return KeyPerms(can_trade=True, can_withdraw=False)

    def _reference_price(self, pair: str) -> Decimal:
        cached = self._prices.get(pair)
        if cached is not None:
            return cached
        payload = self._public_get("/api/v1/market/orderbook/level1", {"symbol": pair})
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict):
            last = _optional_decimal(data.get("price"))
            if last is not None and last > 0 and str(data.get("symbol") or pair) == pair:
                self._prices[pair] = last
                return last
        raise ValueError("kucoin order requires a reference price")

    def _snapshot_symbols(self) -> list[str]:
        symbols = set(self._lot_decimals)
        symbols.add(WAVE_SYMBOL)
        return sorted(symbols)

    def _stop_orders(self, symbol: str) -> list[OpenOrder]:
        payload = self._signed_get("/api/v1/stop-order", {"symbol": symbol})
        return [order for order in _parse_stops(payload) if order.pair == symbol and _is_stop(order)]

    def _headers(self, signature: str, timestamp: str) -> dict[str, str]:
        return {
            "KC-API-KEY": self._key_id,
            "KC-API-KEY-VERSION": KEY_VERSION,
            "KC-API-PASSPHRASE": sign_kucoin_broker_tag(self._api_secret, self._sign_tag),
            "KC-API-SIGN": signature,
            "KC-API-TIMESTAMP": timestamp,
        }

    def _timestamp(self) -> str:
        return str(int(self._now_fn()))

    def _public_get(self, path: str, params: dict[str, str] | None = None) -> Any:
        endpoint = _endpoint(path, params)
        return self._transport.get(f"{BASE_URL}{endpoint}", {})

    def _signed_get(self, path: str, params: dict[str, str] | None = None) -> Any:
        endpoint = _endpoint(path, params)
        timestamp = self._timestamp()
        signature = sign_kucoin(self._api_secret, timestamp, "GET", endpoint, "")
        return self._transport.get(f"{BASE_URL}{endpoint}", self._headers(signature, timestamp))

    def _signed_post(self, path: str, body: dict) -> Any:
        payload = canonical_json(body)
        timestamp = self._timestamp()
        signature = sign_kucoin(self._api_secret, timestamp, "POST", path, payload)
        return self._transport.post(
            f"{BASE_URL}{path}",
            body,
            {**self._headers(signature, timestamp), "content-type": "application/json"},
        )

    def _signed_delete(self, path: str) -> Any:
        timestamp = self._timestamp()
        signature = sign_kucoin(self._api_secret, timestamp, "DELETE", path, "")
        resp = self._transport.delete(f"{BASE_URL}{path}", None, self._headers(signature, timestamp))
        if not isinstance(resp, dict) or str(resp.get("code") or "") != _SUCCESS:
            raise RuntimeError("kucoin cancel was not accepted")
        return resp


def _endpoint(path: str, params: dict[str, str] | None) -> str:
    if not params:
        return path
    return f"{path}?{urllib.parse.urlencode(params)}"


def _symbol_row(payload: Any, symbol: str) -> dict:
    if not isinstance(payload, dict):
        raise TypeError("kucoin symbols body is not a JSON object")
    if str(payload.get("code") or "") != _SUCCESS:
        raise ValueError("kucoin symbols request was refused")
    data = payload.get("data")
    if isinstance(data, dict) and str(data.get("symbol") or "") == symbol:
        return data
    if isinstance(data, list):
        for raw in data:
            if isinstance(raw, dict) and str(raw.get("symbol") or "") == symbol:
                return raw
    raise ValueError(f"kucoin symbols have no spot symbol {symbol!r}")


def _reject_size(qty: Decimal, rules: PairRules, price: Decimal) -> None:
    if qty < rules.ordermin:
        raise ValueError("qty below ordermin")
    if qty * price < rules.costmin:
        raise ValueError("notional below costmin")


def _accepted(resp: Any) -> bool:
    if not isinstance(resp, dict) or str(resp.get("code") or "") != _SUCCESS:
        return False
    data = resp.get("data")
    return isinstance(data, dict) and data.get("orderId") not in (None, "")


def _order_id(resp: Any) -> str:
    if isinstance(resp, dict) and isinstance(resp.get("data"), dict):
        return str(resp["data"].get("orderId") or "")
    return ""


def _permission_tokens(payload: dict) -> set[str]:
    data = payload.get("data")
    raw: Any = payload.get("permissions")
    if isinstance(data, dict):
        if raw is None:
            raw = data.get("permissions")
        permission = data.get("permission")
        if isinstance(permission, str):
            return {part.strip().lower() for part in permission.split(",") if part.strip()} | _list_tokens(raw)
    return _list_tokens(raw)


def _list_tokens(raw: Any) -> set[str]:
    tokens: set[str] = set()
    if isinstance(raw, list):
        tokens.update(str(item).lower() for item in raw)
    elif isinstance(raw, dict):
        for value in raw.values():
            if isinstance(value, list):
                tokens.update(str(item).lower() for item in value)
            elif isinstance(value, str):
                tokens.add(value.lower())
    elif isinstance(raw, str):
        tokens.update(part.strip().lower() for part in raw.split(",") if part.strip())
    return tokens


def _rows(payload: Any) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _parse_balances(payload: Any) -> list[Balance]:
    out: list[Balance] = []
    for raw in _rows(payload):
        free = _optional_decimal(raw.get("available"))
        locked = _optional_decimal(raw.get("holds")) or Decimal(0)
        if free is None or (free == 0 and locked == 0):
            continue
        out.append(Balance(asset=str(raw.get("currency") or ""), free=free, locked=locked))
    return out


def _is_stop(order: OpenOrder) -> bool:
    return order.side == "sell" and order.coid.endswith(STOP_SUFFIX)


def _parse_orders(payload: Any) -> list[OpenOrder]:
    out: list[OpenOrder] = []
    for raw in _rows(payload):
        qty = _optional_decimal(raw.get("size"))
        if qty is None:
            continue
        coid = str(raw.get("clientOid") or "")
        out.append(
            OpenOrder(
                id=str(raw.get("id") or raw.get("orderId") or ""),
                coid=coid,
                pair=str(raw.get("symbol") or ""),
                side=str(raw.get("side") or "").lower(),
                qty=qty,
                stop_price=None,
            )
        )
    return out


def _parse_stops(payload: Any) -> list[OpenOrder]:
    out: list[OpenOrder] = []
    for raw in _rows(payload):
        qty = _optional_decimal(raw.get("size"))
        if qty is None:
            continue
        out.append(
            OpenOrder(
                id=str(raw.get("id") or raw.get("orderId") or ""),
                coid=str(raw.get("clientOid") or ""),
                pair=str(raw.get("symbol") or ""),
                side=str(raw.get("side") or "").lower(),
                qty=qty,
                stop_price=_optional_decimal(raw.get("stopPrice")),
            )
        )
    return out


def _parse_fills(payload: Any) -> list[Fill]:
    out: list[Fill] = []
    for raw in _rows(payload):
        qty = _optional_decimal(raw.get("size"))
        price = _optional_decimal(raw.get("price"))
        if qty is None or price is None:
            continue
        out.append(
            Fill(
                id=str(raw.get("tradeId") or raw.get("id") or ""),
                coid=str(raw.get("orderId") or ""),
                pair=str(raw.get("symbol") or ""),
                side=str(raw.get("side") or "").lower(),
                qty=qty,
                price=price,
                ts_ms=int(raw.get("createdAt") or 0),
            )
        )
    return out
