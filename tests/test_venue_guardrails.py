"""Venue adapter guardrails: source-level checks and Decimal correctness."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from pathlib import Path

import pytest

from krellbot.venues.base import PairRules
from krellbot.venues.coinbase import STOP_BUFFER, _quantize_price, _quantize_qty
from krellbot.venues.kraken import _quantize_price as k_quantize_price
from krellbot.venues.kraken import _quantize_qty as k_quantize_qty

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"


def test_no_cancel_all_orders_after_anywhere():
    """E4: never call Kraken's CancelAllOrdersAfter. Source must be free of it."""
    hits: list[tuple[Path, int, str]] = []
    pattern = "CancelAllOrdersAfter"
    for path in SRC_ROOT.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern in line:
                hits.append((path, lineno, line.strip()))
    assert not hits, f"found CancelAllOrdersAfter in source: {hits}"


def test_decimal_quantization_to_lot_decimals():
    """Lot quantize with ROUND_DOWN; price quantize the same; the venue's stop
    buffer stays exact."""
    rules = PairRules(
        ordermin=Decimal("0.0001"),
        costmin=Decimal(1),
        lot_decimals=4,
        price_decimals=2,
    )
    # ROUND_DOWN on quantity: 0.12345 → 0.1234
    assert _quantize_qty(Decimal("0.12345"), rules.lot_decimals) == Decimal("0.1234")
    # ROUND_DOWN on quantity: do not bump when the next digit is < 5
    assert _quantize_qty(Decimal("0.12349"), rules.lot_decimals) == Decimal("0.1234")
    # Price rounding: round down at 2 decimals
    assert _quantize_price(Decimal("12.349"), rules.price_decimals) == Decimal("12.34")
    # Built-in Decimal quantization matches our helpers
    direct = Decimal("0.12345").quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    assert _quantize_qty(Decimal("0.12345"), rules.lot_decimals) == direct
    # Coinbase stop-buffer exactness: 30000 * (1 - 0.5%) at 2 decimals → 29850.00
    buffered = (Decimal(30000) * (Decimal(1) - STOP_BUFFER)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    assert buffered == Decimal("29850.00")
    # Kraken quantization matches Coinbase for the same rules
    assert k_quantize_qty(Decimal("0.12345"), rules.lot_decimals) == Decimal("0.1234")
    assert k_quantize_price(Decimal("12.349"), rules.price_decimals) == Decimal("12.34")


def test_secret_never_in_exception_text(monkeypatch):
    """No `RuntimeError`, `KeyError_`, or `WithdrawCapableError` may carry the
    API key or secret bytes in its message.

    Construct the venues against fail-loud transports so any error path runs.
    """
    sentinel_key = "SENTINEL_KRELLBOT_API_KEY_ZZZ"
    sentinel_secret = "SENTINEL_KRELLBOT_API_SECRET_ZZZ"

    class BoomPost:
        def post(self, url, body, headers):
            raise RuntimeError("upstream said: nope")

    class BoomGet:
        def get(self, url, headers):
            raise RuntimeError("upstream said: nope")

    from krellbot.venues.coinbase import KeyError_
    from krellbot.venues.kraken import KrakenVenue

    with monkeypatch.context() as m:
        from krellbot import sanitize as _sanitize

        _sanitize._REGISTERED.clear()
        m.setattr(_sanitize, "_REGISTERED", set())
        kraken = KrakenVenue(
            api_key=sentinel_key,
            secret_b64=sentinel_secret,
            transport=BoomPost(),
            now_ms=lambda: 1_700_000_000,
            min_interval_ms=0,
        )
        with pytest.raises(Exception) as ei:
            kraken.place_entry_with_stop("coid-X", Decimal("0.1"), Decimal(100), pair="XBTUSD")
        msg = str(ei.value)
        assert sentinel_key not in msg
        assert sentinel_secret not in msg

    with pytest.raises(KeyError_) as ei2:
        detect_key_for_test(sentinel_secret)
    msg2 = str(ei2.value)
    assert sentinel_secret not in msg2

    with pytest.raises(KeyError_) as ei3:
        detect_key_for_test("garbage_*^&%_not_a_key")
    msg3 = str(ei3.value)
    assert "garbage_*^&%_not_a_key" not in msg3


def detect_key_for_test(secret: str):
    """Helper that re-imports detect_key to avoid leaking the sentinel via
    `pytest.parametrize`."""
    from krellbot.venues.coinbase import detect_key as _detect

    return _detect(secret)
