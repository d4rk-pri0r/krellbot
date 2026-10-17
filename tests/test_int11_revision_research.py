"""A research job can use a saved draft revision instead of a typed path."""

from __future__ import annotations

from krellbot.api.jobs import JobManager
from krellbot.application.strategy import StrategyDraftService


def test_unknown_revision_does_not_start_a_pack_lookup(home) -> None:
    manager = JobManager(home=home)
    result = manager._default_runner({"revision_id": "missing", "dataset_csv": "nope.csv"})
    assert result["ok"] is False
    assert result["code"] == "not_found"


def test_saved_revision_is_the_pack_path(home) -> None:
    pack = {
        "schema_version": 1,
        "id": "trend-follow",
        "version": "1.0.0",
        "label": "Trend follow",
        "author": "int11",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    summary = StrategyDraftService(home=home).create(pack)
    manager = JobManager(home=home)
    result = manager._default_runner(
        {
            "revision_id": summary["revision_id"],
            "dataset_csv": str(home / "missing.csv"),
        }
    )
    assert result["code"] != "not_found"
    assert result["code"] != "missing_pack"
