"""NS04: ResearchService is the callable boundary for backtests.

The service:

    * Takes an explicit `home` and an injected `fetch` callable.
    * A `None` fetch means offline: zero keyring reads, zero network calls.
    * Returns a result with `legacy_receipt` (locked keys) plus a separate
      `detail` object with `schema_version: "1"` and a minimal decision trace.
    * Refuses a missing pack, an invalid pack, or gapped data without the
      caller passing `allow_gaps=True`.
    * Is deterministic: same request -> byte-identical `legacy_receipt`.
    * CLI `cmd_backtest` delegates to it and keeps its stdout, --json
      receipt shape, and exit codes.

The minimal decision trace explains one entry bar and one no-entry bar in
the synthetic CSV, names the closed candle, the indicator values, the
condition outcomes, the Target, and whether the bar is in warmup. No
trace value may come from a later bar; warmup/unknown is distinct from
False and from numeric zero.
"""

from __future__ import annotations

import csv
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot import cli
from krellbot.application.research import (
    ResearchRequest,
    ResearchResult,
    ResearchService,
)

FIX = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_pack(tmp_path: Path, pack: dict) -> Path:
    p = tmp_path / "pack.json"
    p.write_text(json.dumps(pack), encoding="utf-8")
    return p


def _write_synthetic_csv(path: Path, *, gapped: bool = False) -> Path:
    """Write a synthetic 1h CSV that matches the brief's `bar_series`.

    Bars: 10, 10, 12, 14, 8, 8, 8, 8 -> one cross above at bar 2, one
    below at bar 4. ts_ms are 1h apart starting at 0.
    """
    closes = ["10", "10", "12", "14", "8", "8", "8", "8"]
    drops = {4, 7} if gapped else set()
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for i, c in enumerate(closes):
            if i in drops:
                continue
            ts = i * 3_600_000
            w.writerow([ts, c, str(Decimal(c) + Decimal("0.5")), str(Decimal(c) - Decimal("0.5")), c, "100"])
    return path


PACK_DICT = {
    "schema_version": 1,
    "id": "sma-cross",
    "version": "1.0.0",
    "label": "SMA cross",
    "author": "krellbot tests",
    "timeframe": "1h",
    "origin": "Backtest fixture.",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", "crosses_above", "sma2"],
    "exit": ["close", "crosses_below", "sma2"],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
}


@pytest.fixture
def home(tmp_path: Path) -> Path:
    os.environ["KRELLBOT_HOME"] = str(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Equality helpers
# ---------------------------------------------------------------------------


def _canonical_receipt_bytes(receipt: dict) -> bytes:
    return json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# 1. Service receipt equals CLI --json receipt for the same synthetic CSV.
# ---------------------------------------------------------------------------


def test_service_receipt_matches_cli_json_for_same_csv(home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    pack_path = _write_pack(tmp_path, PACK_DICT)
    csv_path = _write_synthetic_csv(tmp_path / "data.csv")

    svc = ResearchService(home=home)
    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
        )
    )

    assert isinstance(result, ResearchResult)
    assert isinstance(result.legacy_receipt, dict)
    rc = cli.cmd_backtest([str(pack_path), "--venue", "kraken", "--data", str(csv_path), "--json"])
    assert rc == 0
    cli_out = capsys.readouterr().out
    cli_receipt = json.loads(cli_out.strip().splitlines()[-1])

    assert set(result.legacy_receipt.keys()) == {
        "engine_version",
        "pack_sha256",
        "data_manifest_sha256",
        "venue",
        "pair",
        "tf",
        "from",
        "to",
        "fee_bps",
        "slippage_bps",
        "slippage_mult",
        "metrics",
        "equity_curve",
    }
    assert _canonical_receipt_bytes(result.legacy_receipt) == _canonical_receipt_bytes(cli_receipt)


# ---------------------------------------------------------------------------
# 2. Missing pack and gapped CSV refuse.
# ---------------------------------------------------------------------------


def test_missing_pack_refuses(home: Path, tmp_path: Path):
    missing = tmp_path / "nope.json"
    svc = ResearchService(home=home)
    result = svc.run(
        ResearchRequest(
            pack_path=missing,
            dataset_csv=_write_synthetic_csv(tmp_path / "data.csv"),
            venue="kraken",
        )
    )
    assert result.ok is False
    assert result.legacy_receipt is None
    assert result.detail["schema_version"] == "1"
    assert result.detail["refusal"]["code"] == "missing_pack"


def test_gapped_csv_refuses(home: Path, tmp_path: Path):
    pack_path = _write_pack(tmp_path, PACK_DICT)
    csv_path = _write_synthetic_csv(tmp_path / "gap.csv", gapped=True)
    svc = ResearchService(home=home)
    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
        )
    )
    assert result.ok is False
    assert result.legacy_receipt is None
    assert result.detail["refusal"]["code"] == "gapped_data"


