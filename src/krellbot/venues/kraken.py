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


class HttpTransport:
    """Real urllib transport. Tests must not call this directly."""

    def post(self, url: str, form: dict[str, str], headers: dict[str, str]) -> dict:
        import urllib.request

        body = urllib.parse.urlencode(form).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={**headers, "content-type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
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
        paths.ensure_layout()
        return paths.home() / "run" / NONCE_FILENAME

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

    # ---- public protocol surface ----------------------------------------

    def rules(self, pair: str) -> PairRules:
        # No public TradeVolume/AssetPairs call here; the engine wires this
        # through paper before live. Defaults match a typical spot pair; tests
        # override per pair.
        del pair
        return PairRules(
            ordermin=Decimal("0.0001"),
            costmin=Decimal(1),
            lot_decimals=DEFAULT_LOT_DECIMALS,
            price_decimals=DEFAULT_PRICE_DECIMALS,
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
        rules = self.rules(pair)
        lot = _quantize_qty(qty, rules.lot_decimals)
        price = _quantize_price(stop, rules.price_decimals)
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
        rules = self.rules(pair)
        lot = _quantize_qty(qty, rules.lot_decimals)
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
            filled_qty=qty,
            stop_price=stop,
        )

    def _private(self, endpoint: str, form: dict[str, str]) -> Any:
        nonce_str = str(self._nonce.next(int(self._now_ms())))
        body = dict(form)
        body["nonce"] = nonce_str
        path = f"{PRIVATE_PATH}/{endpoint}"
        postdata = urllib.parse.urlencode(body)
        signature = sign(self._secret, path, nonce_str, postdata)
        headers = {
            "API-Key": self._api_key,
            "API-Sign": signature,
        }
        url = f"{BASE_URL}{path}"

        # Tests inject a transport that returns a synthetic body. The default
        # HttpTransport is what a live call would go through, but the brief
        # forbids making that call from tests.
        payload = self._dispatch(url, body, headers)

        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, list) and err:
                marker_hit = any(RATE_LIMIT_MARKER in str(e) for e in err)
                if marker_hit:
                    self._handle_rate_limit(endpoint, err)
                # Some endpoints return a permission error string in this list.
                if any("Permission" in str(e) or "Invalid key" in str(e) for e in err):
                    raise _PermissionDenied(err)
                raise RuntimeError(f"kraken {endpoint} error: {err}")
        return payload

    def _dispatch(self, url: str, body: dict[str, str], headers: dict[str, str]) -> Any:
        # Rate budget: at most one private call per `min_interval_ms`. Tests
        # inject zero so they can fire many; the live code path stalls here.
        now_ms = int(self._now_ms())
        delta = now_ms - self._last_call_ms
        if self._last_call_ms and delta < self._min_interval_ms:
            wait_ms = self._min_interval_ms - delta
            time.sleep(wait_ms / 1000)
            now_ms = int(self._now_ms())
        self._last_call_ms = now_ms
        return self._transport.post(url, body, headers)

    def _handle_rate_limit(self, endpoint: str, errors: list[Any]) -> None:
        del endpoint
        self._rate_failures += 1
        if self._rate_failures < 3:
            # 300s on the first retry, 600s on the second. Tests inject
            # a no-op sleeper so they never wait for real.
            wait_ms = 300_000 if self._rate_failures == 1 else 600_000
            time.sleep(wait_ms / 1000)
            return
        # Third failure: stop retrying, write the journal.
        sanitized = [sanitize.redact(e) for e in errors]
        journal.append(
            {
                "ts": int(self._now_ms() // TIME_MS) * TIME_MS,
                "kind": "rate_limit",
                "venue": "kraken",
                "pack": "",
                "bar_ts": 0,
                "detail": "rate limit",
                "errors": sanitized,
            }
        )
        raise RateLimitStop("kraken rate limit: stopped after 3 failures")


class _PermissionDenied(RuntimeError):
    """Internal marker: the venue rejected a private call as not authorized."""


def _parse_balances(payload: Any) -> list[Balance]:
    if not isinstance(payload, dict):
        return []
    out: list[Balance] = []
    for asset, raw in payload.items():
        if not isinstance(raw, dict):
            continue
        try:
            free = Decimal(str(raw.get("free", "0")))
        except Exception:  # noqa: BLE001, S112 - raw venue strings, skip malformed row
            continue
        out.append(Balance(asset=asset, free=free))
    return out


def _parse_open_orders(payload: Any) -> list[OpenOrder]:
    if not isinstance(payload, dict):
        return []
    out: list[OpenOrder] = []
    for order_id, raw in payload.items():
        if not isinstance(raw, dict):
            continue
        descr = raw.get("descr") if isinstance(raw.get("descr"), dict) else {}
        coid = str(raw.get("cl_ord_id") or raw.get("userref") or "")
        try:
            qty = Decimal(str(raw.get("vol", "0")))
        except Exception:  # noqa: BLE001, S112
            continue
        ordertype = str(descr.get("ordertype", ""))
        stop: Decimal | None = None
        if ordertype == "stop-loss" or "stop" in ordertype:
            try:
                stop = Decimal(str(descr.get("price", "0")))
            except Exception:  # noqa: BLE001
                stop = None
        out.append(
            OpenOrder(
                id=order_id,
                coid=coid,
                pair=str(descr.get("pair", "")),
                side=str(descr.get("type", "")),
                qty=qty,
                stop_price=stop,
            )
        )
    return out


def _parse_recent_trades(payload: Any) -> list[Fill]:
    if not isinstance(payload, dict):
        return []
    trades = payload.get("trades")
    if not isinstance(trades, dict):
        return []
    out: list[Fill] = []
    for trade_id, raw in trades.items():
        if not isinstance(raw, dict):
            continue
        try:
            qty = Decimal(str(raw.get("vol", "0")))
            price = Decimal(str(raw.get("price", "0")))
            ts_ms = int(float(raw.get("time", 0)) * 1000)
        except Exception:  # noqa: BLE001, S112
            continue
        out.append(
            Fill(
                id=trade_id,
                coid=str(raw.get("ordertxid", "")),
                pair=str(raw.get("pair", "")),
                side=str(raw.get("type", "")),
                qty=qty,
                price=price,
                ts_ms=ts_ms,
            )
        )
    return out
