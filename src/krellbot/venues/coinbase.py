"""Coinbase Advanced Trade venue adapter.

Docs:
- https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/create-order
- https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/key-permissions/get-api-key-permissions
- https://docs.cdp.coinbase.com/get-started/authentication/jwt-authentication

Auth: per-request JWT. The key type determines the algorithm. A PEM that
parses as an EC private key is ES256. A base64 secret that decodes to 64 bytes
is Ed25519 (`EdDSA`), where the seed is the first 32 bytes. Anything else
raises TypeError; the message never contains the secret.

Duplicate `client_order_id`: a repeat is not resent. The venue keeps a cache
of recent order refs so a second `place_entry_with_stop` for the same `coid`
returns the cached ref and emits zero POSTs.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from decimal import ROUND_DOWN, Decimal
from typing import Any, Protocol

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from krellbot import sanitize
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

API_HOST = "api.coinbase.com"
BASE_URL = f"https://{API_HOST}"
DEFAULT_LOT_DECIMALS = 8
DEFAULT_PRICE_DECIMALS = 5
STOP_BUFFER = Decimal("0.005")  # limit = stop * (1 - 0.5%)


class Transport(Protocol):
    """Anything with `get` and `post` returning parsed JSON dicts."""

    def get(self, url: str, headers: dict[str, str]) -> dict: ...
    def post(self, url: str, body: dict, headers: dict[str, str]) -> dict: ...


class HttpTransport:
    """Real urllib transport. Tests must not call this directly."""

    def get(self, url: str, headers: dict[str, str]) -> dict:
        import urllib.request

        from krellbot.tls import urlopen

        req = urllib.request.Request(url, headers=headers, method="GET")
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def post(self, url: str, body: dict, headers: dict[str, str]) -> dict:
        import urllib.request

        from krellbot.tls import urlopen

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={**headers, "content-type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))


class KeyError_(TypeError):
    """Raised when the Coinbase key cannot be classified. The message never
    contains the secret byte-for-byte; it only mentions the exception class
    name from the underlying parse step.
    """


def detect_key(secret: str) -> tuple[str, Any]:
    """Classify a Coinbase key. Returns `(alg_name, signer)` where `signer` is
    a cryptography primitive ready to call `sign()`.

    Algorithms:
    * EC PEM (BEGIN ... PRIVATE KEY) -> ES256
    * base64 of 64 bytes              -> EdDSA; seed is the first 32 bytes.
    Anything else raises `KeyError_`. The error message never contains the
    secret.
    """
    if "BEGIN" in secret and "PRIVATE KEY" in secret:
        try:
            key = serialization.load_pem_private_key(secret.encode("utf-8"), password=None)
        except (ValueError, TypeError) as exc:
            raise KeyError_(f"coinbase: PEM key parse failed: {type(exc).__name__}") from None
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise KeyError_("coinbase: PEM is not an EC private key")
        return ("ES256", key)
    try:
        decoded = base64.b64decode(secret, validate=True)
    except (ValueError, TypeError) as exc:
        raise KeyError_(f"coinbase: not a recognized key: {type(exc).__name__}") from None
    if len(decoded) == 64:
        try:
            seed = decoded[:32]
            key = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
        except (ValueError, TypeError) as exc:
            raise KeyError_(f"coinbase: ed25519 key build failed: {type(exc).__name__}") from None
        return ("EdDSA", key)
    raise KeyError_("coinbase: key shape is unknown")


def build_jwt(
    alg: str,
    key: Any,
    *,
    key_name: str,
    nonce_hex: str,
    method: str,
    host: str,
    path: str,
    now: int,
) -> str:
    """Build a CDP JWT for one request.

    Header: `{"alg", "typ": "JWT", "kid": key_name, "nonce": nonce_hex}`.
    Claims: `sub=key_name, iss="cdp", aud=["cdp_service"], nbf=now,
    exp=now+120, uri="{METHOD} {host}{path}"` with a single space. Returns
    the three-part compact serialization.

    Coinbase signs the path WITHOUT its query string: a `?...` in the `uri`
    claim is rejected with 401. The query is stripped here so every caller
    is covered; the request URL itself keeps the query.
    """
    path = path.split("?", 1)[0]
    header = {"alg": alg, "typ": "JWT", "kid": key_name, "nonce": nonce_hex}
    claims = {
        "sub": key_name,
        "iss": "cdp",
        "aud": ["cdp_service"],
        "nbf": now,
        "exp": now + 120,
        "uri": f"{method} {host}{path}",
    }
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")))
    claims_b64 = _b64url(json.dumps(claims, separators=(",", ":")))
    signing_input = f"{header_b64}.{claims_b64}".encode("ascii")
    if alg == "ES256":
        signature = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    elif alg == "EdDSA":
        signature = key.sign(signing_input)
    else:
        raise KeyError_(f"coinbase: unsupported alg {alg!r}")
    return f"{header_b64}.{claims_b64}.{_b64url_bytes(signature)}"


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).rstrip(b"=").decode("ascii")


def _b64url_bytes(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _quantize_qty(value: Decimal, decimals: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN)


def _quantize_price(value: Decimal, decimals: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN)


def _default_now() -> int:
    import time as _time

    return int(_time.time())


def _default_nonce() -> str:
    import os

    return os.urandom(16).hex()


class CoinbaseVenue:
    """Coinbase Advanced Trade spot adapter.

    Orders require `pair=` and will not default to BTC-USD. Tests inject a fake
    `transport`, and may override `now_fn`/`nonce_fn` to control JWT claims.
    """

    def __init__(
        self,
        api_key_name: str,
        api_secret: str,
        transport: Transport,
        product_id: str = "",
        *,
        now_fn: Callable[[], int] | None = None,
        nonce_fn: Callable[[], str] | None = None,
    ) -> None:
        sanitize.register_secret(api_key_name, api_secret)
        alg, key = detect_key(api_secret)
        self._alg = alg
        self._key = key
        self._api_key_name = api_key_name
        self._transport = transport
        self._product_id = product_id
        self._now_fn = now_fn or _default_now
        self._nonce_fn = nonce_fn or _default_nonce
        self._recent: dict[str, OrderRef] = {}
        self._prices: dict[str, Decimal] = {}

    # ---- public protocol surface ----------------------------------------

    def rules(self, pair: str) -> PairRules:
        if not pair:
            raise ValueError("coinbase rules require a pair")
        payload = self._public_get(f"/api/v3/brokerage/market/products/{pair}")
        if not isinstance(payload, dict):
            raise TypeError("coinbase product rules missing")
        self._prices[pair] = Decimal(str(payload["price"]))
        return PairRules(
            ordermin=Decimal(str(payload["base_min_size"])),
            costmin=Decimal(str(payload["quote_min_size"])),
            lot_decimals=_decimals(str(payload["base_increment"])),
            price_decimals=_decimals(str(payload["quote_increment"])),
        )

    def snapshot(self) -> Truth:
        accounts = self._get("/api/v3/brokerage/accounts")
        orders = self._get("/api/v3/brokerage/orders/historical/batch?order_status=OPEN")
        fills = self._get("/api/v3/brokerage/orders/historical/fills?limit=50")
        return Truth(
            balances=_parse_coinbase_balances(accounts),
            open_orders=_parse_coinbase_orders(orders),
            recent_fills=_parse_coinbase_fills(fills),
        )

    def place_entry_with_stop(self, coid: str, qty: Decimal, stop: Decimal, *, pair: str) -> OrderRef:
        if coid in self._recent:
            return self._recent[coid]
        product = pair or self._product_id
        if not product:
            raise ValueError("coinbase entry requires a pair")
        found = self._find_order(coid, product)
        if found is not None:
            self._recent[coid] = found
            return found
        rules = self.rules(product)
        lot = _quantize_qty(qty, rules.lot_decimals)
        price_stop = _quantize_price(stop, rules.price_decimals)
        _reject_size(lot, rules, self._prices.get(product))
        limit_price = _quantize_price(
            price_stop * (Decimal(1) - STOP_BUFFER),
            rules.price_decimals,
        )
        entry = self._post(
            "/api/v3/brokerage/orders",
            {
                "client_order_id": coid,
                "product_id": product,
                "side": "BUY",
                "order_configuration": {
                    "market_market_ioc": {"base_size": format(lot, "f")},
                },
            },
        )
        if not _entry_filled(entry):
            raise RuntimeError("coinbase entry was not filled; stop not placed")

        stop_body = {
            "client_order_id": coid + "_stop",
            "product_id": product,
            "side": "SELL",
            "order_configuration": {
                "stop_limit_stop_limit_gtc": {
                    "stop_price": format(price_stop, "f"),
                    "limit_price": format(limit_price, "f"),
                    "stop_direction": "STOP_DIRECTION_STOP_DOWN",
                    "base_size": format(lot, "f"),
                },
            },
        }
        stop_resp = self._post("/api/v3/brokerage/orders", stop_body)
        if not _order_ok(stop_resp):
            raise RuntimeError("coinbase stop was not accepted")
        stop_id = _extract_order_id(stop_resp)
        ref = OrderRef(
            id=_extract_order_id(entry) or stop_id,
            coid=coid,
            pair=product,
            side="buy",
            qty=lot,
            filled_qty=lot,
            stop_price=price_stop,
        )
        self._recent[coid] = ref
        return ref

    def place_exit(self, coid: str, qty: Decimal, *, pair: str) -> OrderRef:
        product = pair or self._product_id
        if not product:
            raise ValueError("coinbase exit requires a pair")
        rules = self.rules(product)
        lot = _quantize_qty(qty, rules.lot_decimals)
        _reject_size(lot, rules, self._prices.get(product))
        resp = self._post(
            "/api/v3/brokerage/orders",
            {
                "client_order_id": coid,
                "product_id": product,
                "side": "SELL",
                "order_configuration": {
                    "market_market_ioc": {"base_size": format(lot, "f")},
                },
            },
        )
        if not _order_ok(resp):
            raise RuntimeError("coinbase exit was not accepted")
        return OrderRef(
            id=_extract_order_id(resp),
            coid=coid,
            pair=product,
            side="sell",
            qty=lot,
            filled_qty=lot,
            stop_price=None,
        )

    def cancel_stops(self, pair: str) -> None:
        snapshot = self.snapshot()
        for order in snapshot.open_orders:
            if order.pair == pair and order.stop_price is not None:
                self._post(
                    "/api/v3/brokerage/orders/cancel",
                    {"order_ids": [order.id]},
                )

    def raise_stop(self, pair: str, new_stop: Decimal) -> None:
        snapshot = self.snapshot()
        rules = self.rules(pair)
        price = _quantize_price(new_stop, rules.price_decimals)
        for order in snapshot.open_orders:
            if order.pair == pair and order.stop_price is not None:
                self._post(
                    "/api/v3/brokerage/orders/edit",
                    {"order_id": order.id, "stop_price": format(price, "f")},
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
        perms = self._get("/api/v3/brokerage/key_permissions")
        # Coinbase returns one object per scope (view, trade, transfer). If
        # transfer/can_transfer is true the key can withdraw assets; the
        # engine refuses that. trade-only is the only key we accept.
        entries = perms if isinstance(perms, list) else [perms]
        can_trade = False
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("can_transfer") is True:
                raise WithdrawCapableError("coinbase key can transfer; trade-only keys refused")
            if entry.get("can_trade") is True:
                can_trade = True
        return KeyPerms(can_trade=can_trade, can_withdraw=False)

    # ---- internals ------------------------------------------------------

    def _auth_headers(self, method: str, path: str) -> dict[str, str]:
        nonce_hex = self._nonce_fn()
        now = int(self._now_fn())
        token = build_jwt(
            self._alg,
            self._key,
            key_name=self._api_key_name,
            nonce_hex=nonce_hex,
            method=method,
            host=API_HOST,
            path=path,
            now=now,
        )
        return {"authorization": f"Bearer {token}"}

    def _get(self, path: str) -> Any:
        headers = self._auth_headers("GET", path)
        url = f"{BASE_URL}{path}"
        return self._transport.get(url, headers)

    def _post(self, path: str, body: dict) -> Any:
        headers = self._auth_headers("POST", path)
        url = f"{BASE_URL}{path}"
        return self._transport.post(url, body, headers)

    def _public_get(self, path: str) -> Any:
        return self._transport.get(f"{BASE_URL}{path}", {})

    def _find_order(self, coid: str, pair: str) -> OrderRef | None:
        cursor = ""
        for _page in range(5):
            path = f"/api/v3/brokerage/orders/historical/batch?product_ids={pair}"
            if cursor:
                path = f"{path}&cursor={cursor}"
            payload = self._get(path)
            if not isinstance(payload, dict):
                return None
            orders = payload.get("orders")
            if isinstance(orders, list):
                for raw in orders:
                    if isinstance(raw, dict) and str(raw.get("client_order_id") or "") == coid:
                        return _ref_from_coinbase(raw, coid)
            if payload.get("has_next") is not True:
                return None
            cursor = str(payload.get("cursor") or "")
            if not cursor:
                return None
        return None


def _decimals(increment: str) -> int:
    exp = Decimal(increment).as_tuple().exponent
    if not isinstance(exp, int) or exp >= 0:
        return 0
    return -exp


def _reject_size(qty: Decimal, rules: PairRules, price: Decimal | None) -> None:
    if qty < rules.ordermin:
        raise ValueError("qty below ordermin")
    if price is not None and qty * price < rules.costmin:
        raise ValueError("notional below costmin")


def _parse_coinbase_orders(payload: Any) -> list[OpenOrder]:
    orders = payload.get("orders") if isinstance(payload, dict) else None
    if not isinstance(orders, list):
        return []
    out: list[OpenOrder] = []
    for raw in orders:
        if not isinstance(raw, dict) or str(raw.get("status", "")).upper() != "OPEN":
            continue
        order = _open_from_coinbase(raw)
        if order is not None:
            out.append(order)
    return out


def _open_from_coinbase(raw: dict) -> OpenOrder | None:
    qty = _optional_decimal(_coinbase_size(raw))
    if qty is None:
        return None
    return OpenOrder(
        id=str(raw.get("order_id", "")),
        coid=str(raw.get("client_order_id", "")),
        pair=str(raw.get("product_id", "")),
        side=str(raw.get("side", "")).lower(),
        qty=qty,
        stop_price=_coinbase_stop(raw),
    )


def _ref_from_coinbase(raw: dict, coid: str) -> OrderRef:
    order = _open_from_coinbase(raw)
    qty = order.qty if order is not None else Decimal(0)
    filled = _optional_decimal(raw.get("filled_size")) or qty
    return OrderRef(
        id=str(raw.get("order_id", "")),
        coid=coid,
        pair=str(raw.get("product_id", "")),
        side=str(raw.get("side", "")).lower(),
        qty=qty,
        filled_qty=filled,
        stop_price=order.stop_price if order is not None else None,
    )


def _coinbase_size(raw: dict) -> Any:
    config = raw.get("order_configuration")
    if isinstance(config, dict):
        for box in config.values():
            if isinstance(box, dict) and "base_size" in box:
                return box["base_size"]
    return raw.get("filled_size")


def _coinbase_stop(raw: dict) -> Decimal | None:
    config = raw.get("order_configuration")
    if not isinstance(config, dict):
        return None
    box = config.get("stop_limit_stop_limit_gtc")
    if not isinstance(box, dict):
        return None
    return _optional_decimal(box.get("stop_price"))


def _optional_decimal(raw: Any) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except (ValueError, ArithmeticError, TypeError):
        return None


def _entry_filled(resp: Any) -> bool:
    """True only when the create-order body says the IOC actually filled."""
    if not isinstance(resp, dict) or resp.get("success") is not True:
        return False
    box = resp.get("success_response")
    if not isinstance(box, dict):
        return False
    if str(box.get("status", "")).upper() == "FILLED":
        return True
    raw = box.get("filled_size")
    if raw in (None, ""):
        return False
    try:
        return Decimal(str(raw)) > 0
    except (ValueError, ArithmeticError):
        return False


def _order_ok(resp: Any) -> bool:
    if isinstance(resp, dict):
        success = resp.get("success")
        if success is True:
            return True
    return False


def _extract_order_id(resp: Any) -> str:
    if not isinstance(resp, dict):
        return ""
    success = resp.get("success")
    if isinstance(success, dict):
        return str(success.get("order_id", ""))
    nested = resp.get("order")
    if isinstance(nested, dict):
        return str(nested.get("order_id", ""))
    return ""


def _parse_coinbase_balances(payload: Any) -> list[Balance]:
    accounts = payload.get("accounts") if isinstance(payload, dict) else None
    if not isinstance(accounts, list):
        return []
    out: list[Balance] = []
    for raw in accounts:
        if not isinstance(raw, dict):
            continue
        balance = raw.get("available_balance")
        free = _optional_decimal(balance.get("value") if isinstance(balance, dict) else None)
        if free is None:
            continue
        out.append(Balance(asset=str(raw.get("currency", "")), free=free))
    return out


def _parse_coinbase_fills(payload: Any) -> list[Fill]:
    fills = payload.get("fills") if isinstance(payload, dict) else None
    if not isinstance(fills, list):
        return []
    out: list[Fill] = []
    for raw in fills:
        if not isinstance(raw, dict):
            continue
        qty = _optional_decimal(raw.get("size"))
        price = _optional_decimal(raw.get("price"))
        if qty is None or price is None:
            continue
        out.append(
            Fill(
                id=str(raw.get("entry_id", "")),
                coid=str(raw.get("client_order_id", "")),
                pair=str(raw.get("product_id", "")),
                side=str(raw.get("side", "")),
                qty=qty,
                price=price,
                ts_ms=_fill_ts(raw.get("trade_time")),
            )
        )
    return out


def _fill_ts(raw: Any) -> int:
    stamp = _optional_decimal(raw)
    if stamp is None:
        return 0
    return int(stamp * 1000)
