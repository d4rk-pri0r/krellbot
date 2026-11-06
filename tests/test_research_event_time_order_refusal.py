"""#262 — refuse an event-time order inversion in an otherwise complete series.

The fixture is one interior adjacent inversion: two neighbouring rows carry
DECREASING timestamps (bar 3 then bar 2) while every bar appears exactly once.
Because ``expected = (last - first) // tf_ms + 1`` still equals ``actual``,
``check_gaps`` reaches the ``missing <= 0`` early return and the public
offline ``ResearchService`` path lets a non-monotonic series through to the
backtester, producing a normal success receipt.

The contract under test: an adjacent decreasing timestamp is refused through
the EXISTING structured refusal — ``ok=False``, ``legacy_receipt=None`` and
``detail["refusal"]["code"] == "gapped_data"`` — with no new code, schema or
message shape invented here.

Fixture provenance (valid synthetic pack/CSV, no product-missing shortcut):

  * ``PACK_DICT`` and ``_write_pack`` come from
    ``tests/test_ns04_research_service.py``; that exact pack is the pack the
    existing healthy-CSV research tests run to success.
  * The CSV uses that fixture's eight closed 1h bars (same
    ``ts_ms,open,high,low,close,volume`` header and same 10/10/12/14/8/8/8/8
    closes). Only the timestamps of rows 2 and 3 are exchanged, so all eight
    bars are present exactly once and nothing is missing.

Offline: ``ResearchService(home=...)`` with ``dataset_csv`` set performs no
fetch, no network call and no keyring read.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

import pytest

from krellbot.application.research import ResearchRequest, ResearchService
from krellbot.data.gaps import GapError, check_gaps, dedupe
from krellbot.pack.model import Candle
from tests.test_ns04_research_service import PACK_DICT, _write_pack

# The fixture's genuine bar closes, in series order.
_CLOSES = ["10", "10", "12", "14", "8", "8", "8", "8"]
_HOUR_MS = 3_600_000

# Rows 2 and 3 exchanged in event time: 3h then 2h. Every bar occurs once.
_INVERTED_TS = [0, 1, 3, 2, 4, 5, 6, 7]


def _write_inverted_order_csv(path: Path) -> Path:
    """Write the eight synthetic bars once each, with one adjacent inversion."""
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for hour, close in zip(_INVERTED_TS, _CLOSES):
            w.writerow(
                [
                    hour * _HOUR_MS,
                    close,
                    str(Decimal(close) + Decimal("0.5")),
                    str(Decimal(close) - Decimal("0.5")),
                    close,
                    "100",
                ]
            )
    return path


def test_interior_inversion_with_every_bar_present_refuses_gapped_data(home: Path, tmp_path: Path) -> None:
    """A complete series with an interior adjacent inversion must refuse."""
    # The fixture itself carries every bar exactly once and one decreasing pair.
    assert len(_INVERTED_TS) == len(_CLOSES) == 8
    assert len(set(_INVERTED_TS)) == 8
    assert any(prev > nxt for prev, nxt in pairwise(_INVERTED_TS))

    pack_path = _write_pack(tmp_path, PACK_DICT)
    csv_path = _write_inverted_order_csv(tmp_path / "inverted.csv")

    service = ResearchService(home=home)
    result = service.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
        )
    )

    assert result.ok is False, result.detail
    assert result.legacy_receipt is None
    assert isinstance(result.refusal, dict), result.detail
    assert result.detail["schema_version"] == "1"
    assert result.detail["refusal"] == result.refusal
    assert result.refusal["code"] == "gapped_data", result.refusal
    assert isinstance(result.refusal["message"], str) and result.refusal["message"], result.refusal


def _series(hours):
    """Explicitly synthetic, flat-price candles isolate event-time ordering."""
    return [
        Candle(
            ts_ms=h * _HOUR_MS,
            open=Decimal(10),
            high=Decimal(11),
            low=Decimal(9),
            close=Decimal(10),
            volume=Decimal(100),
        )
        for h in hours
    ]


def _csv(path, candles):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        w.writerows((c.ts_ms, c.open, c.high, c.low, c.close, c.volume) for c in candles)
    return path


def _state(candles):
    return [(id(c), c.ts_ms, c.open, c.high, c.low, c.close, c.volume) for c in candles]


@pytest.mark.parametrize(
    "hours",
    [list(reversed(range(8))), _INVERTED_TS, [0, 1, 4, 2, 5, 6, 7]],
    ids=["descending", "complete-inversion", "inversion-with-missing"],
)
@pytest.mark.parametrize("allow_gaps", [False, True])
def test_decreasing_order_refuses_before_count_or_waiver_without_rewriting(hours, allow_gaps):
    candles = _series(hours)
    before = _state(candles)
    with pytest.raises(GapError, match="event-time order") as exc:
        check_gaps(candles, "1h", pair="SUIUSD", allow_gaps=allow_gaps)
    assert "SUIUSD" in str(exc.value) and "tf=1h" in str(exc.value)
    assert _state(candles) == before


@pytest.mark.parametrize("hours", [[], [0], list(range(8)), [0, 1, 1, 2]])
@pytest.mark.parametrize("allow_gaps", [False, True])
def test_empty_single_ascending_and_equal_timestamps_keep_existing_behavior(hours, allow_gaps):
    candles = _series(hours)
    before = _state(candles)
    check_gaps(candles, "1h", allow_gaps=allow_gaps)
    assert _state(candles) == before


@pytest.mark.parametrize("expected", [99, 100, 101])
@pytest.mark.parametrize("allow_gaps", [False, True])
def test_sorted_missing_threshold_and_waiver_are_unchanged(expected, allow_gaps):
    candles = _series([h for h in range(expected) if h != 50])
    assert len(candles) == expected - 1
    if expected == 99 and not allow_gaps:
        with pytest.raises(GapError, match="missing=1"):
            check_gaps(candles, "1h", allow_gaps=allow_gaps)
    else:
        check_gaps(candles, "1h", allow_gaps=allow_gaps)


def test_equal_timestamps_do_not_change_dedupe_last_wins():
    first, replacement = _series([1, 1])
    candles = [first, replacement]
    before = _state(candles)
    check_gaps(candles, "1h")
    assert dedupe(candles) == [replacement]
    assert dedupe(candles)[0] is replacement
    assert _state(candles) == before


def _service_case(home, tmp_path, hours, mode, allow_gaps):
    candles = _series(hours)
    before = _state(candles)
    calls = []

    def fetch(venue, pair, tf):
        calls.append((venue, pair, tf))
        return candles  # genuine injected local data seam, not a mocked result

    csv_path = _csv(tmp_path / "labelled-synthetic.csv", candles) if mode == "csv" else None
    result = ResearchService(home=home, fetch=fetch).run(
        ResearchRequest(
            pack_path=_write_pack(tmp_path, PACK_DICT),
            dataset_csv=csv_path,
            venue="kraken",
            allow_gaps=allow_gaps,
        )
    )
    assert calls == ([] if mode == "csv" else [("kraken", "SUIUSD", "1h")])
    assert _state(candles) == before
    return result


@pytest.mark.parametrize("mode", ["csv", "fetch"])
@pytest.mark.parametrize("allow_gaps", [False, True])
@pytest.mark.parametrize("hours", [list(reversed(range(8))), _INVERTED_TS], ids=["descending", "interior"])
def test_both_service_paths_refuse_complete_disorder_even_when_gaps_allowed(home, tmp_path, mode, allow_gaps, hours):
    result = _service_case(home, tmp_path, hours, mode, allow_gaps)
    assert result.ok is False
    assert result.legacy_receipt is None
    assert result.refusal is not None and result.refusal["code"] == "gapped_data"
    assert "event-time order" in result.refusal["message"]
    assert result.detail == {"schema_version": "1", "refusal": result.refusal}


@pytest.mark.parametrize("mode", ["csv", "fetch"])
@pytest.mark.parametrize("allow_gaps", [False, True])
@pytest.mark.parametrize(
    "kind,hours",
    [("ascending", list(range(8))), ("equal", [0, 1, 1, 2, 3, 4, 5, 6, 7]), ("missing", [0, 1, 3, 4, 5, 6, 7])],
)
def test_service_healthy_duplicate_and_sorted_missing_controls(home, tmp_path, mode, allow_gaps, kind, hours):
    result = _service_case(home, tmp_path, hours, mode, allow_gaps)
    if kind == "missing" and not allow_gaps:
        assert result.ok is False and result.refusal is not None
        assert result.refusal["code"] == "gapped_data" and "missing=1" in result.refusal["message"]
    else:
        assert result.ok is True, result.refusal
        assert result.refusal is None and isinstance(result.legacy_receipt, dict)
        assert [r["bar_ts"] for r in result.detail["trace"]] == [h * _HOUR_MS for h in hours]


@pytest.mark.parametrize("allow_gaps", [False, True])
@pytest.mark.parametrize(
    "kind,hours",
    [
        ("ascending", list(range(8))),
        ("interior", _INVERTED_TS),
        ("descending", list(reversed(range(8)))),
        ("missing", [0, 1, 3, 4, 5, 6, 7]),
    ],
)
def test_fresh_offline_cli_uses_real_pack_and_csv(tmp_path, kind, hours, allow_gaps):
    # Each invocation is an ordinary fresh public CLI process, not cmd_backtest
    # called in-process or a missing-pack/CSV shortcut.
    root = tmp_path / "cli"
    root.mkdir()
    for d in ("home", "app", "tmp", "cwd"):
        (root / d).mkdir()
    pack_path = _write_pack(root, PACK_DICT)
    csv_path = _csv(root / "labelled-synthetic.csv", _series(hours))
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        in {
            "PATH",
            "LANG",
            "LC_ALL",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
        }
    }
    env.update(
        HOME=str(root / "home"),
        USERPROFILE=str(root / "home"),
        KRELLBOT_HOME=str(root / "app"),
        TMPDIR=str(root / "tmp"),
        TMP=str(root / "tmp"),
        TEMP=str(root / "tmp"),
        KRELLBOT_ENABLE_LIVE="0",
        PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring",
        PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    console = Path(sys.executable).parent / ("krellbot.exe" if os.name == "nt" else "krellbot")
    assert console.is_file()
    command = [
        str(console),
        "backtest",
        str(pack_path),
        "--venue",
        "kraken",
        "--data",
        str(csv_path),
        "--json",
    ]
    if allow_gaps:
        command.append("--allow-gaps")
    run = subprocess.run(command, cwd=root / "cwd", env=env, capture_output=True, text=True, timeout=30, check=False)
    if kind in {"interior", "descending"} or (kind == "missing" and not allow_gaps):
        assert run.returncode == 1, (run.stdout, run.stderr)
        assert not run.stdout.strip()
        assert ("event-time order" if kind != "missing" else "gap refusal") in run.stderr
    else:
        assert run.returncode == 0, run.stderr
        receipt = json.loads(run.stdout)
        assert receipt["data_manifest_sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest()
        assert receipt["venue"] == "kraken" and receipt["pair"] == "SUIUSD"
        assert "metrics" in receipt and "equity_curve" in receipt
