"""Policy refuse is journaled with a reason code (M22.3).

When an enforce seam denies an agent/operator action under the user
policy file, a ``kind=user_policy`` journal row is written with
``event=refused`` and the typed reason code. Probes via ``check`` /
MCP ``policy_check`` stay silent. UI browse can show the receipt.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.application import user_policy
from krellbot.application.paper import CODE_USER_POLICY_DENIED, PaperService
from krellbot.journal import browse, read_records_lenient
from krellbot.mcp import CODE_POLICY_DENIED, McpTools
from krellbot.release_policy import PAPER_ONLY_RELEASE


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
        "author": "krellbot policy refuse tests",
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


def _deny_paper_policy(home: Path) -> None:
    user_policy.save_policy(
        home,
        {
            "schema_version": "1",
            "allow_paper_arm": False,
            "allow_live": False,
            "allow_key_export": False,
        },
        clock=lambda: 1_700_000_000,
    )


def _refuse_rows(home: Path) -> list[dict]:
    return [
        r
        for r in read_records_lenient(home)
        if r.get("kind") == "user_policy"
        and isinstance(r.get("detail"), dict)
        and r["detail"].get("event") == "refused"
    ]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    os.environ["KRELLBOT_HOME"] = str(tmp_path)
    return tmp_path


def test_paper_only_release_stays_true():
    assert PAPER_ONLY_RELEASE is True


def test_mcp_paper_arm_policy_refuse_is_journaled(home: Path):
    pack = _write_dsl_pack(home)
    _deny_paper_policy(home)
    assert _refuse_rows(home) == []

    mcp = McpTools(home, clock=lambda: 1_700_000_100)
    result = mcp.call(
        "paper_arm",
        pack_path=pack,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
    )
    assert result["ok"] is False
    assert result["effect"] == "refused"
    assert result["code"] == CODE_POLICY_DENIED
    assert result["action"] == user_policy.ACTION_PAPER_ARM
    assert result["message"] == user_policy.MESSAGE_DENY_PAPER_ARM
    assert not (home / "config.json").exists()

    refused = _refuse_rows(home)
    assert len(refused) == 1
    detail = refused[0]["detail"]
    assert detail["event"] == "refused"
    assert detail["code"] == user_policy.CODE_POLICY_DENIED
    assert detail["reason"] == user_policy.CODE_POLICY_DENIED
    assert detail["action"] == user_policy.ACTION_PAPER_ARM
    assert detail["message"] == user_policy.MESSAGE_DENY_PAPER_ARM

    browsed = browse(home, tail=20, since=None, mode=None, now=1_700_000_200)
    rows = [r for r in browsed if r.get("kind") == "user_policy" and r.get("detail", {}).get("event") == "refused"]
    assert len(rows) == 1
    assert rows[0]["mode"] == "paper"
    assert "user policy refused" in rows[0]["summary"]
    assert user_policy.CODE_POLICY_DENIED in rows[0]["summary"]
    assert user_policy.ACTION_PAPER_ARM in rows[0]["summary"]


def test_paper_service_policy_refuse_is_journaled(home: Path):
    pack = _write_dsl_pack(home)
    _deny_paper_policy(home)

    result = PaperService(home).arm(
        pack_path=pack,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
    )
    assert result.ok is False
    assert result.code == CODE_USER_POLICY_DENIED

    refused = _refuse_rows(home)
    assert len(refused) == 1
    assert refused[0]["detail"]["code"] == user_policy.CODE_POLICY_DENIED
    assert refused[0]["detail"]["action"] == user_policy.ACTION_PAPER_ARM


def test_policy_check_and_check_do_not_journal(home: Path):
    _deny_paper_policy(home)
    mcp = McpTools(home)

    decision = user_policy.check(home, user_policy.ACTION_PAPER_ARM)
    assert decision.ok is False
    assert decision.code == user_policy.CODE_POLICY_DENIED
    assert _refuse_rows(home) == []

    probe = mcp.policy_check(user_policy.ACTION_PAPER_ARM)
    assert probe["ok"] is False
    assert probe["code"] == CODE_POLICY_DENIED
    assert _refuse_rows(home) == []


def test_invalid_policy_refuse_is_journaled(home: Path):
    user_policy.policy_path(home).write_text("{not-json", encoding="utf-8")
    decision = user_policy.ensure_allowed(
        home,
        user_policy.ACTION_PAPER_ARM,
        clock=lambda: 1_700_000_050,
    )
    assert decision.ok is False
    assert decision.code == user_policy.CODE_POLICY_INVALID

    refused = _refuse_rows(home)
    assert len(refused) == 1
    assert refused[0]["detail"]["code"] == user_policy.CODE_POLICY_INVALID
    assert refused[0]["detail"]["action"] == user_policy.ACTION_PAPER_ARM
    assert refused[0]["ts"] == 1_700_000_050


def test_allowed_action_does_not_journal_refuse(home: Path):
    user_policy.save_policy(
        home,
        {
            "schema_version": "1",
            "allow_paper_arm": True,
            "allow_live": False,
            "allow_key_export": False,
        },
        clock=lambda: 1_700_000_000,
    )
    decision = user_policy.ensure_allowed(home, user_policy.ACTION_PAPER_ARM)
    assert decision.ok is True
    assert _refuse_rows(home) == []


def test_journal_oserror_does_not_flip_refuse_to_success(home: Path, monkeypatch: pytest.MonkeyPatch):
    _deny_paper_policy(home)

    def boom(*_args, **_kwargs):
        raise OSError("journal read-only")

    monkeypatch.setattr(user_policy.os, "open", boom)
    decision = user_policy.ensure_allowed(
        home,
        user_policy.ACTION_PAPER_ARM,
        clock=lambda: 1_700_000_060,
    )
    assert decision.ok is False
    assert decision.code == user_policy.CODE_POLICY_DENIED
    # Write failed (swallowed); refuse response must still stand.
    assert _refuse_rows(home) == []
