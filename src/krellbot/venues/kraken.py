"""Kraken spot venue adapter.

Docs:
- https://docs.kraken.com/api/docs/rest-api/add-order
- https://docs.kraken.com/api/docs/guides/spot-rest-auth
- https://docs.kraken.com/api/docs/rest-api/get-withdrawal-methods

Auth: HMAC-SHA512 over `path + SHA256(nonce + postdata)`, key =
base64decode(secret); the signature is base64 and goes in `API-Sign`. Tests
inject `now_ns` for monotonic nonces and `min_interval_ns` for the 1-per-second
private-call budget; the journal is appended only on the third rate-limit
failure.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any, Protocol

from krellbot import journal, paths, sanitize
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

BASE_URL = "https://api.kraken.com"
PUBLIC_PATH = "/0/public"
PRIVATE_PATH = "/0/private"
WITHDRAW_METHODS = "WithdrawMethods"
ADD_ORDER = "AddOrder"
TIME_MS = 1000


def _default_now_us() -> int:
    return time.time_ns() // TIME_MS


NONCE_FILENAME = "kraken.nonce"
RATE_LIMIT_MARKER = "EAPI:Rate limit exceeded"
DEFAULT_LOT_DECIMALS = 8
DEFAULT_PRICE_DECIMALS = 5


class Transport(Protocol):
    """Anything with a `post(url, form)` returning a parsed JSON dict."""

    def post(self, url: str, form: dict[str, str], headers: dict[str, str]) -> dict: ...

    def get(self, url: str, headers: dict[str, str] | None = None) -> dict: ...


class HttpTransport:
    """Real urllib transport. Tests must not call this directly."""

    def post(self, url: str, form: dict[str, str], headers: dict[str, str]) -> dict:
        import urllib.request

        from krellbot.tls import urlopen

        body = urllib.parse.urlencode(form).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={**headers, "content-type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get(self, url: str, headers: dict[str, str] | None = None) -> dict:
        import urllib.request

        from krellbot.tls import urlopen

        req = urllib.request.Request(url, headers=headers or {}, method="GET")
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))


def sign(secret_b64: str, path: str, nonce: str, postdata: str) -> str:
    """Produce the value of `API-Sign` per Kraken's documented auth recipe.

    `path` is the request path beginning with `/0/private`. `postdata` is the
    URL-encoded body, exactly as sent. Returns base64(HMAC-SHA512).
    """
    secret = base64.b64decode(secret_b64)
    sha256 = hashlib.sha256((nonce + postdata).encode("utf-8")).digest()
    msg = path.encode("utf-8") + sha256
    digest = hmac.new(secret, msg, hashlib.sha512).digest()
    return base64.b64encode(digest).decode("utf-8")


def coid_userref(coid: str) -> int:
    """Derive Kraken's `userref` integer from a coid.

    First four bytes of SHA256(coid) as a big-endian unsigned 32-bit int,
    masked with `0x7FFFFFFF` so the wire value is non-negative and fits
    Kraken's int32-ish field.
    """
    digest = hashlib.sha256(coid.encode("utf-8")).digest()
    value = int.from_bytes(digest[:4], "big")
    return value & 0x7FFFFFFF


def _quantize_qty(value: Decimal, lot_decimals: int) -> Decimal:
    """Round quantity DOWN to the venue's lot precision."""
    if value.is_nan() or not value.is_finite():
        raise ValueError("qty must be finite")
    return value.quantize(Decimal(1).scaleb(-lot_decimals), rounding=ROUND_DOWN)


def _quantize_price(value: Decimal, price_decimals: int) -> Decimal:
    """Round price DOWN to the venue's price precision."""
    return value.quantize(Decimal(1).scaleb(-price_decimals), rounding=ROUND_DOWN)


@dataclass
class _NonceStore:
    """Monotonic nonce counter, persisted at `paths.home()/run/kraken.nonce`.

    `now_ms()` returns the current time in milliseconds; tests inject a clock
    so the nonce never reuses across simulated restarts.
    """

    home: Path

    def _path(self) -> Path:
        run = self.home / "run"
        run.mkdir(parents=True, exist_ok=True)
        return run / NONCE_FILENAME

    def _read_last(self) -> int:
        p = self._path()
        if not p.exists():
            return 0
        raw = p.read_text(encoding="utf-8").strip()
        return int(raw) if raw else 0

    def _write(self, nonce: int) -> None:
        target = self._path()
        paths.atomic_write(target, f"{nonce}\n".encode())

    def next(self, now_ms: int) -> int:
        last = self._read_last()
        nonce = max(last + 1, now_ms)
        self._write(nonce)
        return nonce


