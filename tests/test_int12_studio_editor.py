"""Studio layout is stored beside the pack, not inside its execution bytes."""

from __future__ import annotations

import json

from krellbot.application.strategy import StrategyDraftService


def _pack() -> dict:
    return {
        "schema_version": 1,
        "id": "trend-follow",
        "version": "1.0.0",
        "label": "Trend follow",
        "author": "int12",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }


def test_editor_layout_does_not_rewrite_pack_bytes(home) -> None:
    service = StrategyDraftService(home=home)
    summary = service.create(_pack())
    before = service.canonical_bytes(summary["revision_id"])
    saved = service.save_editor(
        summary["revision_id"],
        {"layout": {"entry": {"x": 10, "y": 20}}},
    )
    after = service.canonical_bytes(summary["revision_id"])
    assert after == before
    assert b"layout" not in after
    assert saved["revision_id"] == summary["revision_id"]
    assert saved["editor"]["layout"]["entry"] == {"x": 10, "y": 20}
    assert saved["pack"]["entry"] == ["close", ">", "sma20"]
    on_disk = json.loads(after)
    assert "editor" not in on_disk
    assert "layout" not in on_disk


def test_missing_revision_does_not_create_a_draft(home) -> None:
    service = StrategyDraftService(home=home)
    try:
        service.save_editor("missing", {"layout": {}})
    except FileNotFoundError:
        return
    raise AssertionError("missing revision must not be created")
