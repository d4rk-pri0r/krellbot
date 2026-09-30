"""INT04 — ResearchService.run refuses a holdout overlap.

The service must call ``krellbot.research.holdout.assert_disjoint`` after
the existing ``from_ms`` / ``to_ms`` candle filter and before it
constructs the backtester. The shared guard is reused unchanged. A
request that omits both ``holdout_from_ms`` and ``holdout_to_ms`` keeps
the current success path: ``assert_disjoint`` is not called.

Observable contract (per the brief):

  * ``ResearchRequest`` gains optional ``holdout_from_ms`` and
    ``holdout_to_ms`` (both default to ``None``).
  * If either bound is supplied, both must be supplied and
    ``type(value) is int``. ``True``, ``1.0``, and ``"1"`` refuse with
    code ``invalid_holdout`` before ``assert_disjoint`` and before
    ``Backtester``.
  * The scored window is the first and last candle ``ts_ms`` after the
    existing ``from_ms`` / ``to_ms`` filter.
  * A shared endpoint with the holdout counts as overlap; the service
    returns ``ok=False``, ``legacy_receipt=None``, and
    ``detail["refusal"]["code"] == "holdout_overlap"`` without
    constructing ``Backtester``.
  * The refusal detail has no ``equity``, ``return_pct``, ``pnl``,
    ``fill_price``, or ``venue_fill`` attribute.

The tests spy on the ``Backtester`` name and the ``assert_disjoint``
name that ``krellbot.application.research`` calls, so a missing guard
call or a stray backtester is observable. The dataset is supplied via
``dataset_csv`` so no network call or keyring read happens.
"""

from __future__ import annotations

import csv
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

import pytest

from krellbot.application.research import (
    ResearchRequest,
    ResearchService,
)
from krellbot.backtest.engine import BarRecord

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


PACK_DICT = {
    "schema_version": 1,
    "id": "int04-pack",
    "version": "1.0.0",
    "label": "INT04 holdout pack",
    "author": "krellbot tests",
    "timeframe": "1h",
    "origin": "INT04 fixture.",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", "crosses_above", "sma2"],
    "exit": ["close", "crosses_below", "sma2"],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
}


def _write_pack(tmp_path: Path) -> Path:
    p = tmp_path / "pack.json"
    p.write_text(json.dumps(PACK_DICT), encoding="utf-8")
    return p