class RateLimitStop(RuntimeError):
    """Third consecutive rate-limit failure; the adapter stops retrying."""


class KrakenVenue:
    """Kraken spot adapter.

    `transport` is injected; tests pass a fake. `now_ms`/`min_interval_ms`
    allow tests to drive the nonce clock and the 1-per-second rate budget.
    """

    def __init__(
        self,
        api_key: str,
        secret_b64: str,
        transport: Transport,
        now_ms: Callable[[], int] | None = None,
        min_interval_ms: int = 1000,
        home: Path | None = None,
        *,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        sanitize.register_secret(api_key, secret_b64)
        self._api_key = api_key
        self._secret = secret_b64
        self._transport = transport
        self._now_ms = now_ms or _default_now_us
        self._min_interval_ms = min_interval_ms
        self._nonce = _NonceStore(home if home is not None else paths.home())
        self._last_call_ms: int = 0
        self._rate_failures: int = 0
        self._sleep = sleep or time.sleep

    # ---- public protocol surface ----------------------------------------

    def rules(self, pair: str) -> PairRules:
        if not pair:
            raise ValueError("kraken rules require a pair")
        payload = self._public("AssetPairs", {"pair": pair})
        result = _result(payload)
        row = result.get(pair)
        if not isinstance(row, dict):
            raise TypeError("kraken AssetPairs did not return the pair")
        return PairRules(
            ordermin=_required_decimal(row, "ordermin"),
            costmin=_required_decimal(row, "costmin"),
            lot_decimals=int(row["lot_decimals"]),
            price_decimals=int(row["pair_decimals"]),
        )

    def snapshot(self) -> Truth:
        balances_data, open_orders_data, recent_trades_data = (
            self._private("Balance", {}),
            self._private("OpenOrders", {}),
            self._private("TradesHistory", {"trades": True}),
        )
        return Truth(
            balances=_parse_balances(balances_data),
            open_orders=_parse_open_orders(open_orders_data),
            recent_fills=_parse_recent_trades(recent_trades_data),
        )

    def place_entry_with_stop(self, coid: str, qty: Decimal, stop: Decimal, *, pair: str) -> OrderRef:
        if not pair:
            raise ValueError("kraken entry requires a pair")
        existing = self._existing(coid)
        if existing is not None:
            return existing
        rules = self.rules(pair)
        lot = _quantize_qty(qty, rules.lot_decimals)
        price = _quantize_price(stop, rules.price_decimals)
        _reject_size(lot, rules, self._last_price(pair))
        form = {
            "pair": pair,
            "ordertype": "market",
            "type": "buy",
            "volume": format(lot, "f"),
            "cl_ord_id": coid,
            "userref": str(coid_userref(coid)),
            "close[ordertype]": "stop-loss",
            "close[price]": format(price, "f"),
        }
        return self._place(ADD_ORDER, form, coid=coid, side="buy", qty=lot, stop=price)

    def place_exit(self, coid: str, qty: Decimal, *, pair: str) -> OrderRef:
        if not pair:
            raise ValueError("kraken exit requires a pair")
        existing = self._existing(coid)
        if existing is not None:
            return existing
        rules = self.rules(pair)
        lot = _quantize_qty(qty, rules.lot_decimals)
        _reject_size(lot, rules, self._last_price(pair))
        form = {
            "pair": pair,
            "ordertype": "market",
            "type": "sell",
            "volume": format(lot, "f"),
            "cl_ord_id": coid,
            "userref": str(coid_userref(coid)),
        }
        return self._place(ADD_ORDER, form, coid=coid, side="sell", qty=lot, stop=None)

    def cancel_stops(self, pair: str) -> None:
        # Refuse to cancel the whole account. Cancel open orders tagged as stop
        # for this pair, by txid; the doc lists cancelOrder for one txid.
        snapshot = self.snapshot()
        for order in snapshot.open_orders:
            if order.pair == pair and order.stop_price is not None:
                self._private("CancelOrder", {"txid": order.id})

    def raise_stop(self, pair: str, new_stop: Decimal) -> None:
        rules = self.rules(pair)
        price = _quantize_price(new_stop, rules.price_decimals)
        snapshot = self.snapshot()
        for order in snapshot.open_orders:
            if order.pair == pair and order.stop_price is not None:
                self._private(
                    "EditOrder",
                    {
                        "txid": order.id,
                        "ordertype": "stop-loss",
                        "price": format(price, "f"),
                    },
                )

    def order_by_coid(self, coid: str) -> OpenOrder | None:
        snapshot = self.snapshot()
        for order in snapshot.open_orders:
            if order.coid == coid:
                return order
        return None

    def check_key(self) -> KeyPerms:
        # WithdrawMethods success → the key can withdraw → refused. A
        # permission error means it cannot, which is the only key we accept.
        # Any non-error response (including an empty list) is treated as
        # withdraw-capable; we keep the rule conservative.
        try:
            data = self._private(WITHDRAW_METHODS, {})
        except _PermissionDenied:
            return KeyPerms(can_trade=True, can_withdraw=False)
        if isinstance(data, dict):
            raise WithdrawCapableError("kraken WithdrawMethods succeeded; trade-only keys refused")
        raise WithdrawCapableError("kraken WithdrawMethods shape unknown; refused")

    # ---- internals ------------------------------------------------------

    def _place(
        self,
        endpoint: str,
        form: dict[str, str],
        *,
        coid: str,
        side: str,
        qty: Decimal,
        stop: Decimal | None,
    ) -> OrderRef:
        payload = self._private(endpoint, form)
        order_id = ""
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, dict):
                txid = result.get("txid")
                if isinstance(txid, list) and txid:
                    order_id = str(txid[0])
                elif txid:
                    order_id = str(txid)
        pair = ""
        if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
            pair = str(payload["result"].get("descr", {}).get("pair", ""))
        if not pair:
            pair = str(form.get("pair", ""))
        return OrderRef(
            id=order_id,
            coid=coid,
            pair=pair,
            side=side,
            qty=qty,
            filled_qty=Decimal(0),
            stop_price=stop,
        )

    def _existing(self, coid: str) -> OrderRef | None:
        userref = coid_userref(coid)
        for endpoint, bucket in (("OpenOrders", "open"), ("ClosedOrders", "closed")):
            payload = self._private(endpoint, {"userref": str(userref)})
            found = _match_userref(payload, bucket, coid, userref)
            if found is not None:
                return found
        return None

    def _last_price(self, pair: str) -> Decimal:
        payload = self._public("Ticker", {"pair": pair})
        result = _result(payload)
        row = result.get(pair)
        if not isinstance(row, dict):
            raise TypeError("kraken Ticker did not return the pair")
        last = row.get("c")
        if not isinstance(last, list) or not last:
            raise RuntimeError("kraken Ticker last price missing")
        return Decimal(str(last[0]))

    def _public(self, endpoint: str, query: dict[str, str]) -> Any:
        url = f"{BASE_URL}{PUBLIC_PATH}/{endpoint}?{urllib.parse.urlencode(query)}"
        return self._transport.get(url, {})

    def _private(self, endpoint: str, form: dict[str, str]) -> Any:
        for _attempt in range(3):
            payload = self._send_once(endpoint, form)
            err = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(err, list) and err:
                if any(RATE_LIMIT_MARKER in str(item) for item in err):
                    self._note_rate_limit()
                    continue
                if any("Permission" in str(item) or "Invalid key" in str(item) for item in err):
                    raise _PermissionDenied("kraken permission denied")
                raise RuntimeError(f"kraken {endpoint} rejected the request")
            self._rate_failures = 0
            return payload
        self._journal_rate_limit()
        raise RateLimitStop("kraken rate limit: stopped after 3 failures")

    def _send_once(self, endpoint: str, form: dict[str, str]) -> Any:
        nonce_str = str(self._nonce.next(int(self._now_ms())))
        body = dict(form)
        body["nonce"] = nonce_str
        path = f"{PRIVATE_PATH}/{endpoint}"
        postdata = urllib.parse.urlencode(body)
        signature = sign(self._secret, path, nonce_str, postdata)
        headers = {"API-Key": self._api_key, "API-Sign": signature}
        return self._dispatch(f"{BASE_URL}{path}", body, headers)

    def _dispatch(self, url: str, body: dict[str, str], headers: dict[str, str]) -> Any:
        now_ms = int(self._now_ms())
        delta = now_ms - self._last_call_ms
        if self._last_call_ms and delta < self._min_interval_ms:
            self._sleep((self._min_interval_ms - delta) / 1000)
            now_ms = int(self._now_ms())
        self._last_call_ms = now_ms
        return self._transport.post(url, body, headers)

    def _note_rate_limit(self) -> None:
        self._rate_failures += 1
        if self._rate_failures >= 3:
            self._journal_rate_limit()
            raise RateLimitStop("kraken rate limit: stopped after 3 failures")
        self._sleep(300.0 if self._rate_failures == 1 else 600.0)

    def _journal_rate_limit(self) -> None:
        journal.append(
            {
                "ts": int(self._now_ms()) // 1_000_000,
                "kind": "rate_limit",
                "venue": "kraken",
                "pack": "",
                "bar_ts": 0,
                "detail": "rate limit",
            }
        )


