"""OKX spot venue adapter.

Docs:
- https://www.okx.com/docs-v5/en/#public-data-rest-api-get-instruments
- https://www.okx.com/docs-v5/en/#order-book-trading-trade-post-place-order
- https://www.okx.com/docs-v5/en/#order-book-trading-trade-post-place-algo-order
- https://www.okx.com/docs-v5/en/#overview-rest-authentication

Auth: HMAC-SHA256 of ``timestamp + method + requestPath + body``, base64,
sent as ``OK-ACCESS-SIGN``. Tests inject a fake ``Transport`` and a
deterministic ``now_fn``. The constructor requires ``transport`` — there
is no silent ``HttpTransport`` default, so CI cannot accidentally hit
the network.

Canonical pack/paper wave pair spelling is ``BTC-USDT`` (OKX ``instId``;
see ``docs/pack-format.md``). Spot market buys send ``tgtCcy=base_ccy``
so ``sz`` is base quantity, matching the Venue protocol.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import urllib.parse
from collections.abc import Callable
from datetime import datetime, timezone
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

API_HOST = "www.okx.com"
BASE_URL = f"https://{API_HOST}"
STOP_BUFFER = Decimal("0.005")  # limit = stop * (1 - 0.5%)
# Public instruments omit a quote minimum. Paper uses 1 quote unit.
PAPER_MIN_NOTIONAL = Decimal(1)


class Transport(Protocol):
    """Anything with get/post returning parsed JSON dicts."""

    def get(self, url: str, headers: dict[str, str]) -> dict: ...

    def post(self, url: str, body: dict | list | None, headers: dict[str, str]) -> dict: ...


class HttpTransport:
    """Real urllib transport. Tests must not call this directly."""

    def get(self, url: str, headers: dict[str, str]) -> dict:
        import urllib.request

        from krellbot.tls import urlopen

        req = urllib.request.Request(url, headers=headers, method="GET")
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def post(self, url: str, body: dict | list | None, headers: dict[str, str]) -> dict:
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


def canonical_json(body: dict | list) -> str:
    """Stable JSON for the OKX signature and the POST body."""
    return json.dumps(body, separators=(",", ":"), sort_keys=True)


def sign_okx(secret: str, timestamp: str, method: str, request_path: str, body: str) -> str:
    """Base64 HMAC-SHA256 of the OKX v5 prehash string."""
    prehash = f"{timestamp}{method.upper()}{request_path}{body}"
    digest = hmac.new(secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


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


def _iso_millis(ms: int) -> str:
    seconds, millis = divmod(int(ms), 1000)
    base = datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{millis:03d}Z"


def _default_now_ms() -> int:
    import time as _time

    return int(_time.time() * 1000)


class OkxVenue:
    """OKX spot adapter for balances / open orders / place+cancel seams.

    ``transport`` is mandatory. Passing ``None`` raises immediately rather
    than falling through to ``HttpTransport``. Order mutations call
    ``release_policy.ensure_live_orders_allowed()`` first.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str,
        transport: Transport,
        *,
        now_fn: Callable[[], int] | None = None,
    ) -> None:
        if transport is None:
            raise ValueError("okx: transport is required; None must not silently call the network")
        sanitize.register_secret(api_key, api_secret, passphrase)
        self._api_key = api_key
        self._api_secret = api_secret
        self._passphrase = passphrase
        self._transport = transport
        self._now_fn = now_fn or _default_now_ms
        self._recent: dict[str, OrderRef] = {}
        self._prices: dict[str, Decimal] = {}

    def rules(self, pair: str) -> PairRules:
        if not pair:
            raise ValueError("okx rules require a pair")
        payload = self._public_get(
            "/api/v5/public/instruments",
            {"instType": "SPOT", "instId": pair},
        )
        row = _instrument_row(payload, pair)
        lot = str(row.get("lotSz") or "1")
        tick = str(row.get("tickSz") or "1")
        min_qty = Decimal(str(row.get("minSz") or "0"))
        last = _optional_decimal(row.get("last"))
        if last is not None:
            self._prices[pair] = last
        return PairRules(
            ordermin=min_qty,
            costmin=PAPER_MIN_NOTIONAL,
            lot_decimals=_decimals(lot),
            price_decimals=_decimals(tick),
        )

    def snapshot(self) -> Truth:
        balances = self._signed_get("/api/v5/account/balance")
        orders = self._signed_get("/api/v5/trade/orders-pending", {"instType": "SPOT"})
        algos = self._signed_get(
            "/api/v5/trade/orders-algo-pending",
            {"ordType": "conditional", "instType": "SPOT"},
        )
        fills = self._signed_get("/api/v5/trade/fills", {"instType": "SPOT", "limit": "50"})
        return Truth(
            balances=_parse_balances(balances),
            open_orders=[*_parse_orders(orders), *_parse_algos(algos)],
            recent_fills=_parse_fills(fills),
        )

    def place_entry_with_stop(self, coid: str, qty: Decimal, stop: Decimal, *, pair: str) -> OrderRef:
        release_policy.ensure_live_orders_allowed()
        if coid in self._recent:
            return self._recent[coid]
        if not pair:
            raise ValueError("okx entry requires a pair")
        rules = self.rules(pair)
        lot = _quantize_qty(qty, rules.lot_decimals)
        price_stop = _quantize_price(stop, rules.price_decimals)
        _reject_size(lot, rules, self._prices.get(pair))
        limit_price = _quantize_price(price_stop * (Decimal(1) - STOP_BUFFER), rules.price_decimals)
        entry = self._signed_post(
            "/api/v5/trade/order",
            {
                "instId": pair,
                "tdMode": "cash",
                "side": "buy",
                "ordType": "market",
                "sz": format(lot, "f"),
                "tgtCcy": "base_ccy",
                "clOrdId": coid,
            },
        )
        if not _accepted(entry):
            raise RuntimeError("okx entry was not accepted; stop not placed")
        stop_resp = self._signed_post(
            "/api/v5/trade/order-algo",
            {
                "instId": pair,
                "tdMode": "cash",
                "side": "sell",
                "ordType": "conditional",
                "sz": format(lot, "f"),
                "slTriggerPx": format(price_stop, "f"),
                "slOrdPx": format(limit_price, "f"),
                "slTriggerPxType": "last",
                "algoClOrdId": coid + "_stop",
            },
        )
        if not _accepted(stop_resp):
            raise RuntimeError("okx stop was not accepted")
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
            raise ValueError("okx exit requires a pair")
        rules = self.rules(pair)
        lot = _quantize_qty(qty, rules.lot_decimals)
        _reject_size(lot, rules, self._prices.get(pair))
        resp = self._signed_post(
            "/api/v5/trade/order",
            {
                "instId": pair,
                "tdMode": "cash",
                "side": "sell",
                "ordType": "market",
                "sz": format(lot, "f"),
                "clOrdId": coid,
            },
        )
        if not _accepted(resp):
            raise RuntimeError("okx exit was not accepted")
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
            self._signed_post(
                "/api/v5/trade/cancel-algos",
                [{"algoId": order.id, "instId": pair}],
            )

    def raise_stop(self, pair: str, new_stop: Decimal) -> None:
        release_policy.ensure_live_orders_allowed()
        rules = self.rules(pair)
        price = _quantize_price(new_stop, rules.price_decimals)
        limit_price = _quantize_price(price * (Decimal(1) - STOP_BUFFER), rules.price_decimals)
        for order in self._stop_orders(pair):
            self._signed_post(
                "/api/v5/trade/cancel-algos",
                [{"algoId": order.id, "instId": pair}],
            )
            self._signed_post(
                "/api/v5/trade/order-algo",
                {
                    "instId": pair,
                    "tdMode": "cash",
                    "side": "sell",
                    "ordType": "conditional",
                    "sz": format(order.qty, "f"),
                    "slTriggerPx": format(price, "f"),
                    "slOrdPx": format(limit_price, "f"),
                    "slTriggerPxType": "last",
                    "algoClOrdId": (order.coid or order.id) + "_raised",
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
        payload = self._signed_get("/api/v5/account/config")
        row = _first_data(payload)
        if row is None:
            raise TypeError("okx account config response missing")
        tokens = {part.strip().lower() for part in str(row.get("perm") or "").split(",") if part.strip()}
        if "withdraw" in tokens:
            raise WithdrawCapableError("okx key can withdraw; trade-only keys refused")
        return KeyPerms(can_trade="trade" in tokens, can_withdraw=False)

    def _stop_orders(self, pair: str) -> list[OpenOrder]:
        algos = self._signed_get(
            "/api/v5/trade/orders-algo-pending",
            {"ordType": "conditional", "instType": "SPOT", "instId": pair},
        )
        return [order for order in _parse_algos(algos) if order.pair == pair and order.stop_price is not None]

    def _headers(self, timestamp: str, signature: str) -> dict[str, str]:
        return {
            "OK-ACCESS-KEY": self._api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self._passphrase,
        }

    def _public_get(self, path: str, params: dict[str, str] | None = None) -> Any:
        request_path = _request_path(path, params)
        return self._transport.get(f"{BASE_URL}{request_path}", {})

    def _signed_get(self, path: str, params: dict[str, str] | None = None) -> Any:
        request_path = _request_path(path, params)
        timestamp = _iso_millis(self._now_fn())
        signature = sign_okx(self._api_secret, timestamp, "GET", request_path, "")
        return self._transport.get(f"{BASE_URL}{request_path}", self._headers(timestamp, signature))

    def _signed_post(self, path: str, body: dict | list) -> Any:
        timestamp = _iso_millis(self._now_fn())
        signature = sign_okx(self._api_secret, timestamp, "POST", path, canonical_json(body))
        return self._transport.post(f"{BASE_URL}{path}", body, self._headers(timestamp, signature))


def _request_path(path: str, params: dict[str, str] | None) -> str:
    if not params:
        return path
    return f"{path}?{urllib.parse.urlencode(params)}"


def _instrument_row(payload: Any, pair: str) -> dict:
    if not isinstance(payload, dict):
        raise TypeError("okx instruments body is not a JSON object")
    if str(payload.get("code") or "") not in {"", "0"}:
        raise ValueError("okx instruments request was refused")
    data = payload.get("data")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and str(item.get("instId") or "") == pair:
                return item
    if str(payload.get("instId") or "") == pair:
        return payload
    raise ValueError(f"okx instruments has no instId {pair!r}")


def _reject_size(qty: Decimal, rules: PairRules, price: Decimal | None) -> None:
    if qty < rules.ordermin:
        raise ValueError("qty below ordermin")
    if price is not None and qty * price < rules.costmin:
        raise ValueError("notional below costmin")


def _first_data(payload: Any) -> dict | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    return None


def _accepted(resp: Any) -> bool:
    row = _first_data(resp)
    if not isinstance(resp, dict) or str(resp.get("code") or "") != "0" or row is None:
        return False
    return str(row.get("sCode") or "0") == "0"


def _row_id(resp: Any) -> str:
    row = _first_data(resp) or {}
    return str(row.get("ordId") or row.get("algoId") or "")


def _parse_balances(payload: Any) -> list[Balance]:
    row = _first_data(payload)
    details = row.get("details") if isinstance(row, dict) else None
    if not isinstance(details, list):
        return []
    out: list[Balance] = []
    for raw in details:
        if not isinstance(raw, dict):
            continue
        free = _optional_decimal(raw.get("availBal"))
        locked = _optional_decimal(raw.get("frozenBal")) or Decimal(0)
        if free is None or (free == 0 and locked == 0):
            continue
        out.append(Balance(asset=str(raw.get("ccy") or ""), free=free, locked=locked))
    return out


def _parse_orders(payload: Any) -> list[OpenOrder]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    out: list[OpenOrder] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        qty = _optional_decimal(raw.get("sz"))
        if qty is None:
            continue
        out.append(
            OpenOrder(
                id=str(raw.get("ordId") or ""),
                coid=str(raw.get("clOrdId") or ""),
                pair=str(raw.get("instId") or ""),
                side=str(raw.get("side") or "").lower(),
                qty=qty,
                stop_price=None,
            )
        )
    return out


def _parse_algos(payload: Any) -> list[OpenOrder]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    out: list[OpenOrder] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        qty = _optional_decimal(raw.get("sz"))
        stop = _optional_decimal(raw.get("slTriggerPx"))
        if qty is None or stop is None or stop == 0:
            continue
        out.append(
            OpenOrder(
                id=str(raw.get("algoId") or ""),
                coid=str(raw.get("algoClOrdId") or ""),
                pair=str(raw.get("instId") or ""),
                side=str(raw.get("side") or "").lower(),
                qty=qty,
                stop_price=stop,
            )
        )
    return out


def _parse_fills(payload: Any) -> list[Fill]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    out: list[Fill] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        qty = _optional_decimal(raw.get("fillSz"))
        price = _optional_decimal(raw.get("fillPx"))
        if qty is None or price is None:
            continue
        out.append(
            Fill(
                id=str(raw.get("tradeId") or ""),
                coid=str(raw.get("ordId") or ""),
                pair=str(raw.get("instId") or ""),
                side=str(raw.get("side") or "").lower(),
                qty=qty,
                price=price,
                ts_ms=int(raw.get("ts") or 0),
            )
        )
    return out
