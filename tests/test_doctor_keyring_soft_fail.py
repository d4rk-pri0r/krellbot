"""Doctor soft-fails when the OS keyring backend is absent.

On a no-keyring box, ``keyring.backends.fail.Keyring`` raises
``keyring.errors.NoKeyringError`` on ``get_password``. Doctor must report
warning JSON instead of tracebacking. Pins the CLI path
``krellbot doctor --json --skip-clock`` as well as ``doctor.run``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import keyring
import keyring.backends.fail as fail_backend


def test_doctor_run_reports_warning_json_when_keyring_raises_no_keyring_error(home, monkeypatch):
    """``doctor.run(..., as_json=True)`` returns warning JSON, not a traceback."""
    keyring.set_keyring(fail_backend.Keyring())
    # Ensure secrets.get cannot bypass keyring via env credentials.
    for venue in ("KRAKEN", "COINBASE"):
        monkeypatch.delenv(f"KRELLBOT_{venue}_KEY", raising=False)
        monkeypatch.delenv(f"KRELLBOT_{venue}_SECRET", raising=False)
        monkeypatch.delenv(f"KRELLBOT_{venue}_KEYFILE", raising=False)

    from krellbot import doctor

    if not home.is_dir():
        home.mkdir(parents=True)
    if sys.platform != "win32":
        home.chmod(0o700)

    rc, body = doctor.run(
        home=home,
        write_root=home,
        time_source=None,
        clock=lambda: 1_000,
        as_json=True,
    )
    data = json.loads(body)
    assert isinstance(data, dict)
    assert "warnings" in data
    assert isinstance(data["warnings"], list)
    assert len(data["warnings"]) >= 1
    assert data["ok"] is False
    assert rc == 1
    assert data["install_ready"] is False
    # Fail backend is classified as non-persistent, or keys reported absent.
    joined = " ".join(str(w) for w in data["warnings"]).lower()
    assert "keychain" in joined or "key not stored" in joined


def test_doctor_cli_json_skip_clock_no_keyring_no_traceback(tmp_path, monkeypatch):
    """``krellbot doctor --json --skip-clock`` exits with warning JSON, no traceback."""
    home = tmp_path / "krellbot-home"
    home.mkdir()
    if sys.platform != "win32":
        home.chmod(0o700)

    env = os.environ.copy()
    env["KRELLBOT_HOME"] = str(home)
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.fail.Keyring"
    for venue in ("KRAKEN", "COINBASE"):
        env.pop(f"KRELLBOT_{venue}_KEY", None)
        env.pop(f"KRELLBOT_{venue}_SECRET", None)
        env.pop(f"KRELLBOT_{venue}_KEYFILE", None)

    proc = subprocess.run(
        [sys.executable, "-m", "krellbot.cli", "doctor", "--json", "--skip-clock"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(Path(__file__).resolve().parents[1]),
        check=False,
    )
    assert "NoKeyringError" not in proc.stderr, proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    data = json.loads(proc.stdout)
    assert isinstance(data.get("warnings"), list)
    assert data["ok"] is False
    assert len(data["warnings"]) >= 1
    assert any("keychain" in str(w).lower() or "key not stored" in str(w).lower() for w in data["warnings"])