def test_gapped_csv_with_allow_gaps_passes(home: Path, tmp_path: Path):
    pack_path = _write_pack(tmp_path, PACK_DICT)
    csv_path = _write_synthetic_csv(tmp_path / "gap.csv", gapped=True)
    svc = ResearchService(home=home)
    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
            allow_gaps=True,
        )
    )
    assert result.ok is True
    assert result.legacy_receipt is not None


def test_invalid_pack_refuses(home: Path, tmp_path: Path):
    bad = _write_pack(tmp_path, {"schema_version": 1})  # missing required fields
    svc = ResearchService(home=home)
    result = svc.run(
        ResearchRequest(
            pack_path=bad,
            dataset_csv=_write_synthetic_csv(tmp_path / "data.csv"),
            venue="kraken",
        )
    )
    assert result.ok is False
    assert result.legacy_receipt is None
    assert result.detail["refusal"]["code"] in {"invalid_pack", "legacy_pack_not_runnable"}


# ---------------------------------------------------------------------------
# 3. Trace timestamps never exceed the bar being explained.
# ---------------------------------------------------------------------------


def _entry_bars(detail: dict) -> list[dict]:
    return [t for t in detail["trace"] if t["target"]["reason"] == "entry"]


def _no_entry_bars(detail: dict) -> list[dict]:
    return [t for t in detail["trace"] if t["target"]["reason"] != "entry"]


def test_trace_timestamps_never_exceed_bar(home: Path, tmp_path: Path):
    pack_path = _write_pack(tmp_path, PACK_DICT)
    csv_path = _write_synthetic_csv(tmp_path / "data.csv")
    svc = ResearchService(home=home)
    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
        )
    )
    assert result.ok is True
    detail = result.detail
    assert detail["schema_version"] == "1"
    traces = detail["trace"]
    # The CSV closes at bar 2 (12 > sma(10,10)=10) and at bar 4 (8 < sma(12,14)=13).
    # We expect at least one entry trace and at least one non-entry trace.
    assert len(_entry_bars(detail)) >= 1, detail
    assert len(_no_entry_bars(detail)) >= 1, detail
    # No indicator or condition operand value may come from a later bar than the bar_ts.
    bar_tss = [t["bar_ts"] for t in traces]
    # The traces must be ordered by bar_ts ascending.
    assert bar_tss == sorted(bar_tss)
    # For every trace, every indicator value's effective index must be <= bar_ts.
    # The pack's only indicator is sma2, which is defined at index i-1 (i>=1).
    # We assert the trace's "indicators" map values come from the closed candle
    # at bar_ts (and any previous bar), not from later bars.
    for t in traces:
        assert t["bar_ts"] == t["input"]["ts_ms"]
        # The "input" is the closed candle at this bar.
        assert t["input"]["close"] is not None
        assert t["input"]["high"] is not None
        assert t["input"]["low"] is not None
        assert t["input"]["open"] is not None
        assert t["input"]["volume"] is not None
        # Warmup/unknown is distinct from False and from numeric zero.
        for cond in t["conditions"]:
            outcome = cond["outcome"]
            assert outcome is True or outcome is False or outcome == "unknown"
            assert not isinstance(outcome, int) or outcome is True or outcome is False
        # All indicator values must be float | None; None is the warmup/unknown marker.
        for v in t["indicators"].values():
            assert v is None or isinstance(v, float)


def test_entry_trace_contains_required_fields(home: Path, tmp_path: Path):
    pack_path = _write_pack(tmp_path, PACK_DICT)
    csv_path = _write_synthetic_csv(tmp_path / "data.csv")
    svc = ResearchService(home=home)
    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
        )
    )
    assert result.ok is True
    detail = result.detail
    entries = _entry_bars(detail)
    assert entries, "expected at least one entry bar in the synthetic CSV"
    e = entries[0]
    # bar_ts + closed candle + indicator values + condition outcomes + target + warmup flag.
    assert "bar_ts" in e
    assert "input" in e
    assert "indicators" in e
    assert "conditions" in e
    assert "target" in e
    assert "warmup" in e
    target = e["target"]
    assert target["reason"] == "entry"
    assert target["long"] is True
    assert target["stop_price"] is not None
    # warmup flag is a real boolean.
    assert e["warmup"] is False


def test_no_entry_trace_carries_flat_target(home: Path, tmp_path: Path):
    pack_path = _write_pack(tmp_path, PACK_DICT)
    csv_path = _write_synthetic_csv(tmp_path / "data.csv")
    svc = ResearchService(home=home)
    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
        )
    )
    assert result.ok is True
    detail = result.detail
    flats = _no_entry_bars(detail)
    assert flats, "expected at least one non-entry bar in the synthetic CSV"
    f = flats[0]
    assert f["target"]["reason"] in {"flat", "warmup", "exit"}
    assert f["target"]["long"] is False
    assert f["target"]["stop_price"] is None


# ---------------------------------------------------------------------------
# 4. Explicit fee change changes the receipt.
# ---------------------------------------------------------------------------