class _PermissionDenied(RuntimeError):
    """Internal marker: the venue rejected a private call as not authorized."""


def _result(payload: Any) -> dict:
    if not isinstance(payload, dict):
        return {}
    result = payload.get("result")
    return result if isinstance(result, dict) else {}


def _required_decimal(row: dict, key: str) -> Decimal:
    if key not in row:
        raise RuntimeError("kraken pair rules missing a required field")
    return Decimal(str(row[key]))


def _optional_decimal(raw: Any) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except (ValueError, ArithmeticError, TypeError):
        return None


def _reject_size(qty: Decimal, rules: PairRules, price: Decimal | None) -> None:
    if qty < rules.ordermin:
        raise ValueError("qty below ordermin")
    if price is not None and qty * price < rules.costmin:
        raise ValueError("notional below costmin")


def _parse_balances(payload: Any) -> list[Balance]:
    out: list[Balance] = []
    for asset, raw in _result(payload).items():
        free = _optional_decimal(raw)
        if free is None:
            continue
        out.append(Balance(asset=str(asset), free=free))
    return out


def _parse_open_orders(payload: Any) -> list[OpenOrder]:
    book = _result(payload).get("open")
    if not isinstance(book, dict):
        return []
    out: list[OpenOrder] = []
    for order_id, raw in book.items():
        order = _open_order(str(order_id), raw)
        if order is not None:
            out.append(order)
    return out


