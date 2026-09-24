"""Characterization tests for the legacy single-file client.

They pin what `krellbot` does today, before any phase changes it. Every
case runs the CLI in a subprocess with HOME pointed at a temp dir, so the
real ~/.krellbot is never read and no network call is made.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["KRELLBOT_API"] = "http://127.0.0.1:9"  # unroutable; any accidental call fails fast
    return subprocess.run(
        [sys.executable, "-m", "krellbot.cli", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path


def write_pack(home: Path, name: str, data: dict) -> None:
    packs = home / ".krellbot" / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    (packs / f"{name}.json").write_text(json.dumps(data), encoding="utf-8", newline="")


def test_usage_exit_code_2(home):
    r = run_cli(home)
    assert r.returncode == 2
    assert "Usage: krellbot list" in r.stderr


def test_list_with_no_packs(home):
    r = run_cli(home, "list")
    assert r.returncode == 0
    assert "No packs installed." in r.stdout
    assert "The pack format is open." in r.stdout


def test_show_user_pack(home):
    write_pack(home, "mine", {"id": "mine", "public_label": "Mine", "rule": "My rule.", "timeframe": "1h"})
    r = run_cli(home, "show", "mine")
    assert r.returncode == 0
    assert "Mine" in r.stdout
    assert "My rule." in r.stdout
    assert "No order sent. This pack was written on this machine." in r.stdout


def test_run_user_pack_sends_no_order(home):
    write_pack(home, "mine", {"id": "mine", "public_label": "Mine"})
    r = run_cli(home, "run", "mine")
    assert r.returncode == 0
    assert "No order sent. A pack file is not an order." in r.stdout


def test_list_skips_invalid_pack_files(home):
    packs = home / ".krellbot" / "packs"
    packs.mkdir(parents=True)
    (packs / "broken.json").write_text("{not json", encoding="utf-8")
    write_pack(home, "ok", {"id": "ok", "public_label": "Okay"})
    r = run_cli(home, "list")
    assert r.returncode == 0
    assert "Okay" in r.stdout


def test_version_importable():
    import krellbot

    assert krellbot.__version__ == "0.9.0"


def test_version_flag_prints_package_version(home):
    result = run_cli(home, "--version")
    assert result.returncode == 0
    assert result.stdout.strip() == "0.9.0"
