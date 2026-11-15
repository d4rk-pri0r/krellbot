"""Validate-only smoke against the real Kraken AddOrder endpoint.

Builds the same BTC/USD (XBTUSD) entry-with-stop request the live engine
would send, posts it with ``validate=true`` using the stored trade-only
key, and refuses to send any request body that lacks ``validate=true``.

Owner runs (M1.8)::

    uv run --no-sync python scripts/kraken_validate_smoke.py

Expect ``PASS``. No order is submitted and no cash moves.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from krellbot import paths as kb_paths
from krellbot import secrets as kb_secrets
from krellbot.venues.base import WithdrawCapableError
from krellbot.venues.kraken import (
    ADD_ORDER,
    PRIVATE_PATH,
    HttpTransport,
    KrakenVenue,
    build_entry_with_stop_form,
    require_validate_true,
)

# Kraken wire symbol for BTC/USD (M1 scope).
PAIR = "XBTUSD"
SMOKE_COID = "krellbot-validate-smoke"
STOP_FRACTION = Decimal("0.95")


class ValidateOnlyTransport:
    """Proxy that refuses AddOrder bodies lacking ``validate=true``.

    Public GETs and non-AddOrder private calls pass through unchanged.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.refused: list[dict[str, str]] = []

    def post(self, url: str, form: dict[str, str], headers: dict[str, str]) -> dict:
        if url.rstrip("/").endswith(f"{PRIVATE_PATH}/{ADD_ORDER}"):
            try:
                require_validate_true(form)
            except ValueError:
                self.refused.append(dict(form))
                raise
        return self._inner.post(url, form, headers)

    def get(self, url: str, headers: dict[str, str] | None = None) -> dict:
        return self._inner.get(url, headers)


def post_validate_only(
    transport: Any,
    url: str,
    body: dict[str, str],
    headers: dict[str, str],
) -> dict:
    """Send only when ``body`` carries ``validate=true``; else refuse."""
    require_validate_true(body)
    return transport.post(url, body, headers)


def build_btc_usd_validate_form(
    *,
    qty: Decimal,
    stop: Decimal,
    lot_decimals: int,
    price_decimals: int,
    coid: str = SMOKE_COID,
    pair: str = PAIR,
) -> dict[str, str]:
    """Same entry-with-stop fields as the engine, plus ``validate=true``."""
    form = build_entry_with_stop_form(
        coid,
        qty,
        stop,
        pair=pair,
        lot_decimals=lot_decimals,
        price_decimals=price_decimals,
    )
    form["validate"] = "true"
    return form


def run_smoke(
    *,
    transport: Any,
    api_key: str,
    secret_b64: str,
    home: Path | None = None,
    pair: str = PAIR,
) -> str:
    """Drive the validate-only AddOrder path. Returns ``PASS`` or raises."""
    guarded = ValidateOnlyTransport(transport)
    venue = KrakenVenue(
        api_key,
        secret_b64,
        guarded,
        home=home if home is not None else kb_paths.home(),
        min_interval_ms=0,
    )
    perms = venue.check_key()
    if not perms.can_trade or perms.can_withdraw:
        raise RuntimeError("stored key is not trade-only")
    rules = venue.rules(pair)
    last = venue._last_price(pair)
    qty = rules.ordermin
    stop = (last * STOP_FRACTION).quantize(Decimal(1).scaleb(-rules.price_decimals))
    # Shape pin: smoke form must match the engine entry-with-stop fields.
    expected = build_btc_usd_validate_form(
        qty=qty,
        stop=stop,
        lot_decimals=rules.lot_decimals,
        price_decimals=rules.price_decimals,
        pair=pair,
    )
    require_validate_true(expected)
    # Venue rebuilds the same form; transport proxy refuses any stripped body.
    payload = venue.validate_entry_with_stop(SMOKE_COID, qty, stop, pair=pair)
    if not isinstance(payload, dict):
        raise TypeError("unexpected validate response")
    errors = payload.get("error")
    if isinstance(errors, list) and errors:
        raise RuntimeError(f"kraken validate rejected: {errors}")
    return "PASS"


def main(argv: list[str] | None = None) -> int:
    del argv  # no flags; uses KRELLBOT_HOME + stored key
    try:
        api_key, secret = kb_secrets.get("kraken")
    except (FileNotFoundError, ValueError, PermissionError) as exc:
        print(f"FAIL: no stored kraken key ({exc})", file=sys.stderr)
        return 1
    try:
        result = run_smoke(
            transport=HttpTransport(),
            api_key=api_key,
            secret_b64=secret,
            home=kb_paths.home(),
        )
    except WithdrawCapableError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — smoke prints one line then exits
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