def _write_candles_csv(path: Path) -> Path:
    """Eight 1h bars at ts_ms 0, 3.6M, 7.2M, ..., 25.2M.

    Scored window after the filter is ``[0, 25_200_000]``.
    """
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for i in range(8):
            ts = i * 3_600_000
            w.writerow([ts, "10", "11", "9", "10", "100"])
    return path


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Point both KRELLBOT_HOME and Path.home() at a temp dir, no real keys."""
    os.environ["KRELLBOT_HOME"] = str(tmp_path)
    os.environ.pop("KRELLBOT_ENABLE_LIVE", None)
    return tmp_path


# ---------------------------------------------------------------------------
# Spies
# ---------------------------------------------------------------------------


class _RecordingBacktester:
    """A drop-in stand-in for ``krellbot.backtest.engine.Backtester``.

    Records every instantiation so a missing guard call or a stray
    backtester after a refusal is observable. Returns a single zero-pnl
    BarRecord from ``run()`` so ``build_receipt`` can still shape a
    legacy receipt on the disjoint success path.
    """

    instances: ClassVar[list[dict]] = []

    def __init__(self, pack, candles, *, starting_cash, fee_bps, slippage_bps, slippage_mult):
        _RecordingBacktester.instances.append(
            {
                "pack": pack,
                "candles": list(candles),
                "starting_cash": starting_cash,
                "fee_bps": fee_bps,
                "slippage_bps": slippage_bps,
                "slippage_mult": slippage_mult,
            }
        )
        self.trade_count = 0

    def run(self) -> list[BarRecord]:
        return [
            BarRecord(
                t=0,
                ts_ms=0,
                open=Decimal(10),
                high=Decimal(11),
                low=Decimal(9),
                close=Decimal(10),
                cash_after=Decimal(10000),
                qty_after=Decimal(0),
                equity=Decimal(10000),
                fill=None,
            )
        ]


@pytest.fixture
def spies(monkeypatch: pytest.MonkeyPatch):
    """Replace ``Backtester`` on the service module and wrap
    ``assert_disjoint`` on the holdout module. The from-import the
    implementation does binds ``assert_disjoint`` on
    ``krellbot.application.research``; patching the source module is
    equivalent because a from-import copies the bound attribute once.

    Returns a handle with ``calls`` and ``last_args`` attributes on each
    spy so a missing or extra call is observable. ``assert_disjoint``
    delegates to the real implementation so the genuine
    ``HoldoutOverlap`` is raised for genuine overlap.
    """
    import krellbot.application.research as research_mod
    import krellbot.research.holdout as holdout_mod

    # Reset the recording backtester between tests.
    _RecordingBacktester.instances = []

    monkeypatch.setattr(research_mod, "Backtester", _RecordingBacktester)

    real_assert_disjoint = holdout_mod.assert_disjoint

    def assert_disjoint_spy(scored_from_ms, scored_to_ms, holdout_from_ms, holdout_to_ms):
        assert_disjoint_spy.calls += 1
        assert_disjoint_spy.last_args = (
            scored_from_ms,
            scored_to_ms,
            holdout_from_ms,
            holdout_to_ms,
        )
        return real_assert_disjoint(scored_from_ms, scored_to_ms, holdout_from_ms, holdout_to_ms)

    assert_disjoint_spy.calls = 0
    assert_disjoint_spy.last_args = None

    monkeypatch.setattr(holdout_mod, "assert_disjoint", assert_disjoint_spy)
    # If the service already imported the symbol, mirror the patch on
    # its module so the from-import bind is also the spy.
    if hasattr(research_mod, "assert_disjoint"):
        monkeypatch.setattr(research_mod, "assert_disjoint", assert_disjoint_spy)
    return {"backtester": _RecordingBacktester, "assert_disjoint": assert_disjoint_spy}


# ---------------------------------------------------------------------------
# 1. Overlapping holdout refuses and does not call Backtester.
# ---------------------------------------------------------------------------


def test_overlapping_holdout_refuses_and_does_not_construct_backtester(home: Path, tmp_path: Path, spies: dict) -> None:
    """A request whose scored window overlaps the holdout returns
    ``ok=False`` with code ``holdout_overlap`` and never constructs
    ``Backtester``."""
    pack_path = _write_pack(tmp_path)
    csv_path = _write_candles_csv(tmp_path / "data.csv")
    svc = ResearchService(home=home)

    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
            holdout_from_ms=10_000_000,
            holdout_to_ms=14_000_000,
        )
    )

    assert result.ok is False
    assert result.legacy_receipt is None
    assert result.detail["schema_version"] == "1"
    assert result.detail["refusal"]["code"] == "holdout_overlap"
    assert spies["assert_disjoint"].calls == 1
    assert _RecordingBacktester.instances == [], (
        "Backtester must not be constructed when the holdout overlaps the scored window"
    )


def test_overlap_refusal_detail_has_no_invented_return_fields(home: Path, tmp_path: Path, spies: dict) -> None:
    """The overlap refusal is a refusal of a score, not a return
    narrative. None of the brief-forbidden fields appear on the
    refusal detail."""
    pack_path = _write_pack(tmp_path)
    csv_path = _write_candles_csv(tmp_path / "data.csv")
    svc = ResearchService(home=home)

    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
            holdout_from_ms=10_000_000,
            holdout_to_ms=14_000_000,
        )
    )

    assert result.ok is False
    refusal = result.detail["refusal"]
    for forbidden in ("equity", "return_pct", "pnl", "fill_price", "venue_fill"):
        assert forbidden not in refusal, f"refusal must not carry {forbidden!r}; got refusal={refusal!r}"


def test_shared_endpoint_holdout_is_overlap(home: Path, tmp_path: Path, spies: dict) -> None:
    """A holdout that touches the scored window at a single endpoint is
    overlap; the guard raises and ``Backtester`` is not constructed."""
    pack_path = _write_pack(tmp_path)
    csv_path = _write_candles_csv(tmp_path / "data.csv")
    svc = ResearchService(home=home)

    # Scored window is [0, 25_200_000]; a holdout starting at 25_200_000
    # shares that endpoint and therefore overlaps.
    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
            holdout_from_ms=25_200_000,
            holdout_to_ms=30_000_000,
        )
    )

    assert result.ok is False
    assert result.detail["refusal"]["code"] == "holdout_overlap"
    assert _RecordingBacktester.instances == []


# ---------------------------------------------------------------------------
# 2. Disjoint holdout lets the backtester run once.
# ---------------------------------------------------------------------------


def test_disjoint_holdout_calls_assert_disjoint_and_backtester_once(home: Path, tmp_path: Path, spies: dict) -> None:
    """A disjoint holdout lets the guard call through and lets the
    backtester run exactly once."""
    pack_path = _write_pack(tmp_path)
    csv_path = _write_candles_csv(tmp_path / "data.csv")
    svc = ResearchService(home=home)

    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
            holdout_from_ms=30_000_000,
            holdout_to_ms=40_000_000,
        )
    )

    assert result.ok is True
    assert spies["assert_disjoint"].calls == 1
    assert len(_RecordingBacktester.instances) == 1
    # The guard was called with the first and last candle ts_ms and the
    # caller's holdout bounds.
    args = spies["assert_disjoint"].last_args
    assert args == (0, 25_200_000, 30_000_000, 40_000_000), args


# ---------------------------------------------------------------------------
# 3. Non-int holdout refuses with invalid_holdout and calls nothing.
# ---------------------------------------------------------------------------


def test_holdout_from_true_refuses_with_invalid_holdout(home: Path, tmp_path: Path, spies: dict) -> None:
    """A ``True`` holdout bound is not an int and must refuse with
    ``invalid_holdout`` before either guard call."""
    pack_path = _write_pack(tmp_path)
    csv_path = _write_candles_csv(tmp_path / "data.csv")
    svc = ResearchService(home=home)

    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
            holdout_from_ms=True,
            holdout_to_ms=10,
        )
    )

    assert result.ok is False
    assert result.legacy_receipt is None
    assert result.detail["refusal"]["code"] == "invalid_holdout"
    assert spies["assert_disjoint"].calls == 0
    assert _RecordingBacktester.instances == []


def test_holdout_to_float_refuses_with_invalid_holdout(home: Path, tmp_path: Path, spies: dict) -> None:
    """A float holdout bound is not an int even when its value is whole;
    refuse with ``invalid_holdout`` and call neither function."""
    pack_path = _write_pack(tmp_path)
    csv_path = _write_candles_csv(tmp_path / "data.csv")
    svc = ResearchService(home=home)

    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
            holdout_from_ms=0,
            holdout_to_ms=1.0,
        )
    )

    assert result.ok is False
    assert result.detail["refusal"]["code"] == "invalid_holdout"
    assert spies["assert_disjoint"].calls == 0
    assert _RecordingBacktester.instances == []


def test_holdout_from_string_refuses_with_invalid_holdout(home: Path, tmp_path: Path, spies: dict) -> None:
    """A string holdout bound is not an int; refuse with
    ``invalid_holdout`` and call neither function."""
    pack_path = _write_pack(tmp_path)
    csv_path = _write_candles_csv(tmp_path / "data.csv")
    svc = ResearchService(home=home)

    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
            holdout_from_ms="1",
            holdout_to_ms=10,
        )
    )

    assert result.ok is False
    assert result.detail["refusal"]["code"] == "invalid_holdout"
    assert spies["assert_disjoint"].calls == 0
    assert _RecordingBacktester.instances == []


def test_partial_holdout_only_from_refuses_with_invalid_holdout(home: Path, tmp_path: Path, spies: dict) -> None:
    """Supplying only ``holdout_from_ms`` without ``holdout_to_ms`` is
    invalid; both bounds must be present if either is."""
    pack_path = _write_pack(tmp_path)
    csv_path = _write_candles_csv(tmp_path / "data.csv")
    svc = ResearchService(home=home)

    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
            holdout_from_ms=0,
        )
    )

    assert result.ok is False
    assert result.detail["refusal"]["code"] == "invalid_holdout"
    assert spies["assert_disjoint"].calls == 0
    assert _RecordingBacktester.instances == []


def test_invalid_holdout_refusal_has_no_invented_return_fields(home: Path, tmp_path: Path, spies: dict) -> None:
    """The invalid-holdout refusal is also a refusal of a score; no
    forbidden return field may appear."""
    pack_path = _write_pack(tmp_path)
    csv_path = _write_candles_csv(tmp_path / "data.csv")
    svc = ResearchService(home=home)

    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
            holdout_from_ms=True,
            holdout_to_ms=10,
        )
    )

    assert result.ok is False
    refusal = result.detail["refusal"]
    for forbidden in ("equity", "return_pct", "pnl", "fill_price", "venue_fill"):
        assert forbidden not in refusal, f"refusal must not carry {forbidden!r}; got refusal={refusal!r}"


# ---------------------------------------------------------------------------
# 4. A request with both holdout fields omitted does not call assert_disjoint.
# ---------------------------------------------------------------------------


def test_request_without_holdout_fields_does_not_call_assert_disjoint(home: Path, tmp_path: Path, spies: dict) -> None:
    """A request that omits both holdout fields keeps the current
    success path; ``assert_disjoint`` is not called. ``Backtester`` is
    still constructed exactly once."""
    pack_path = _write_pack(tmp_path)
    csv_path = _write_candles_csv(tmp_path / "data.csv")
    svc = ResearchService(home=home)

    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
        )
    )

    assert result.ok is True
    assert spies["assert_disjoint"].calls == 0, (
        "assert_disjoint must not be called when the request omits both holdout fields"
    )
    assert len(_RecordingBacktester.instances) == 1
