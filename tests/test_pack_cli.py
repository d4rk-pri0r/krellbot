"""CLI tests for the new `lint` command and re-wired list/show.

We shell out to the krellbot entrypoint with HOME/KRELLBOT_HOME pointed at a
temp dir, the same pattern as test_legacy_cli.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["KRELLBOT_API"] = "http://127.0.0.1:9"
    env["KRELLBOT_HOME"] = str(home)
    env["PYTHONPATH"] = str(REPO / "src")
    return subprocess.run(
        [sys.executable, "-m", "krellbot.cli", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )


def write_pack(home: Path, name: str, data: dict) -> Path:
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    path = packs / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8", newline="")
    return path


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path


def test_lint_valid_dsl_pack_exits_0(home):
    pack = json.loads((REPO / "tests" / "fixtures" / "packs" / "valid.json").read_text())
    path = write_pack(home, "valid", pack)
    r = run_cli(home, "lint", str(path))
    assert r.returncode == 0, f"stderr: {r.stderr}"


def test_lint_bad_short_exits_1_and_names_field(home):
    pack = json.loads((REPO / "tests" / "fixtures" / "packs" / "bad_short.json").read_text())
    path = write_pack(home, "bad_short", pack)
    r = run_cli(home, "lint", str(path))
    assert r.returncode == 1
    assert "short" in r.stderr


def test_lint_legacy_pack_exits_0(home):
    """A file with id+public_label and no schema_version is legacy: not runnable."""
    pack = {
        "id": "legacy_one",
        "public_label": "Old",
        "rule": "Plain English.",
        "timeframe": "1h",
    }
    path = write_pack(home, "legacy_one", pack)
    r = run_cli(home, "lint", str(path))
    assert r.returncode == 0, f"stderr: {r.stderr}"


def test_legacy_pack_lists_as_not_runnable(home):
    """`krellbot list` prints public_label AND the legacy marker for legacy packs."""
    pack = {
        "id": "old",
        "public_label": "Old Reliable",
        "rule": "Do the thing.",
        "timeframe": "1h",
    }
    write_pack(home, "old", pack)
    r = run_cli(home, "list")
    assert r.returncode == 0
    assert "Old Reliable" in r.stdout
    assert "legacy: not runnable" in r.stdout


def test_label_with_ansi_is_sanitized_on_list(home):
    """An ANSI CSI escape in a DSL pack's label must be stripped before printing."""
    pack = json.loads((REPO / "tests" / "fixtures" / "packs" / "valid.json").read_text())
    pack["label"] = "\x1b[31mREDACTED\x1b[0m trend"
    write_pack(home, "ansi", pack)
    r = run_cli(home, "list")
    assert r.returncode == 0
    assert "\x1b[31m" not in r.stdout
    assert "REDACTED" in r.stdout  # the visible text remains


def test_list_shows_dsl_pack_label(home):
    pack = json.loads((REPO / "tests" / "fixtures" / "packs" / "valid.json").read_text())
    write_pack(home, "dsl_one", pack)
    r = run_cli(home, "list")
    assert r.returncode == 0
    assert "trend" in r.stdout.lower() or "valid" in r.stdout.lower()  # label or id printed


def test_list_uses_krellbot_home_not_os_home(tmp_path):
    """A pack under $KRELLBOT_HOME/packs lists even when that is not ~/.krellbot."""
    os_home = tmp_path / "os-home"
    kb_home = tmp_path / "kb-home"
    os_home.mkdir()
    kb_home.mkdir()
    decoy = os_home / ".krellbot" / "packs"
    decoy.mkdir(parents=True)
    (decoy / "decoy.json").write_text(
        json.dumps({"id": "decoy", "public_label": "Do not list me"}),
        encoding="utf-8",
    )
    pack = json.loads((REPO / "tests" / "fixtures" / "packs" / "valid.json").read_text())
    write_pack(kb_home, "real", pack)
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["HOME"] = str(os_home)
    env["USERPROFILE"] = str(os_home)
    env["KRELLBOT_HOME"] = str(kb_home)
    env["KRELLBOT_API"] = "http://127.0.0.1:9"
    env["PYTHONPATH"] = str(REPO / "src")
    result = subprocess.run(
        [sys.executable, "-m", "krellbot.cli", "list"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "Do not list me" not in result.stdout
    assert "Trend" in result.stdout or "trend" in result.stdout.lower()


def test_show_legacy_pack_still_works(home):
    pack = {
        "id": "old",
        "public_label": "Old Reliable",
        "rule": "Stay calm.",
        "timeframe": "1h",
    }
    write_pack(home, "old", pack)
    r = run_cli(home, "show", "old")
    assert r.returncode == 0
    assert "Old Reliable" in r.stdout
    assert "legacy: not runnable" in r.stdout
