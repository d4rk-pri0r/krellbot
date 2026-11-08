"""Nonfinite synthetic paper requests refuse without changing config bytes."""

import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from krellbot.application.paper import PaperService
from krellbot.config import load_config, save_config
from tests.test_ns04_research_service import PACK_DICT, _write_pack
from tests.test_paper_command_concurrent_updates import _seed

BAD = ["NaN", "sNaN", "Infinity", "-Infinity"]


@pytest.fixture(autouse=True)
def isolated(home, monkeypatch, fresh_keyring):
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "0")
    monkeypatch.chdir(home)


@pytest.mark.parametrize("value", BAD)
def test_service_stop_refuses_nonfinite_without_config_change(home, value):
    _seed(home)
    before = (home / "config.json").read_bytes()
    result = PaperService(home=home).raise_stop(venue="kraken", pair="SUIUSD", new_stop=Decimal(value))
    assert not result.ok and result.code == "invalid_stop" and result.effect == "refused"
    assert result.revision_before == result.revision_after
    assert (home / "config.json").read_bytes() == before


@pytest.mark.parametrize("value", BAD)
def test_service_arm_refuses_nonfinite_before_engine_or_config(home, value):
    pack = _write_pack(home, PACK_DICT)
    result = PaperService(home=home).arm(pack, venue="kraken", mode="paper", paper_balance=Decimal(value))
    assert not result.ok and result.code == "invalid_balance" and result.effect == "refused"
    assert result.revision_before is result.revision_after is None
    assert not (home / "config.json").exists()


@pytest.mark.parametrize("value", BAD)
@pytest.mark.parametrize("action", ["stop", "arm"])
def test_fresh_cli_refuses_nonfinite_without_traceback_or_persistence(home, value, action):
    pack = _write_pack(home, PACK_DICT)
    if action == "stop":
        _seed(home)
    config = home / "config.json"
    before = config.read_bytes() if config.exists() else None
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}}
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        KRELLBOT_HOME=str(home),
        TMPDIR=str(home),
        TMP=str(home),
        TEMP=str(home),
        KRELLBOT_ENABLE_LIVE="0",
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
    )
    console = Path(sys.executable).parent / ("krellbot.exe" if os.name == "nt" else "krellbot")
    args = (
        ["stop", "--venue", "kraken", "--pair", "SUIUSD", "--price", value]
        if action == "stop"
        else ["arm", str(pack), "--venue", "kraken", "--mode", "paper", "--paper-balance", value]
    )
    result = subprocess.run(
        [str(console), *args], cwd=home, env=env, capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode != 0
    assert "finite" in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
    assert (config.read_bytes() if config.exists() else None) == before


def test_existing_venue_stored_mode_kill_and_finite_ordering_precedence(home, monkeypatch):
    _seed(home)
    service = PaperService(home=home)
    assert service.raise_stop(venue="bad", pair="SUIUSD", new_stop=Decimal("NaN")).code == "unknown_venue"
    assert service.raise_stop(venue="kraken", pair="MISSING", new_stop=Decimal("NaN")).code == "not_armed"
    for value in (Decimal(-1), Decimal(0), Decimal(90)):
        assert service.raise_stop(venue="kraken", pair="SUIUSD", new_stop=value).code == "invalid_stop"
    assert service.raise_stop(venue="kraken", pair="SUIUSD", new_stop=Decimal(95)).ok
    config = load_config(home)
    config.armed[0].mode = "live"
    save_config(home, config)
    assert service.raise_stop(venue="kraken", pair="SUIUSD", new_stop=Decimal("NaN")).code == "stored_mode_not_paper"
    pack = _write_pack(home, PACK_DICT)
    assert service.arm(pack, venue="bad", mode="paper", paper_balance=Decimal("NaN")).code == "unknown_venue"
    monkeypatch.setattr("krellbot.application.live_gate.kill_state", lambda *_: SimpleNamespace(engaged=True))
    assert service.arm(pack, venue="kraken", mode="paper", paper_balance=Decimal("NaN")).code == "kill_switch_engaged"
