"""MCP paper tools refuse live arm and key read with typed errors.

Pins the M22.1 safety contract: the local MCP adapter exposes only
read / draft / validate / backtest / paper-arm against application
facades, refuses live arm and any key read without calling secrets or
the keyring, and leaves config bytes unchanged on live refusal.
"""

from __future__ import annotations

import csv
import json
import os
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from krellbot.mcp import ALLOWED_TOOLS, CODE_KEY_READ_REFUSED, CODE_LIVE_ARM_REFUSED, McpTools
from krellbot.mcp.errors import MESSAGE_KEY_READ_REFUSED, MESSAGE_LIVE_ARM_REFUSED


def _write_dsl_pack(
    home: Path,
    *,
    pack_id: str = "trend-follow",
    pair: str = "SUIUSD",
    venue: str = "kraken",
) -> Path:
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Trend follow",
        "author": "krellbot mcp tests",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": venue, "pair": pair}],
    }
    target = packs / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _write_synthetic_csv(path: Path) -> Path:
    closes = ["10", "10", "12", "14", "8", "8", "8", "8"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for i, c in enumerate(closes):
            ts = i * 3_600_000
            w.writerow([ts, c, str(Decimal(c) + Decimal("0.5")), str(Decimal(c) - Decimal("0.5")), c, "100"])
    return path


def _config_bytes(home: Path) -> bytes:
    path = home / "config.json"
    if not path.exists():
        return b""
    return path.read_bytes()


def _valid_pack_dict() -> dict:
    return {
        "schema_version": 1,
        "id": "trend-follow",
        "version": "1.0.0",
        "label": "Trend follow",
        "author": "krellbot mcp tests",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }


@pytest.fixture
def home(tmp_path: Path) -> Path:
    os.environ["KRELLBOT_HOME"] = str(tmp_path)
    return tmp_path


def test_mcp_allowlist_is_five_safe_verbs_only():
    assert ALLOWED_TOOLS == ("read", "draft", "validate", "backtest", "paper_arm")
    tools = McpTools(Path("/tmp/unused-home-for-list"))
    assert tools.list_tools() == list(ALLOWED_TOOLS)
    assert "live" not in tools.list_tools()
    assert "keys" not in tools.list_tools()
    assert "secrets" not in tools.list_tools()


def test_mcp_paper_arm_mode_live_refused_without_config_change(home: Path, monkeypatch: pytest.MonkeyPatch):
    pack = _write_dsl_pack(home)
    before = _config_bytes(home)

    secrets_get = MagicMock(side_effect=AssertionError("secrets.get must not be called"))
    monkeypatch.setattr("krellbot.secrets.get", secrets_get, raising=False)

    arm_pack = MagicMock(side_effect=AssertionError("run.arm_pack must not be called on live MCP arm"))
    monkeypatch.setattr("krellbot.run.arm_pack", arm_pack, raising=False)

    mcp = McpTools(home)
    result = mcp.call(
        "paper_arm",
        pack_path=pack,
        venue="kraken",
        mode="live",
        paper_balance=Decimal(1000),
    )

    assert result["ok"] is False
    assert result["effect"] == "refused"
    assert result["code"] == CODE_LIVE_ARM_REFUSED
    assert result["message"] == MESSAGE_LIVE_ARM_REFUSED
    assert result["tool"] == "paper_arm"
    assert _config_bytes(home) == before
    arm_pack.assert_not_called()
    secrets_get.assert_not_called()


def test_mcp_live_named_tool_refused(home: Path, monkeypatch: pytest.MonkeyPatch):
    secrets_get = MagicMock(side_effect=AssertionError("secrets.get must not be called"))
    monkeypatch.setattr("krellbot.secrets.get", secrets_get, raising=False)

    mcp = McpTools(home)
    for name in ("live.arm", "live_arm", "arm_live"):
        result = mcp.call(name, venue="kraken", mode="live")
        assert result["ok"] is False
        assert result["code"] == CODE_LIVE_ARM_REFUSED
        assert result["effect"] == "refused"
    secrets_get.assert_not_called()


def test_mcp_key_read_tools_refused_without_keyring(home: Path, monkeypatch: pytest.MonkeyPatch):
    secrets_get = MagicMock(side_effect=AssertionError("secrets.get must not be called"))
    monkeypatch.setattr("krellbot.secrets.get", secrets_get, raising=False)

    import keyring

    get_password = MagicMock(side_effect=AssertionError("keyring.get_password must not be called"))
    monkeypatch.setattr(keyring, "get_password", get_password)

    mcp = McpTools(home)
    for name in ("keys.read", "secrets.get", "export_keys", "read_key", "credentials.export"):
        result = mcp.call(name, venue="kraken")
        assert result["ok"] is False
        assert result["effect"] == "refused"
        assert result["code"] == CODE_KEY_READ_REFUSED
        assert result["message"] == MESSAGE_KEY_READ_REFUSED

    secrets_get.assert_not_called()
    get_password.assert_not_called()


def test_mcp_draft_validate_backtest_paper_arm_happy_path(home: Path):
    """Smoke the five verbs offline; does not claim the owner P3 gate."""
    mcp = McpTools(home)

    draft = mcp.call("draft", pack=_valid_pack_dict())
    assert draft["ok"] is True
    revision_id = draft["result"]["revision_id"]

    validated = mcp.call("validate", revision_id=revision_id)
    assert validated["ok"] is True
    assert validated["result"]["runnable"] is True
    assert validated["result"]["state"] == "validated"

    pack_path = _write_dsl_pack(home, pack_id="sma-cross")
    # Use a short-SMA research pack for a deterministic offline backtest.
    research_pack = {
        "schema_version": 1,
        "id": "sma-cross",
        "version": "1.0.0",
        "label": "SMA cross",
        "author": "krellbot mcp tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    pack_path.write_text(json.dumps(research_pack), encoding="utf-8")
    csv_path = _write_synthetic_csv(home / "data.csv")

    backtest = mcp.call(
        "backtest",
        pack_path=pack_path,
        dataset_csv=csv_path,
        venue="kraken",
    )
    assert backtest["ok"] is True
    assert isinstance(backtest.get("legacy_receipt"), dict)

    armed = mcp.call(
        "paper_arm",
        revision_id=revision_id,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
        correlation_id="mcp-smoke",
    )
    assert armed["ok"] is True
    assert armed["code"] == "armed"
    assert armed["effect"] == "changed"

    snapshot = mcp.call("read")
    assert snapshot["ok"] is True
    assert any(row.get("revision_id") == revision_id for row in snapshot["drafts"])
    assert any(row.get("mode") == "paper" for row in snapshot["armed"])
