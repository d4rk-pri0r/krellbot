"""Selected research windows keep the existing gap policy; all data is synthetic."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.application.research import ResearchRequest, ResearchService
from krellbot.pack.model import Candle
from tests.test_ns04_research_service import PACK_DICT

HOUR = 3_600_000
# Bounds are inclusive hours since the Unix epoch. Whole sources have 240 hours.
CASES = [
    pytest.param({195}, 192, 216, False, "gapped_data", id="diluted-selected-gap"),
    pytest.param({195}, 192, None, False, "gapped_data", id="from-only-gap"),
    pytest.param({5}, None, 24, False, "gapped_data", id="to-only-gap"),
    pytest.param({195}, 192, 216, True, None, id="explicit-gap-opt-in"),
    pytest.param(set(), 192, 216, False, None, id="complete-window"),
    pytest.param(set(), 192, None, False, None, id="healthy-from-only"),
    pytest.param(set(), None, 24, False, None, id="healthy-to-only"),
    pytest.param({195}, None, None, False, None, id="unbounded-under-threshold"),
    pytest.param({195}, 0, 24, False, None, id="gap-outside-window"),
    pytest.param({40, 41, 42, 43, 44}, 192, 216, False, "gapped_data", id="whole-source-still-refuses"),
    pytest.param(set(), 240, None, False, "empty_dataset", id="empty-window"),
    pytest.param(set(), 24, 24, False, None, id="single-candle"),
]


def _inputs(root, missing):
    pack = root / "synthetic-pack.json"
    pack.write_text(json.dumps({**PACK_DICT, "label": "Synthetic window-gap fixture"}), encoding="utf-8")
    candles = [
        Candle(i * HOUR, Decimal(10), Decimal(11), Decimal(9), Decimal(10), Decimal(100))
        for i in range(240)
        if i not in missing
    ]
    csv = root / "synthetic-hours.csv"
    body = "ts_ms,open,high,low,close,volume\n" + "".join(f"{c.ts_ms},10,11,9,10,100\n" for c in candles)
    csv.write_bytes(body.encode())
    return pack, csv, candles


@pytest.fixture(autouse=True)
def isolated(home, monkeypatch, fresh_keyring):
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "0")
    monkeypatch.chdir(home)


@pytest.mark.parametrize("mode", ["csv", "injected-synthetic-fetch"])
@pytest.mark.parametrize("missing,start,end,allow,code", CASES)
def test_selected_window_admission(home, mode, missing, start, end, allow, code):
    pack, csv, candles = _inputs(home, missing)
    original = csv.read_bytes()
    before = list(candles)
    calls = []

    def fetch(*args):
        calls.append(args)
        return candles

    result = ResearchService(home=home, fetch=fetch).run(
        ResearchRequest(
            pack_path=pack,
            venue="kraken",
            dataset_csv=csv if mode == "csv" else None,
            from_ms=None if start is None else start * HOUR,
            to_ms=None if end is None else end * HOUR,
            allow_gaps=allow,
        )
    )
    assert csv.read_bytes() == original
    assert candles == before
    assert calls == ([] if mode == "csv" else [("kraken", "SUIUSD", "1h")])
    if code:
        assert not result.ok
        assert result.legacy_receipt is None
        assert result.refusal["code"] == code
        assert result.detail == {"schema_version": "1", "refusal": result.refusal}
    else:
        assert result.ok, result.refusal
        assert result.refusal is None
        assert result.legacy_receipt["data_manifest_sha256"] == hashlib.sha256(original).hexdigest()
        assert result.legacy_receipt["pair"] == "SUIUSD"
        assert result.legacy_receipt["fee_bps"] == 40
        assert result.legacy_receipt["slippage_bps"] == 5


@pytest.mark.parametrize("end,refuses", [(139, False), (138, True)])
def test_selected_window_keeps_exact_one_percent_threshold(home, end, refuses):
    pack, csv, _ = _inputs(home, {50})
    result = ResearchService(home=home).run(
        ResearchRequest(pack_path=pack, venue="kraken", dataset_csv=csv, from_ms=40 * HOUR, to_ms=end * HOUR)
    )
    assert result.ok is not refuses
    if refuses:
        assert result.legacy_receipt is None
        assert result.refusal["code"] == "gapped_data"
        assert "missing=1 expected=99 actual=98" in result.refusal["message"]


def test_selected_gap_refuses_before_evaluation_and_receipt(home, monkeypatch):
    pack, csv, _ = _inputs(home, {195})

    def forbidden(*args, **kwargs):
        pytest.fail("gapped selected window reached evaluation or receipt generation")

    monkeypatch.setattr("krellbot.application.research.prepare_v1", forbidden)
    monkeypatch.setattr("krellbot.application.research.build_receipt", forbidden)
    result = ResearchService(home=home).run(
        ResearchRequest(pack_path=pack, venue="kraken", dataset_csv=csv, from_ms=190 * HOUR, to_ms=199 * HOUR)
    )
    assert not result.ok and result.legacy_receipt is None
    assert result.refusal["code"] == "gapped_data"
    assert "missing=1 expected=10 actual=9" in result.refusal["message"]


@pytest.mark.parametrize("missing,start,end,allow,code", CASES)
def test_fresh_offline_cli_selected_window(home, missing, start, end, allow, code):
    pack, csv, _ = _inputs(home, missing)
    original = csv.read_bytes()
    for name in ("cli-home", "app", "tmp", "cwd"):
        (home / name).mkdir()
    env = {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}
    }
    env.update(
        HOME=str(home / "cli-home"),
        USERPROFILE=str(home / "cli-home"),
        KRELLBOT_HOME=str(home / "app"),
        TMPDIR=str(home / "tmp"),
        TMP=str(home / "tmp"),
        TEMP=str(home / "tmp"),
        KRELLBOT_ENABLE_LIVE="0",
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    console = Path(sys.executable).parent / ("krellbot.exe" if os.name == "nt" else "krellbot")
    assert console.is_file()
    command = [str(console), "backtest", str(pack), "--venue", "kraken", "--data", str(csv), "--json"]
    for flag, hour in (("--from", start), ("--to", end)):
        if hour is not None:
            assert hour % 24 == 0
            command.extend([flag, f"1970-01-{hour // 24 + 1:02d}"])
    if allow:
        command.append("--allow-gaps")
    run = subprocess.run(command, cwd=home / "cwd", env=env, capture_output=True, text=True, timeout=30, check=False)
    assert csv.read_bytes() == original
    if code:
        assert run.returncode == 1, (run.stdout, run.stderr)
        assert not run.stdout.strip()
        assert ("gap refusal" if code == "gapped_data" else "no candles after filtering") in run.stderr
    else:
        assert run.returncode == 0, run.stderr
        receipt = json.loads(run.stdout)
        assert receipt["data_manifest_sha256"] == hashlib.sha256(original).hexdigest()
        assert receipt["venue"] == "kraken" and receipt["pair"] == "SUIUSD"
        assert "metrics" in receipt and "equity_curve" in receipt