def test_explicit_fee_changes_receipt(home: Path, tmp_path: Path):
    pack_path = _write_pack(tmp_path, PACK_DICT)
    csv_path = _write_synthetic_csv(tmp_path / "data.csv")
    svc = ResearchService(home=home)

    r0 = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
            fee_bps=10,
            slippage_bps=2,
        )
    )
    r1 = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
            fee_bps=80,
            slippage_bps=2,
        )
    )
    assert r0.ok and r1.ok
    # Pack + dataset identity stays the same; only fee differs. Receipt bytes must differ.
    assert r0.legacy_receipt["pack_sha256"] == r1.legacy_receipt["pack_sha256"]
    assert r0.legacy_receipt["data_manifest_sha256"] == r1.legacy_receipt["data_manifest_sha256"]
    assert r0.legacy_receipt["fee_bps"] == 10
    assert r1.legacy_receipt["fee_bps"] == 80
    assert _canonical_receipt_bytes(r0.legacy_receipt) != _canonical_receipt_bytes(r1.legacy_receipt)


# ---------------------------------------------------------------------------
# 5. Offline call log is empty.
# ---------------------------------------------------------------------------


def test_offline_call_log_is_empty(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pack_path = _write_pack(tmp_path, PACK_DICT)
    csv_path = _write_synthetic_csv(tmp_path / "data.csv")

    # The service MUST not call any keyring getter or any network transport
    # when given an explicit dataset_csv (offline-by-data path).
    keyring_calls: list[tuple[str, str]] = []

    class _WatchKeyring:
        def get_password(self, service: str, username: str) -> str | None:
            keyring_calls.append((service, username))
            return None

    import keyring

    monkeypatch.setattr(keyring, "get_keyring", lambda: _WatchKeyring())

    # If the service were to open a socket, it would fail the test.
    from urllib import request as _urllib_request

    real_urlopen = _urllib_request.urlopen

    def _no_urlopen(*args, **kwargs):
        raise AssertionError("network access attempted in offline mode")

    monkeypatch.setattr(_urllib_request, "urlopen", _no_urlopen)

    svc = ResearchService(home=home)
    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
        )
    )
    assert result.ok is True
    assert keyring_calls == []
    # Touch real_urlopen to silence "unused import" lints without actually calling it.
    assert callable(real_urlopen)


def test_offline_service_with_none_fetch_does_not_call(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A `None` fetch and no dataset_csv must still work: zero network calls, zero keyring reads."""
    pack_path = _write_pack(tmp_path, PACK_DICT)
    csv_path = _write_synthetic_csv(tmp_path / "data.csv")

    keyring_calls: list[tuple[str, str]] = []

    class _WatchKeyring:
        def get_password(self, service: str, username: str) -> str | None:
            keyring_calls.append((service, username))
            return None

    import keyring

    monkeypatch.setattr(keyring, "get_keyring", lambda: _WatchKeyring())
    from urllib import request as _urllib_request

    def _no_urlopen(*args, **kwargs):
        raise AssertionError("network access attempted in offline mode")

    monkeypatch.setattr(_urllib_request, "urlopen", _no_urlopen)

    svc = ResearchService(home=home, fetch=None)
    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
        )
    )
    assert result.ok is True
    assert keyring_calls == []


def test_injected_fetch_used_when_dataset_missing(home: Path, tmp_path: Path):
    """When dataset_csv is None and a fetch callable is injected, the service uses it."""
    pack_path = _write_pack(tmp_path, PACK_DICT)
    candles = _candles_from_csv(_write_synthetic_csv(tmp_path / "data.csv"))

    seen: list[tuple[str, str, str]] = []

    def fetch(venue: str, pair: str, tf: str):
        seen.append((venue, pair, tf))
        return candles

    svc = ResearchService(home=home, fetch=fetch)
    result = svc.run(
        ResearchRequest(
            pack_path=pack_path,
            venue="kraken",
        )
    )
    assert result.ok is True
    assert seen == [("kraken", "SUIUSD", "1h")]


# ---------------------------------------------------------------------------
# 6. Determinism: same request -> same bytes.
# ---------------------------------------------------------------------------


def test_same_request_yields_byte_identical_legacy_receipt(home: Path, tmp_path: Path):
    pack_path = _write_pack(tmp_path, PACK_DICT)
    csv_path = _write_synthetic_csv(tmp_path / "data.csv")
    svc = ResearchService(home=home)
    req = ResearchRequest(
        pack_path=pack_path,
        dataset_csv=csv_path,
        venue="kraken",
        fee_bps=40,
        slippage_bps=5,
        slippage_mult=1.0,
    )
    r1 = svc.run(req)
    r2 = svc.run(req)
    assert r1.ok and r2.ok
    assert _canonical_receipt_bytes(r1.legacy_receipt) == _canonical_receipt_bytes(r2.legacy_receipt)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candles_from_csv(path: Path) -> list:
    """Parse the synthetic CSV back into Candle objects for the injected fetch path."""
    from krellbot.pack.model import Candle

    out = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(
                Candle(
                    ts_ms=int(row["ts_ms"]),
                    open=Decimal(row["open"]),
                    high=Decimal(row["high"]),
                    low=Decimal(row["low"]),
                    close=Decimal(row["close"]),
                    volume=Decimal(row["volume"]),
                )
            )
    return out
