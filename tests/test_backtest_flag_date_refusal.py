"""`krellbot backtest --from/--to`: typed refusal for values that do not
parse as ``%Y-%m-%d`` (issue 316).

The sibling numeric flags already refuse malformed values with a typed
one-line message on stderr and exit 1 (``invalid --slippage-mult: x``).
``--from`` / ``--to`` must do the same
(``invalid --from: <value>`` / ``invalid --to: <value>``) instead of
crashing with a raw ``strptime`` ValueError traceback out of
``cmd_backtest``.

Valid dates keep the exact legacy behavior:

  * the healthy ``--from 2023-11-14 --to 2023-11-17`` window still prints
    the filtered receipt and exits 0;
  * strptime-parseable but out-of-data-range dates still get the typed
    ``no candles after filtering`` refusal (exit 1);
  * the exact representable strptime edges (``0001-01-01`` /
    ``9999-12-31``) still flow through the filter unchanged.

The suite is fully offline: the dataset is an explicit ``--data`` CSV and
the default fetch is monkeypatched to fail the test if ever called.
"""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot import cli

DAY_MS = 86_400_000
T0_MS = 1_699_920_000_000  # 2023-11-14T00:00:00Z, first candle of the fixture CSV

PACK = {
    "schema_version": 1,
    "id": "bt-date-refusal-fixture",
    "version": "1.0.0",
    "label": "fixture",
    "author": "tests",
    "origin": "fixture",
    "timeframe": "1d",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", ">", "sma2"],
    "exit": ["close", "<", "sma2"],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": "kraken", "pair": "XBTUSD"}],
}

# Daily closes over 2023-11-14 .. 2023-11-23.
CLOSES = ["10", "10", "12", "14", "8", "8", "12", "10", "10", "10"]

HEALTHY_WINDOW_STDOUT = (
    "2023-11-14 -> 2023-11-17  kraken XBTUSD 1d\n"
    "  total_return_pct: -0.4482\n"
    "  cagr_pct:         -42.1252142704582\n"
    "  max_drawdown_pct: 0.4482\n"
    "  return_to_dd:     -93.9912527436821\n"
    "  trade_count:      0\n"
    "  exposure_pct:     25.0000\n"
    "  buy_and_hold total_return_pct: 39.3725\n"
)

MALFORMED_DATES = [
    "2023/11/14",  # wrong separators
    "not-a-date",  # not a date at all
    "2023-13-01",  # month out of range
    "2023-02-30",  # day out of range for February
    "20231114",  # missing dashes
]