def _open_order(order_id: str, raw: Any) -> OpenOrder | None:
    if not isinstance(raw, dict):
        return None
    descr_raw = raw.get("descr")
    descr = descr_raw if isinstance(descr_raw, dict) else {}
    qty = _optional_decimal(raw.get("vol"))
    if qty is None:
        return None
    ordertype = str(descr.get("ordertype", ""))
    stop = _optional_decimal(raw.get("stopprice"))
    if "stop" not in ordertype and (stop is None or stop <= 0):
        stop = None
    elif stop is None or stop <= 0:
        stop = _optional_decimal(descr.get("price"))
    return OpenOrder(
        id=order_id,
        coid=str(raw.get("cl_ord_id") or ""),
        pair=str(descr.get("pair", "")),
        side=str(descr.get("type", "")),
        qty=qty,
        stop_price=stop,
    )


def _match_userref(payload: Any, bucket: str, coid: str, userref: int) -> OrderRef | None:
    book = _result(payload).get(bucket)
    if not isinstance(book, dict):
        return None
    for order_id, raw in book.items():
        if not isinstance(raw, dict):
            continue
        stored = str(raw.get("cl_ord_id") or "")
        try:
            stored_ref = int(raw.get("userref") or 0)
        except (TypeError, ValueError):
            stored_ref = 0
        if stored != coid and stored_ref != userref:
            continue
        order = _open_order(str(order_id), raw)
        if order is None:
            continue
        return OrderRef(
            id=order.id,
            coid=coid,
            pair=order.pair,
            side=order.side,
            qty=order.qty,
            filled_qty=order.qty,
            stop_price=order.stop_price,
        )
    return None


def _parse_recent_trades(payload: Any) -> list[Fill]:
    trades = _result(payload).get("trades")
    if not isinstance(trades, dict):
        return []
    out: list[Fill] = []
    for trade_id, raw in trades.items():
        if not isinstance(raw, dict):
            continue
        qty = _optional_decimal(raw.get("vol"))
        price = _optional_decimal(raw.get("price"))
        stamp = _optional_decimal(raw.get("time"))
        if qty is None or price is None or stamp is None:
            continue
        out.append(
            Fill(
                id=str(trade_id),
                coid=str(raw.get("ordertxid", "")),
                pair=str(raw.get("pair", "")),
                side=str(raw.get("type", "")),
                qty=qty,
                price=price,
                ts_ms=int(stamp * 1000),
            )
        )
    return out
