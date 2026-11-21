"""Gate spot venue adapter.

Docs:
- https://www.gate.com/docs/developers/apiv4/en/#authentication
- Gate API v4 ``POST /spot/orders`` (market buy ``amount`` is quote)
- Gate API v4 ``POST /spot/price_orders`` (trigger ``rule`` ``<=``)
- ``GET /spot/currency_pairs/{currency_pair}``

Auth: hex HMAC-SHA512 of
``METHOD\\n/api/v4/...\\nquery\\nsha512(body)\\ntimestamp``.
Headers are ``KEY``, ``Timestamp`` (unix seconds), and ``SIGN``.
Tests inject a fake ``Transport`` and a deterministic ``now_fn``.
The constructor requires ``transport``.

Canonical pack/paper wave pair is ``BTC-USDT``. The adapter maps that to
the Gate currency pair ``BTC_USDT``. Spot market buys send quote
``amount = base qty * last`` because Gate's market-buy ``amount`` is the
quote currency. Sell size stays in base. Stops are price-triggered limit
sells. ``gateio`` is the legacy tentacles name for this same id.
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

API_HOST = "api.gateio.ws"
PREFIX = "/api/v4"
BASE_URL = f"https://{API_HOST}"
STOP_BUFFER = Decimal("0.005")  # limit = stop * (1 - 0.5%)
# Gate requires an expiration, in seconds, on a price-triggered order.
TRIGGER_EXPIRATION_SEC = 2_592_000
QUOTE_AMOUNT_DECIMALS = 8
_WITHDRAW_TOKENS = {"withdraw", "withdrawal"}


class Transport(Protocol):
    """Anything with get/post/delete returning parsed JSON."""

    def get(self, url: str, headers: dict[str, str]) -> Any: ...

    def post(self, url: str, body: dict | None, headers: dict[str, str]) -> Any: ...

    def delete(self, url: str, headers: dict[str, str]) -> Any: ...


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

    def delete(self, url: str, headers: dict[str, str]) -> Any:
        import urllib.request

        from krellbot.tls import urlopen

        req = urllib.request.Request(url, headers=headers, method="DELETE")
        with urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}


def canonical_json(body: dict) -> str:
    """Stable JSON for the Gate signature and the POST body."""
    return json.dumps(body, separators=(",", ":"), sort_keys=True)


def sign_gate(secret: str, method: str, path: str, query: str, body: str, timestamp: str) -> str:
    """Hex HMAC-SHA512 of the Gate APIv4 prehash string."""
    hashed = hashlib.sha512((body or "").encode("utf-8")).hexdigest()
    prehash = f"{method.upper()}\n{path}\n{query}\n{hashed}\n{timestamp}"
    return hmac.new(secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha512).hexdigest()


def venue_symbol(pack_pair: str) -> str:
    """Map a pack pair (``BTC-USDT``) to a Gate currency pair (``BTC_USDT``)."""
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


def _client_text(coid: str) -> str:
    """Gate ``text`` must start with ``t-`` and stay within 28 bytes after it."""
    cleaned = "".join(ch for ch in coid if ch.isalnum() or ch in "_-.")
    if not cleaned:
        cleaned = "kb"
    return "t-" + cleaned[:28]


def _default_now_ms() -> int:
    import time as _time

    return int(_time.time() * 1000)


class GateVenue:
    """Gate spot adapter for balances / open orders / place+cancel seams.

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
            raise ValueError("gate: transport is required; None must not silently call the network")
        sanitize.register_secret(api_key, api_secret)
        self._api_key = api_key
        self._api_secret = api_secret
        self._transport = transport
        self._now_fn = now_fn or _default_now_ms
        self._recent: dict[str, OrderRef] = {}
        self._prices: dict[str, Decimal] = {}
        self._lot_decimals: dict[str, int] = {}

    def rules(self, pair: str) -> PairRules:
        if not pair:
            raise ValueError("gate rules require a pair")
        symbol = venue_symbol(pair)
        payload = self._public_get(f"/spot/currency_pairs/{urllib.parse.quote(symbol)}")
        row = _pair_row(payload, symbol)
        amount_decimals = int(row.get("amount_precision") or 0)
        price_decimals = int(row.get("precision") or 0)
        self._lot_decimals[pair] = amount_decimals
        min_qty = Decimal(str(row.get("min_base_amount") or "0"))
        min_quote = _optional_decimal(row.get("min_quote_amount")) or Decimal(1)
        return PairRules(
            ordermin=min_qty,
            costmin=min_quote,
            lot_decimals=amount_decimals,
            price_decimals=price_decimals,
        )

    def snapshot(self) -> Truth:
        balances = self._signed_get("/spot/accounts")
        orders = self._signed_get("/spot/open_orders")
        stops = self._signed_get("/spot/price_orders", {"status": "open"})
        fills = self._signed_get("/spot/my_trades", {"limit": "50"})
        return Truth(
            balances=_parse_balances(balances),
            open_orders=[*_parse_open_orders(orders), *_parse_price_orders(stops)],
            recent_fills=_parse_fills(fills),
        )

    def place_entry_with_stop(self, coid: str, qty: Decimal, stop: Decimal, *, pair: str) -> OrderRef:
        release_policy.ensure_live_orders_allowed()
        if coid in self._recent:
            return self._recent[coid]
        if not pair:
            raise ValueError("gate entry requires a pair")
        symbol = venue_symbol(pair)
        rules = self.rules(pair)
        lot = _quantize(qty, rules.lot_decimals)
        price_stop = _quantize(stop, rules.price_decimals)
        last = self._reference_price(pair)
        _reject_size(lot, rules, last)
        quote_amount = _quantize(lot * last, QUOTE_AMOUNT_DECIMALS)
        limit_price = _quantize(price_stop * (Decimal(1) - STOP_BUFFER), rules.price_decimals)
        entry = self._signed_post(
            "/spot/orders",
            {
                "account": "spot",
                "amount": format(quote_amount, "f"),
                "currency_pair": symbol,
                "side": "buy",
                "text": _client_text(coid),
                "time_in_force": "ioc",
                "type": "market",
            },
        )
        if not _accepted(entry):
            raise RuntimeError("gate entry was not accepted; stop not placed")
        stop_resp = self._signed_post(
            "/spot/price_orders",
            _stop_body(symbol, lot, price_stop, limit_price, _client_text(coid + "_stop")),
        )
        if not _accepted(stop_resp):
            raise RuntimeError("gate stop was not accepted")
        ref = OrderRef(
            id=_row_id(entry),
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
            raise ValueError("gate exit requires a pair")
        symbol = venue_symbol(pair)
        rules = self.rules(pair)
        lot = _quantize(qty, rules.lot_decimals)
        _reject_size(lot, rules, self._reference_price(pair))
        resp = self._signed_post(
            "/spot/orders",
            {
                "account": "spot",
                "amount": format(lot, "f"),
                "currency_pair": symbol,
                "side": "sell",
                "text": _client_text(coid),
                "time_in_force": "ioc",
                "type": "market",
            },
        )
        if not _accepted(resp):
            raise RuntimeError("gate exit was not accepted")
        return OrderRef(
            id=_row_id(resp),
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
            self._signed_delete(f"/spot/price_orders/{urllib.parse.quote(order.id)}")

    def raise_stop(self, pair: str, new_stop: Decimal) -> None:
        release_policy.ensure_live_orders_allowed()
        symbol = venue_symbol(pair)
        rules = self.rules(pair)
        price = _quantize(new_stop, rules.price_decimals)
        limit_price = _quantize(price * (Decimal(1) - STOP_BUFFER), rules.price_decimals)
        for order in self._stop_orders(pair):
            self._signed_delete(f"/spot/price_orders/{urllib.parse.quote(order.id)}")
            self._signed_post(
                "/spot/price_orders",
                _stop_body(symbol, order.qty, price, limit_price, _client_text((order.coid or order.id) + "_raised")),
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
        """Read ``GET /account/detail``.

        That payload does not list key scopes. When a ``permissions`` array
        or object is present, ``withdraw`` / ``withdrawal`` is refused.
        """
        payload = self._signed_get("/account/detail")
        if not isinstance(payload, dict) or payload.get("user_id") in (None, ""):
            raise TypeError("gate account detail response missing")
        if payload.get("label"):
            raise TypeError("gate account detail was refused")
        tokens = _permission_tokens(payload)
        if tokens & _WITHDRAW_TOKENS:
            raise WithdrawCapableError("gate key can withdraw; trade-only keys refused")
        can_trade = "spot" in tokens or not tokens
        return KeyPerms(can_trade=can_trade, can_withdraw=False)

    def _reference_price(self, pair: str) -> Decimal:
        cached = self._prices.get(pair)
        if cached is not None:
            return cached
        symbol = venue_symbol(pair)
        payload = self._public_get("/spot/tickers", {"currency_pair": symbol})
        rows = payload if isinstance(payload, list) else []
        for raw in rows:
            if isinstance(raw, dict) and str(raw.get("currency_pair") or "") in {symbol, pair}:
                last = _optional_decimal(raw.get("last"))
                if last is not None and last > 0:
                    self._prices[pair] = last
                    return last
        raise ValueError("gate order requires a reference price")

    def _stop_orders(self, pair: str) -> list[OpenOrder]:
        symbol = venue_symbol(pair)
        payload = self._signed_get("/spot/price_orders", {"status": "open", "market": symbol})
        return [order for order in _parse_price_orders(payload) if order.pair in {pair, symbol}]

    def _headers(self, timestamp: str, signature: str) -> dict[str, str]:
        return {
            "KEY": self._api_key,
            "SIGN": signature,
            "Timestamp": timestamp,
        }

    def _timestamp(self) -> str:
        return str(int(self._now_fn()) // 1000)

    def _public_get(self, path: str, params: dict[str, str] | None = None) -> Any:
        request_path = _request_path(f"{PREFIX}{path}", params)
        return self._transport.get(f"{BASE_URL}{request_path}", {})

    def _signed_get(self, path: str, params: dict[str, str] | None = None) -> Any:
        query = urllib.parse.urlencode(params) if params else ""
        full_path = f"{PREFIX}{path}"
        request_path = f"{full_path}?{query}" if query else full_path
        timestamp = self._timestamp()
        signature = sign_gate(self._api_secret, "GET", full_path, query, "", timestamp)
        return self._transport.get(f"{BASE_URL}{request_path}", self._headers(timestamp, signature))

    def _signed_post(self, path: str, body: dict) -> Any:
        full_path = f"{PREFIX}{path}"
        payload = canonical_json(body)
        timestamp = self._timestamp()
        signature = sign_gate(self._api_secret, "POST", full_path, "", payload, timestamp)
        return self._transport.post(f"{BASE_URL}{full_path}", body, self._headers(timestamp, signature))

    def _signed_delete(self, path: str) -> Any:
        full_path = f"{PREFIX}{path}"
        timestamp = self._timestamp()
        signature = sign_gate(self._api_secret, "DELETE", full_path, "", "", timestamp)
        resp = self._transport.delete(f"{BASE_URL}{full_path}", self._headers(timestamp, signature))
        if isinstance(resp, dict) and resp.get("label"):
            raise RuntimeError("gate cancel was not accepted")
        return resp


def _request_path(path: str, params: dict[str, str] | None) -> str:
    if not params:
        return path
    return f"{path}?{urllib.parse.urlencode(params)}"


def _stop_body(symbol: str, qty: Decimal, trigger: Decimal, limit: Decimal, text: str) -> dict:
    return {
        "market": symbol,
        "put": {
            "account": "normal",
            "amount": format(qty, "f"),
            "price": format(limit, "f"),
            "side": "sell",
            "text": text,
            "time_in_force": "gtc",
            "type": "limit",
        },
        "trigger": {
            "expiration": TRIGGER_EXPIRATION_SEC,
            "price": format(trigger, "f"),
            "rule": "<=",
        },
    }


def _pair_row(payload: Any, symbol: str) -> dict:
    if not isinstance(payload, dict):
        raise TypeError("gate currency pair body is not a JSON object")
    if payload.get("label"):
        raise ValueError("gate currency pair request was refused")
    if str(payload.get("id") or "") != symbol:
        raise ValueError(f"gate currency pair has no id {symbol!r}")
    return payload


def _reject_size(qty: Decimal, rules: PairRules, price: Decimal) -> None:
    if qty < rules.ordermin:
        raise ValueError("qty below ordermin")
    if qty * price < rules.costmin:
        raise ValueError("notional below costmin")


def _accepted(resp: Any) -> bool:
    return isinstance(resp, dict) and resp.get("label") in (None, "") and resp.get("id") not in (None, "")


def _row_id(resp: Any) -> str:
    if isinstance(resp, dict):
        return str(resp.get("id") or "")
    return ""


def _permission_tokens(payload: dict) -> set[str]:
    raw = payload.get("permissions")
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


def _as_dicts(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


def _parse_balances(payload: Any) -> list[Balance]:
    out: list[Balance] = []
    for raw in _as_dicts(payload):
        free = _optional_decimal(raw.get("available"))
        locked = _optional_decimal(raw.get("locked")) or Decimal(0)
        if free is None or (free == 0 and locked == 0):
            continue
        out.append(Balance(asset=str(raw.get("currency") or ""), free=free, locked=locked))
    return out


def _parse_open_orders(payload: Any) -> list[OpenOrder]:
    out: list[OpenOrder] = []
    groups = _as_dicts(payload)
    orders: list[dict] = []
    for group in groups:
        nested = group.get("orders")
        if isinstance(nested, list):
            orders.extend(item for item in nested if isinstance(item, dict))
        elif group.get("id") is not None and group.get("side"):
            orders.append(group)
    for raw in orders:
        qty = _optional_decimal(raw.get("amount"))
        if qty is None:
            continue
        out.append(
            OpenOrder(
                id=str(raw.get("id") or ""),
                coid=str(raw.get("text") or ""),
                pair=str(raw.get("currency_pair") or ""),
                side=str(raw.get("side") or "").lower(),
                qty=qty,
                stop_price=None,
            )
        )
    return out


def _parse_price_orders(payload: Any) -> list[OpenOrder]:
    out: list[OpenOrder] = []
    for raw in _as_dicts(payload):
        put = raw.get("put") if isinstance(raw.get("put"), dict) else {}
        trigger = raw.get("trigger") if isinstance(raw.get("trigger"), dict) else {}
        qty = _optional_decimal(put.get("amount"))
        stop = _optional_decimal(trigger.get("price"))
        if qty is None or stop is None or stop == 0:
            continue
        out.append(
            OpenOrder(
                id=str(raw.get("id") or ""),
                coid=str(put.get("text") or ""),
                pair=str(raw.get("market") or ""),
                side=str(put.get("side") or "").lower(),
                qty=qty,
                stop_price=stop,
            )
        )
    return out


def _parse_fills(payload: Any) -> list[Fill]:
    out: list[Fill] = []
    for raw in _as_dicts(payload):
        qty = _optional_decimal(raw.get("amount"))
        price = _optional_decimal(raw.get("price"))
        if qty is None or price is None:
            continue
        out.append(
            Fill(
                id=str(raw.get("id") or ""),
                coid=str(raw.get("order_id") or ""),
                pair=str(raw.get("currency_pair") or ""),
                side=str(raw.get("side") or "").lower(),
                qty=qty,
                price=price,
                ts_ms=int(raw.get("create_time_ms") or 0),
            )
        )
    return out
