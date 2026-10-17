"""M1R-FC: the dashboard keeps the legacy summary-shape pack view.

NS25 turned ``ui_packs.list_installed(home)`` into the pack-library
bucket API (``{bucket, pack_id, version, permissions, rollback_ref}``),
but the dashboard view builder still consumes it and expects the
legacy summary shape built by the private ``_summarize`` helper
(``{path, id, public_label, schema_version, runnable,
not_runnable_reason, markets, timeframe, label, version, author}``).
The fix adds a public ``dashboard_packs(home)`` that restores the
summary shape for the dashboard only; ``list_installed`` stays the
NS25 bucket API, unchanged.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from krellbot.ui import packs as ui_packs
from krellbot.ui import server as ui_server


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed(tmp: Path) -> None:
    """One DSL (schema_version 1) pack and one legacy pack under packs/."""
    _write_json(
        tmp / "packs" / "trend-follow.json",
        {
            "id": "trend-follow",
            "schema_version": 1,
            "label": "Trend Follow",
            "version": "1.0.0",
            "author": "kb",
            "markets": ["BTC-USD"],
            "timeframe": "1h",
        },
    )
    _write_json(
        tmp / "packs" / "old-style.json",
        {"id": "old-style", "public_label": "Old Style"},
    )


def test_dashboard_packs_returns_summary_shape(tmp_path: Path) -> None:
    """``dashboard_packs`` restores the legacy summary shape row for row."""
    _seed(tmp_path)

    rows = ui_packs.dashboard_packs(tmp_path)

    assert len(rows) == 2, rows
    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == {"trend-follow", "old-style"}

    legacy = by_id["old-style"]
    assert legacy["runnable"] is False
    assert isinstance(legacy["not_runnable_reason"], str)
    assert legacy["not_runnable_reason"]

    dsl = by_id["trend-follow"]
    assert dsl["runnable"] is True

    expected_keys = set(ui_packs._summarize(Path(), {"id": "x"}).keys())
    for row in rows:
        assert set(row.keys()) == expected_keys, sorted(row.keys())


def test_dashboard_view_uses_dashboard_packs() -> None:
    """The server view builder calls dashboard_packs, not list_installed."""
    source = inspect.getsource(ui_server)
    assert "ui_packs.dashboard_packs(" in source
    assert "ui_packs.list_installed(" not in source


def test_list_installed_still_returns_buckets(tmp_path: Path) -> None:
    """list_installed stays the NS25 bucket API, unchanged."""
    _seed(tmp_path)

    rows = ui_packs.list_installed(tmp_path)

    assert rows, "expected at least one bucket row for the seeded packs"
    expected = {"bucket", "pack_id", "version", "permissions", "rollback_ref"}
    for row in rows:
        assert set(row.keys()) == expected, sorted(row.keys())
