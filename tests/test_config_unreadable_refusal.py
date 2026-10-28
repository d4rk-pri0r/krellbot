"""An unreadable `$KRELLBOT_HOME/config.json` is refused, never a raw traceback.

BASE on main (b592ed3): `krellbot status` and `krellbot doctor` crashed with a
raw PermissionError traceback when config.json was chmod 000, and a raw
IsADirectoryError when config.json was a directory — both rc1. These tests are
the regression pin: after the `load_config` fix, both surfaces must print the
typed refusal naming config.json (rc1, no traceback), while missing / torn /
non-dict config keeps the silent empty-Config fallback (rc0) and healthy
load/save stays byte-identical. The CLI runs in real subprocesses with a tmp
KRELLBOT_HOME, the fake keyring, no network, and no live flags.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.config import ArmedPack, Config, load_config, save_config

_IS_POSIX_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
_ON_WINDOWS = sys.platform == "win32"


def run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["KRELLBOT_API"] = "http://127.0.0.1:9"  # unroutable; any accidental call fails fast
    env["KRELLBOT_HOME"] = str(home / "krellbot-home")
    return subprocess.run(
        [sys.executable, "-m", "krellbot.cli", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )


def kh(home: Path) -> Path:
    krellbot_home = home / "krellbot-home"
    krellbot_home.mkdir(parents=True, exist_ok=True)
    return krellbot_home


def write_config(krellbot_home: Path, payload) -> None:
    (krellbot_home / "config.json").write_text(payload, encoding="utf-8")


def assert_refusal(proc: subprocess.CompletedProcess, exc_name: str) -> None:
    assert proc.returncode == 1
    assert "config.json" in proc.stderr
    assert "config load refused" in proc.stderr
    assert exc_name in proc.stderr
    assert "Traceback" not in proc.stderr


# ---- typed refusal: unreadable config.json (chmod 000) ----------------------


@pytest.mark.skipif(_IS_POSIX_ROOT or _ON_WINDOWS, reason="chmod 000 only forbids reads for non-root POSIX")
def test_status_unreadable_config_refusal(tmp_path):
    krellbot_home = kh(tmp_path)
    write_config(krellbot_home, '{"armed": [], "live_first_armed": false}')
    os.chmod(krellbot_home / "config.json", 0o000)
    proc = run_cli(tmp_path, "status")
    assert_refusal(proc, "PermissionError")


@pytest.mark.skipif(_IS_POSIX_ROOT or _ON_WINDOWS, reason="chmod 000 only forbids reads for non-root POSIX")
def test_doctor_unreadable_config_refusal(tmp_path):
    krellbot_home = kh(tmp_path)
    write_config(krellbot_home, '{"armed": [], "live_first_armed": false}')
    os.chmod(krellbot_home / "config.json", 0o000)
    proc = run_cli(tmp_path, "doctor", "--skip-clock")
    assert_refusal(proc, "PermissionError")


# ---- typed refusal: config.json is a directory -------------------------------


def test_status_config_directory_refusal(tmp_path):
    krellbot_home = kh(tmp_path)
    (krellbot_home / "config.json").mkdir()
    proc = run_cli(tmp_path, "status")
    exc_name = "IsADirectoryError" if not _ON_WINDOWS else "PermissionError"
    assert_refusal(proc, exc_name)


def test_doctor_config_directory_refusal(tmp_path):
    krellbot_home = kh(tmp_path)
    (krellbot_home / "config.json").mkdir()
    proc = run_cli(tmp_path, "doctor", "--skip-clock")
    exc_name = "IsADirectoryError" if not _ON_WINDOWS else "PermissionError"
    assert_refusal(proc, exc_name)


# ---- load_config-level typed refusal -----------------------------------------


@pytest.mark.skipif(_IS_POSIX_ROOT or _ON_WINDOWS, reason="chmod 000 only forbids reads for non-root POSIX")
def test_load_config_unreadable_raises_system_exit(tmp_path, capsys):
    krellbot_home = kh(tmp_path)
    write_config(krellbot_home, '{"armed": [], "live_first_armed": false}')
    os.chmod(krellbot_home / "config.json", 0o000)
    with pytest.raises(SystemExit) as exc_info:
        load_config(krellbot_home)
    assert exc_info.value.code == 1
    stderr = capsys.readouterr().err
    assert "config.json" in stderr
    assert "config load refused" in stderr
    assert "PermissionError" in stderr


def test_load_config_directory_raises_system_exit(tmp_path, capsys):
    krellbot_home = kh(tmp_path)
    (krellbot_home / "config.json").mkdir()
    with pytest.raises(SystemExit) as exc_info:
        load_config(krellbot_home)
    assert exc_info.value.code == 1
    stderr = capsys.readouterr().err
    assert "config.json" in stderr
    assert "config load refused" in stderr


# ---- controls: surfaces that do not read config.json stay rc0 ----------------


@pytest.mark.skipif(_IS_POSIX_ROOT or _ON_WINDOWS, reason="chmod 000 only forbids reads for non-root POSIX")
def test_controls_unaffected_by_unreadable_config(tmp_path):
    krellbot_home = kh(tmp_path)
    write_config(krellbot_home, '{"armed": [], "live_first_armed": false}')
    os.chmod(krellbot_home / "config.json", 0o000)
    journal = run_cli(tmp_path, "journal", "--tail", "2")
    assert journal.returncode == 0
    assert "no journal" in journal.stdout
    telemetry = run_cli(tmp_path, "telemetry", "show")
    assert telemetry.returncode == 0
    version = run_cli(tmp_path, "--version")
    assert version.returncode == 0
    listed = run_cli(tmp_path, "list")
    assert listed.returncode == 0


# ---- silent empty-Config fallback stays byte-identical (rc0) -----------------


@pytest.mark.parametrize("payload", ['{"armed": [', "[1, 2]", '"nope"', "null"])
def test_torn_and_nondict_config_silent_fallback(tmp_path, payload):
    krellbot_home = kh(tmp_path)
    write_config(krellbot_home, payload)
    status = run_cli(tmp_path, "status")
    assert status.returncode == 0
    assert status.stdout == "no armed packs\n"
    assert status.stderr == ""
    doctor = run_cli(tmp_path, "doctor", "--skip-clock")
    assert doctor.returncode in {0, 1}  # doctor reports health; it must not crash
    assert "Traceback" not in doctor.stderr
    assert "config load refused" not in doctor.stderr
    assert load_config(krellbot_home) == Config()


def test_missing_config_keeps_empty_fallback(tmp_path):
    krellbot_home = kh(tmp_path)
    assert load_config(krellbot_home) == Config()
    status = run_cli(tmp_path, "status")
    assert status.returncode == 0
    assert status.stdout == "no armed packs\n"


# ---- healthy config load/save stays byte-identical ---------------------------


def _healthy_config() -> Config:
    return Config(
        armed=[
            ArmedPack(
                pack_path="/tmp/packs/breakout.json",
                pack_sha256="a" * 64,
                pack_id="breakout",
                pack_version="1.2.3",
                venue="kraken",
                pair="XBT/USD",
                cap=Decimal("25"),
                stop=Decimal("10500.5"),
                mode="paper",
                starting_cash=Decimal("10000.00"),
                requires_license=False,
                armed_at_ts=1_700_000_000,
                owned_qty=Decimal("0.5"),
                pending_version="1.3.0",
                entries_paused=True,
            )
        ],
        live_first_armed=True,
    )


def test_healthy_config_round_trip_byte_identical(tmp_path):
    first = tmp_path / "h1"
    second = tmp_path / "h2"
    first.mkdir()
    second.mkdir()
    save_config(first, _healthy_config())
    loaded = load_config(first)
    assert loaded == _healthy_config()
    save_config(second, loaded)
    assert (first / "config.json").read_bytes() == (second / "config.json").read_bytes()
    payload = json.loads((first / "config.json").read_text(encoding="utf-8"))
    assert payload == json.loads((second / "config.json").read_text(encoding="utf-8"))
    assert payload["live_first_armed"] is True
    assert payload["armed"][0]["cap"] == "25"


def test_healthy_status_prints_armed_line(tmp_path):
    krellbot_home = kh(tmp_path)
    save_config(krellbot_home, _healthy_config())
    proc = run_cli(tmp_path, "status")
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert proc.stdout == "breakout 1.2.3 kraken XBT/USD cap=25 stop=10500.5 mode=paper requires_license=False\n"
