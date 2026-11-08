"""Synthetic strategy literals must fit the evaluator's finite float domain."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from krellbot.application.research import ResearchRequest, ResearchService
from krellbot.application.strategy import StrategyDraftService
from krellbot.pack import lint
from tests.test_ns04_research_service import PACK_DICT, _write_synthetic_csv

BAD = [str(10**400), str(-(10**400)), "1e400", "-1e400", "NaN"]
GOOD = ["0", "-12", "0.125", str(10**308), repr(sys.float_info.max)]


def _pack(literal, kind, side):
    pack = json.loads(json.dumps(PACK_DICT))
    leaf = ["close", ">", "OPERAND"] if side == 2 else ["OPERAND", "<", "close"]
    pack[kind] = {"all": [pack[kind], {"any": [leaf]}]}
    return json.loads(json.dumps(pack).replace('"OPERAND"', literal))


@pytest.fixture(autouse=True)
def isolated(home, monkeypatch, fresh_keyring):
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "0")
    monkeypatch.chdir(home)


@pytest.mark.parametrize("kind,side", [("entry", 0), ("entry", 2), ("exit", 0), ("exit", 2)])
@pytest.mark.parametrize("literal", BAD, ids=["huge-positive", "huge-negative", "positive-inf", "negative-inf", "nan"])
def test_numeric_refusal_reaches_lint_saved_draft_and_research(home, literal, kind, side):
    pack = _pack(literal, kind, side)
    before = json.dumps(pack, sort_keys=True)
    errors = lint.check(pack)
    assert errors
    assert errors == [
        {
            "field": f"{kind}.all[1].any[0][{side}]",
            "message": "numeric operand must be finite in the float64 execution domain",
        }
    ]
    assert json.dumps(pack, sort_keys=True) == before
    pack_path = home / "synthetic-bad-operand.json"
    pack_path.write_text(before, encoding="utf-8")
    assert lint.lint_pack(pack_path) == errors
    drafts = StrategyDraftService(home)
    saved = drafts.create(pack)
    validated = drafts.validate(saved["revision_id"])
    assert validated["state"] == "draft"
    assert validated["runnable"] is False
    assert validated["errors"] == errors
    assert drafts.is_runnable(saved["revision_id"]) is False
    assert drafts.get(saved["revision_id"])["errors"] == errors
    result = ResearchService(home=home, fetch=None).run(
        ResearchRequest(pack_path=pack_path, dataset_csv=_write_synthetic_csv(home / "synthetic.csv"), venue="kraken")
    )
    assert not result.ok and result.legacy_receipt is None
    assert result.refusal["code"] == "invalid_pack"
    assert result.refusal["errors"] == errors


@pytest.mark.parametrize("kind,side", [("entry", 0), ("entry", 2), ("exit", 0), ("exit", 2)])
@pytest.mark.parametrize("literal", GOOD, ids=["zero", "negative", "fractional", "large-int", "max-float"])
def test_finite_operands_remain_runnable(home, literal, kind, side):
    pack = _pack(literal, kind, side)
    assert lint.check(pack) == []
    service = StrategyDraftService(home)
    saved = service.create(pack)
    validated = service.validate(saved["revision_id"])
    assert validated["runnable"] is True and validated["state"] == "validated"


@pytest.mark.parametrize("literal,refuses", [(BAD[0], True), (BAD[2], True), (GOOD[0], False), (GOOD[-1], False)])
def test_fresh_cli_lint_and_offline_backtest_identify_rule_not_equity(home, literal, refuses):
    pack_path = home / "synthetic-cli-pack.json"
    pack_path.write_text(json.dumps(_pack(literal, "entry", 2)), encoding="utf-8")
    csv = _write_synthetic_csv(home / "synthetic-cli.csv")
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
    )
    console = Path(sys.executable).parent / ("krellbot.exe" if os.name == "nt" else "krellbot")
    for args in (
        ["lint", str(pack_path)],
        ["backtest", str(pack_path), "--venue", "kraken", "--data", str(csv), "--json"],
    ):
        run = subprocess.run(
            [str(console), *args], cwd=home / "cwd", env=env, capture_output=True, text=True, timeout=30, check=False
        )
        assert run.returncode == (1 if refuses else 0), (run.stdout, run.stderr)
        if refuses:
            if args[0] == "lint":
                assert "entry" in run.stdout + run.stderr
                assert "finite" in run.stdout + run.stderr
            else:
                # Backtest deliberately prints only the common refusal message;
                # detailed rule paths are verified through ResearchService above.
                assert run.stderr == "pack validation failed\n"
                assert run.stdout == ""
            assert "equity exceeded" not in run.stdout + run.stderr


def test_undefined_indicator_and_legacy_rules_are_unchanged():
    pack = _pack('"undefined_indicator"', "entry", 2)
    assert any("defined indicator" in e["message"] for e in lint.check(pack))
    assert lint.check({"id": "legacy", "public_label": "Legacy"}) == []
