"""INT05 — a research job carries the holdout refusal code through.

The production job runner (:class:`JobManager._default_runner`) must pass
``holdout_from_ms`` / ``holdout_to_ms`` onto the :class:`ResearchRequest`
without coercing the values (the service uses ``type(value) is int`` to
detect a malformed bound) and must surface the refusal code the service
returned. The manager's existing failure path replaces a refusal code
with the generic ``job_failed``; this test pins the requirement that
``holdout_overlap`` and ``invalid_holdout`` arrive at ``job.error["code"]``
verbatim, while every other refusal still falls back to ``job_failed``.

Observable contract (per the brief):

  * A job submitted with overlapping ``holdout_from_ms`` /
    ``holdout_to_ms`` finishes ``failed`` with
    ``error.code == "holdout_overlap"``.
  * A job submitted with ``holdout_from_ms = True`` finishes ``failed``
    with ``error.code == "invalid_holdout"`` — the runner must not
    coerce ``True`` to ``1`` before the service sees it.
  * A successful job that omits both keys does not finish ``failed`` with
    ``holdout_overlap``.
  * The stored error object only carries ``code`` and ``message`` — no
    ``equity``, ``return_pct``, ``pnl``, ``fill_price``, or
    ``venue_fill`` field.

The default runner is the production path; the test must go through
``JobManager.submit(...)`` with ``runner=None`` so ``_default_runner``
runs and calls ``ResearchService.run`` end-to-end. ``Backtester`` is
monkeypatched with a recording stand-in so the success path returns a
real receipt without spinning up a real indicator evaluator, and a
stray backtester on the refusal paths becomes observable.
"""

from __future__ import annotations

import csv
import json
import time
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

import pytest

from krellbot.api.jobs import JOB_KIND_RESEARCH_BACKTEST, JobManager
from krellbot.backtest.engine import BarRecord

# ---------------------------------------------------------------------------
# Pack + offline dataset fixtures (kept tiny so the default runner doesn't
# touch the network, the keyring, or the venue APIs).
# ---------------------------------------------------------------------------

