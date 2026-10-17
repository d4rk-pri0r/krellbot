"""Research runs call prepare_v1 before the backtester."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from krellbot.application.research import ResearchRequest, ResearchService

PACK = {
    "schema_version": 1,
    "id": "int09-pack",
    "version": "1.0.0",
    "label": "INT09",
    "author": "krellbot tests",
    "timeframe": "1h",
    "origin": "INT09 fixture.",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", "crosses_above", "sma2"],
    "exit": ["close", "crosses_below", "sma2"],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
}


def _pack(tmp_path: Path, extra: dict | None = None) -> Path:
    body = dict(PACK)
    if extra:
        body.update(extra)
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _csv(path: Path, rows: int) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for i in range(rows):
            close = "10" if i % 2 == 0 else "11"
            writer.writerow([i * 3_600_000, "10", "12", "9", close, "100"])
    return path


def _run(tmp_path: Path, pack: Path, csv_path: Path, nodes: list | None = None):
    return ResearchService(tmp_path, fetch=None).run(
        ResearchRequest(
            venue="kraken",
            pack_path=pack,
            dataset_csv=csv_path,
            nodes=nodes,
        )
    )


def test_future_node_refuses_before_backtester(tmp_path: Path, monkeypatch) -> None:
    import krellbot.application.research as research_mod

    calls = []
    real = research_mod.Backtester

    class _Spy(real):
        def __init__(self, *args, **kwargs):
            calls.append(args)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(research_mod, "Backtester", _Spy)
    pack = _pack(tmp_path)
    result = _run(
        tmp_path,
        pack,
        _csv(tmp_path / "bars.csv", 8),
        nodes=[{"id": "late", "bar_index": 50}],
    )
    assert result.ok is False
    assert result.refusal is not None
    assert result.refusal["code"] == "future_data"
    assert result.refusal["index"] == 50
    assert calls == []
    assert "equity" not in result.refusal


def test_closed_node_runs_once(tmp_path: Path, monkeypatch) -> None:
    import krellbot.application.research as research_mod

    calls = []
    real = research_mod.Backtester

    class _Spy(real):
        def __init__(self, pack, *args, **kwargs):
            calls.append(pack)
            super().__init__(pack, *args, **kwargs)

    monkeypatch.setattr(research_mod, "Backtester", _Spy)
    pack = _pack(tmp_path)
    result = _run(
        tmp_path,
        pack,
        _csv(tmp_path / "bars.csv", 8),
        nodes=[{"id": "closed", "bar_index": 0}],
    )
    assert result.ok is True
    assert len(calls) == 1
    assert result.detail["bar_count"] == 8


def test_one_hundred_thousand_rows(tmp_path: Path) -> None:
    pack = _pack(tmp_path)
    csv_path = _csv(tmp_path / "bars.csv", 100_000)
    result = _run(tmp_path, pack, csv_path)
    assert result.ok is True
    assert result.detail["bar_count"] == 100_000
    assert len(result.detail["trace"]) == 100_000
    assert result.legacy_receipt is not None
    assert result.legacy_receipt["engine_version"]
