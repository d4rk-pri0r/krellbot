"""Owned two-average crossover generated-pack bridge test.

Traces the exact shape the mounted OwnedStrategyForm generates for the
two-average crossover recipe (``fast``/``slow`` indicator nodes consumed by
the entry/exit comparisons) through the REAL backend primitives — unchanged
``pack.lint.check`` for schema/semantic validation and unchanged
``pack.evaluate.run`` for decisions on a disclosed synthetic candle prefix.

Educational rule configuration only: this test checks mechanics, not returns.
"""

from __future__ import annotations

import subprocess
from decimal import Decimal
from pathlib import Path

from krellbot.pack import evaluate
from krellbot.pack.lint import check
from krellbot.pack.model import Candle

REPO = Path(__file__).resolve().parents[1]
GEN = REPO / "frontend" / "src" / "features" / "strategies" / "ownedStrategy.ts"

# The disclosed synthetic fixture: a falling run into a rising run. With the
# real backend math on these closes, sma(3) crosses above sma(6) on bar 13,
# sma(5) x sma(6) and ema(3) x ema(6) only on bar 14, and both averages are
# warmed up below from bar 5 on.
CLOSES = [50, 48, 46, 44, 42, 40, 38, 36, 34, 32, 30, 31, 33, 36, 40, 45]


def _make_candles(closes: list[float]) -> list[Candle]:
    out = list[Candle]()
    for i, close in enumerate(closes):
        out.append(
            Candle(
                ts_ms=i * 3_600_000,
                open=Decimal(str(close)),
                high=Decimal(str(close + 0.5)),
                low=Decimal(str(close - 0.5)),
                close=Decimal(str(close)),
                volume=Decimal("100"),
            )
        )
    return out


def _generated_pack(fast_len: int, slow_len: int, fn: str) -> dict:
    """Run the real frontend builder for the crossover recipe.

    The script feeds the same OwnedStrategyFormState the mounted form holds
    (recipe ma_cross, one shared kind, fast/slow periods, crosses entry/exit)
    through buildOwnedStrategyPack — the same function the form's update()
    calls — and prints the generated pack as JSON. No invented syntax.
    """
    import json

    form_state = (
        "{"
        f'"name":"Crossover plan","id":"crossover-plan","pair":"XXBTZUSD",'
        f'"timeframe":"1h","recipe":"ma_cross","kind":"{fn}",'
        f'"fastLength":"{fast_len}","length":"{slow_len}",'
        f'"entryComparison":"crosses_above","exitComparison":"crosses_below",'
        f'"maxAccountPct":"25","stopPct":"5"'
        "}"
    )
    module = (
        "import * as m from 'file://" + str(GEN) + "';\n"
        f"const state = {form_state};\n"
        "const pack = m.buildOwnedStrategyPack(state, {});\n"
        "if (pack === null) { process.exit(3); }\n"
        "console.log(JSON.stringify(pack));\n"
    )
    script = REPO / "tests" / "_owned_crossover_builder.mjs"
    script.write_text(module, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["node", "--experimental-strip-types", str(script)],
            capture_output=True,
            text=True,
            cwd=REPO,
            check=False,
        )
    finally:
        script.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise AssertionError(f"generated-pack runner failed: {proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout)


def test_generated_crossover_pack_validates_and_decides():
    """The real generated crossover pack passes the real validator and changes real decisions."""
    pack = _generated_pack(fast_len=3, slow_len=6, fn="sma")

    # Exactly the generated two-node shape: real indicator nodes, consumed as
    # operands by the entry/exit comparisons.
    assert pack["indicators"] == {
        "fast": {"fn": "sma", "src": "close", "len": 3},
        "slow": {"fn": "sma", "src": "close", "len": 6},
    }
    assert pack["entry"] == ["fast", "crosses_above", "slow"]
    assert pack["exit"] == ["fast", "crosses_below", "slow"]

    # Real backend schema + semantic validation (unused indicators, operand
    # resolution, lookback budget) accepts the generated pack unchanged.
    errors = check(pack)
    assert errors == []

    # Disclosed synthetic candle prefixes: while falling the fast average sits
    # below the slow one and the pack decides flat; on the bar where the rise
    # flips the fast average above the slow one the pack decides entry with
    # the pct stop from the last close (bar 13 closes at 36).
    flat = evaluate.run(pack, _make_candles(CLOSES[:11]))
    assert flat.reason == "flat"
    assert flat.long is False
    assert flat.stop_price is None

    crossed = evaluate.run(pack, _make_candles(CLOSES[:14]))
    assert crossed.reason == "entry"
    assert crossed.long is True
    assert crossed.stop_price == Decimal(36) * (Decimal(1) - Decimal(5) / Decimal(100))


def test_generated_crossover_periods_change_decisions():
    """Changing the fast period in the form changes real evaluator decisions."""
    short_fast = _generated_pack(fast_len=3, slow_len=6, fn="sma")
    longer_fast = _generated_pack(fast_len=5, slow_len=6, fn="sma")
    assert check(short_fast) == []
    assert check(longer_fast) == []

    prefix = _make_candles(CLOSES[:14])
    # sma(3) crosses above sma(6) on bar 13...
    assert evaluate.run(short_fast, prefix).reason == "entry"
    # ...but sma(5) only crosses on bar 14, so the same prefix decides flat.
    assert evaluate.run(longer_fast, prefix).reason == "flat"


def test_generated_crossover_kind_changes_decisions():
    """Switching the average kind changes real evaluator decisions."""
    sma = _generated_pack(fast_len=3, slow_len=6, fn="sma")
    ema = _generated_pack(fast_len=3, slow_len=6, fn="ema")
    assert check(sma) == []
    assert check(ema) == []

    # ema(3) x ema(6) crosses only on bar 14, one bar later than sma(3) x sma(6).
    prefix = _make_candles(CLOSES[:14])
    assert evaluate.run(sma, prefix).reason == "entry"
    assert evaluate.run(ema, prefix).reason == "flat"


def test_generated_single_average_still_validates():
    """The preserved single-average recipe still generates a valid pack."""
    pack = _generated_pack(fast_len=3, slow_len=6, fn="sma")
    single = dict(pack)
    single["indicators"] = {"ma": {"fn": "sma", "src": "close", "len": 20}}
    single["entry"] = ["close", ">", "ma"]
    single["exit"] = ["close", "<", "ma"]
    assert check(single) == []
    # 16 bars are not enough for sma(20): the old recipe's warmup behavior is
    # unchanged.
    assert evaluate.run(single, _make_candles(CLOSES)).reason == "warmup"


def test_imported_extra_indicator_shape_is_not_the_generated_subset():
    """An imported pack with an extra unused indicator fails the real validator.

    The form cannot express it and keeps such bytes as raw JSON instead of
    rewriting them; the backend independently refuses the unused indicator.
    """
    pack = _generated_pack(fast_len=3, slow_len=6, fn="sma")
    imported = dict(pack)
    imported["indicators"] = dict(pack["indicators"])
    imported["indicators"]["trend"] = {"fn": "sma", "src": "close", "len": 50}
    errors = check(imported)
    assert any("unused indicator" in e["message"] for e in errors)