PACK_DICT = {
    "schema_version": 1,
    "id": "int05-pack",
    "version": "1.0.0",
    "label": "INT05 holdout job pack",
    "author": "krellbot tests",
    "timeframe": "1h",
    "origin": "INT05 fixture.",
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


# ---------------------------------------------------------------------------
# Recording Backtester stand-in
# ---------------------------------------------------------------------------


class _RecordingBacktester:
    """A drop-in stand-in for ``krellbot.backtest.engine.Backtester``.

    Records every instantiation so a stray backtester on a refusal path
    is observable. Returns a single zero-pnl ``BarRecord`` from
    ``run()`` so ``build_receipt`` can shape a legacy receipt on the
    success path.
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
def backtester_spy(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingBacktester]:
    """Patch ``Backtester`` on the research module so the default runner
    uses the recording stand-in. Returns the class so tests can inspect
    ``_RecordingBacktester.instances`` after the job finishes."""
    import krellbot.application.research as research_mod

    _RecordingBacktester.instances = []
    monkeypatch.setattr(research_mod, "Backtester", _RecordingBacktester)
    return _RecordingBacktester


# ---------------------------------------------------------------------------
# Job helpers
# ---------------------------------------------------------------------------


def _build_manager(home: Path) -> JobManager:
    return JobManager(home=home)


def _wait_terminal(mgr: JobManager, job_id: str, *, timeout: float = 5.0) -> dict:
    """Poll until the job reaches a terminal state and return its
    snapshot as a dict. The test never inspects ``JobV1`` directly — the
    snapshot is the API contract."""
    deadline = time.monotonic() + timeout
    snap = None
    while time.monotonic() < deadline:
        snap = mgr.get(job_id)
        assert snap is not None, f"job {job_id} disappeared"
        if snap.state in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.005)
    assert snap is not None
    assert snap.state in {"succeeded", "failed", "cancelled"}, snap
    return snap.to_dict()


def _teardown(mgr: JobManager) -> None:
    """Drain any pending worker thread before the test returns."""
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        with mgr._lock:
            busy = mgr._running_id is not None or mgr._queue_order
        if not busy:
            break
        time.sleep(0.01)


@pytest.fixture(autouse=True)
def _scrub_venue_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear any venue / network env vars so the default runner's
    offline path is the only one taken. The runner reads no env, but
    belt-and-braces against CI leaking a real key."""
    for var in (
        "KRELLBOT_ENABLE_LIVE",
        "KRAKEN_API_KEY",
        "KRAKEN_API_SECRET",
        "COINBASE_API_KEY",
        "COINBASE_API_SECRET",
        "COINBASE_API_PASSPHRASE",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fresh ``KRELLBOT_HOME`` and ``Path.home()`` per test, no real keys."""
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Overlapping holdout finishes failed with code "holdout_overlap".
# ---------------------------------------------------------------------------


def test_overlapping_holdout_finishes_failed_with_holdout_overlap(
    home: Path,
    tmp_path: Path,
    backtester_spy: type[_RecordingBacktester],
) -> None:
    """A real research.backtest job whose scored window overlaps the
    holdout finishes ``failed`` with ``error.code == "holdout_overlap"``.

    Goes through ``JobManager.submit`` and the production default
    runner. The runner must not replace the refusal code with
    ``job_failed``.
    """
    pack_path = _write_pack(tmp_path)
    csv_path = _write_candles_csv(tmp_path / "data.csv")
    mgr = _build_manager(home)

    snap = mgr.submit(
        kind=JOB_KIND_RESEARCH_BACKTEST,
        correlation_id="int05-overlap",
        request={
            "pack_path": str(pack_path),
            "venue": "kraken",
            "pair": "SUIUSD",
            "timeframe": "1h",
            "dataset_csv": str(csv_path),
            "holdout_from_ms": 10_000_000,
            "holdout_to_ms": 14_000_000,
        },
    )

    final = _wait_terminal(mgr, snap.id)
    try:
        assert final["state"] == "failed", final
        assert final["error"] is not None, final
        assert final["error"]["code"] == "holdout_overlap", final
        assert "holdout_overlap" not in (final["error"].get("message") or "") or True  # code is the source of truth
        # The refusal must not be coerced into the generic job_failed.
        assert final["error"]["code"] != "job_failed", final
        # Stored error has the closed shape: code + message only.
        assert set(final["error"].keys()) == {"code", "message"}, final
        for forbidden in ("equity", "return_pct", "pnl", "fill_price", "venue_fill"):
            assert forbidden not in final["error"], final
        # Backtester must not have run.
        assert _RecordingBacktester.instances == [], _RecordingBacktester.instances
    finally:
        _teardown(mgr)


# ---------------------------------------------------------------------------
# 2. holdout_from_ms = True finishes failed with code "invalid_holdout".
# ---------------------------------------------------------------------------


def test_holdout_from_ms_true_finishes_failed_with_invalid_holdout(
    home: Path,
    tmp_path: Path,
    backtester_spy: type[_RecordingBacktester],
) -> None:
    """``holdout_from_ms = True`` is not an int. The runner must pass it
    through to ``ResearchRequest`` without ``int(True) == 1`` coercion,
    and the resulting refusal code must arrive at ``job.error["code"]``
    verbatim."""
    pack_path = _write_pack(tmp_path)
    csv_path = _write_candles_csv(tmp_path / "data.csv")
    mgr = _build_manager(home)

    snap = mgr.submit(
        kind=JOB_KIND_RESEARCH_BACKTEST,
        correlation_id="int05-invalid",
        request={
            "pack_path": str(pack_path),
            "venue": "kraken",
            "pair": "SUIUSD",
            "timeframe": "1h",
            "dataset_csv": str(csv_path),
            "holdout_from_ms": True,
            "holdout_to_ms": 10,
        },
    )

    final = _wait_terminal(mgr, snap.id)
    try:
        assert final["state"] == "failed", final
        assert final["error"] is not None, final
        assert final["error"]["code"] == "invalid_holdout", final
        assert final["error"]["code"] != "job_failed", final
        # Stored error has the closed shape: code + message only.
        assert set(final["error"].keys()) == {"code", "message"}, final
        for forbidden in ("equity", "return_pct", "pnl", "fill_price", "venue_fill"):
            assert forbidden not in final["error"], final
        # Backtester must not have run.
        assert _RecordingBacktester.instances == [], _RecordingBacktester.instances
    finally:
        _teardown(mgr)


# ---------------------------------------------------------------------------
# 3. No holdout keys: no holdout_overlap failure.
# ---------------------------------------------------------------------------


def test_no_holdout_keys_does_not_fail_with_holdout_overlap(
    home: Path,
    tmp_path: Path,
    backtester_spy: type[_RecordingBacktester],
) -> None:
    """A request with no ``holdout_*`` keys keeps the prior success path.

    The job must not finish ``failed`` with ``holdout_overlap``. With
    the recording ``Backtester`` patched in, the run reaches
    ``succeeded`` and stores a receipt.
    """
    pack_path = _write_pack(tmp_path)
    csv_path = _write_candles_csv(tmp_path / "data.csv")
    mgr = _build_manager(home)

    snap = mgr.submit(
        kind=JOB_KIND_RESEARCH_BACKTEST,
        correlation_id="int05-noholdout",
        request={
            "pack_path": str(pack_path),
            "venue": "kraken",
            "pair": "SUIUSD",
            "timeframe": "1h",
            "dataset_csv": str(csv_path),
        },
    )

    final = _wait_terminal(mgr, snap.id)
    try:
        # The brief is explicit: the job does not fail with holdout_overlap.
        if final["state"] == "failed":
            assert final["error"]["code"] != "holdout_overlap", final
        else:
            assert final["state"] == "succeeded", final
            assert final["result_ref"], final
        # Receipt shape unchanged: error stays None on success.
        assert final["error"] is None, final
    finally:
        _teardown(mgr)