@pytest.fixture
def dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Isolated home + pack + explicit daily CSV; the fetch path must never run."""
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path / "kb"))

    def _no_fetch(venue, pair, tf, transport):
        raise AssertionError("--data dataset must never trigger a fetch")

    monkeypatch.setattr(cli, "_default_fetch", _no_fetch)
    monkeypatch.setattr(cli, "_default_transport", lambda: None)

    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps(PACK), encoding="utf-8")
    data = tmp_path / "data.csv"
    with data.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for i, close in enumerate(CLOSES):
            px = Decimal(close)
            w.writerow([T0_MS + i * DAY_MS, str(px), str(px + 1), str(px - 1), str(px), "100"])
    return pack, data


def _backtest(pack: Path, data: Path, *flags: str):
    return cli.main(["krellbot", "backtest", str(pack), "--venue", "kraken", "--data", str(data), *flags])


# ---------------------------------------------------------------------------
# 1. Malformed --from / --to: typed one-line refusal on stderr, exit 1.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", MALFORMED_DATES)
def test_malformed_from_refuses_typed_one_line(dataset, capsys: pytest.CaptureFixture[str], value: str):
    pack, data = dataset
    rc = _backtest(pack, data, "--from", value)
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == f"invalid --from: {value}\n"
    assert captured.out == ""


@pytest.mark.parametrize("value", MALFORMED_DATES)
def test_malformed_to_refuses_typed_one_line(dataset, capsys: pytest.CaptureFixture[str], value: str):
    pack, data = dataset
    rc = _backtest(pack, data, "--to", value)
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == f"invalid --to: {value}\n"
    assert captured.out == ""


def test_malformed_from_checked_before_to(dataset, capsys: pytest.CaptureFixture[str]):
    """Both flags bad: the first bad flag (--from) refuses; one line only."""
    pack, data = dataset
    rc = _backtest(pack, data, "--from", "bad/from", "--to", "bad/to")
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == "invalid --from: bad/from\n"
    assert "--to" not in captured.err
    assert "Traceback" not in captured.err


def test_malformed_to_with_healthy_from(dataset, capsys: pytest.CaptureFixture[str]):
    pack, data = dataset
    rc = _backtest(pack, data, "--from", "2023-11-14", "--to", "nonsense")
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == "invalid --to: nonsense\n"


# ---------------------------------------------------------------------------
# 2. Healthy in-range control: the filtered receipt is unchanged, exit 0.
# ---------------------------------------------------------------------------


def test_healthy_window_receipt_is_byte_identical(dataset, capsys: pytest.CaptureFixture[str]):
    pack, data = dataset
    assert _backtest(pack, data, "--from", "2023-11-14", "--to", "2023-11-17") == 0
    first = capsys.readouterr()
    assert first.out == HEALTHY_WINDOW_STDOUT
    assert first.err == ""

    # Deterministic: a second run of the same command prints the same bytes.
    assert _backtest(pack, data, "--from", "2023-11-14", "--to", "2023-11-17") == 0
    assert capsys.readouterr().out == HEALTHY_WINDOW_STDOUT


def test_healthy_window_json_receipt_pins_filtered_bounds(dataset, capsys: pytest.CaptureFixture[str]):
    pack, data = dataset
    assert _backtest(pack, data, "--from", "2023-11-14", "--to", "2023-11-17", "--json") == 0
    receipt = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert receipt["from"] == "2023-11-14"
    assert receipt["to"] == "2023-11-17"
    assert receipt["venue"] == "kraken"
    assert receipt["pair"] == "XBTUSD"
    assert receipt["tf"] == "1d"


# ---------------------------------------------------------------------------
# 3. Parseable but out-of-data-range dates keep the typed no-candles refusal.
# ---------------------------------------------------------------------------


def test_out_of_range_from_keeps_no_candles_refusal(dataset, capsys: pytest.CaptureFixture[str]):
    pack, data = dataset
    rc = _backtest(pack, data, "--from", "2030-01-01")
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == "no candles after filtering (pair=XBTUSD)\n"
    assert "invalid --from" not in captured.err


def test_out_of_range_to_keeps_no_candles_refusal(dataset, capsys: pytest.CaptureFixture[str]):
    pack, data = dataset
    rc = _backtest(pack, data, "--to", "2001-01-01")
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == "no candles after filtering (pair=XBTUSD)\n"
    assert "invalid --to" not in captured.err


# ---------------------------------------------------------------------------
# 4. Boundary control: the exact representable strptime edges still run.
# ---------------------------------------------------------------------------


def test_representable_edge_dates_keep_full_dataset_receipt(dataset, capsys: pytest.CaptureFixture[str]):
    pack, data = dataset
    assert _backtest(pack, data) == 0
    unfiltered = capsys.readouterr().out
    assert unfiltered.startswith("2023-11-14 -> 2023-11-23  kraken XBTUSD 1d\n")

    assert _backtest(pack, data, "--from", "0001-01-01", "--to", "9999-12-31") == 0
    captured = capsys.readouterr()
    assert captured.out == unfiltered
    assert captured.err == ""


# ---------------------------------------------------------------------------
# 5. Sibling flag control: the numeric refusals this fix mirrors are unchanged.
# ---------------------------------------------------------------------------


def test_sibling_slippage_refusal_unchanged(dataset, capsys: pytest.CaptureFixture[str]):
    pack, data = dataset
    rc = _backtest(pack, data, "--slippage-mult", "abc")
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == "invalid --slippage-mult: abc\n"


def test_empty_value_stays_ignored_like_before(dataset, capsys: pytest.CaptureFixture[str]):
    """An empty --from value is falsy, never reaches strptime, and keeps the
    legacy behavior of running the full dataset (exit 0)."""
    pack, data = dataset
    assert _backtest(pack, data) == 0
    unfiltered = capsys.readouterr().out
    assert _backtest(pack, data, "--from", "") == 0
    assert capsys.readouterr().out == unfiltered
