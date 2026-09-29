"""M1R-FB — restore ``service install --dry-run`` after NS15.

NS15 rewrote ``krellbot.service.install`` around the owner file and
dropped the ``dry_run`` parameter, but the CLI call site still passes
``dry_run=`` — so both ``krellbot service install --dry-run`` and a
plain ``krellbot service install`` crash with ``TypeError``. This file
pins the restored behavior:

* ``--dry-run`` prints the platform unit (exactly as at b13c955),
  exits 0, and writes nothing — no unit, no owner file, no directories
  under ``write_root`` or ``home``. A dry run ignores an existing
  owner file (read-only, never refuses).
* A real install keeps the NS15 ownership semantics (owner conflict →
  rc 2, ``owner_conflict`` on stderr, nothing rewritten) and, on
  success, prints one ``installed <path>`` line (restored from
  b13c955).

The CLI (``python -m krellbot.cli service install``) is exercised in
subprocesses so the end-to-end wiring — argument parsing to
``install`` — is proven, not just the library call.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _run_service_cli(tmp: Path, *args: str) -> subprocess.CompletedProcess:
    """Spawn ``python -m krellbot.cli service ...`` against tmp homes.

    ``KRELLBOT_HOME`` points at ``tmp/home`` and ``HOME``/``USERPROFILE``
    at ``tmp`` so nothing under the real ``~`` is ever read or written.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["KRELLBOT_HOME"] = str(tmp / "home")
    env["HOME"] = str(tmp)
    env["USERPROFILE"] = str(tmp)
    env["KRELLBOT_API"] = "http://127.0.0.1:9"  # unroutable; fail fast on any accidental call
    return subprocess.run(
        [sys.executable, "-m", "krellbot.cli", "service", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=str(Path(__file__).resolve().parent.parent),
        timeout=60,
    )


def _platform_marker() -> str:
    """A string that must appear in dry-run stdout for sys.platform."""
    if sys.platform == "darwin":
        return "dev.krellbot.tick"
    if sys.platform.startswith("linux"):
        return "OnCalendar"
    if sys.platform == "win32":
        return "StartWhenAvailable"
    raise RuntimeError(f"unsupported test platform: {sys.platform}")


def _expected_unit_path(write_root: Path) -> Path:
    """Where install() drops the scheduler unit for sys.platform."""
    if sys.platform == "darwin":
        return write_root / "Library" / "LaunchAgents" / "dev.krellbot.tick.plist"
    if sys.platform.startswith("linux"):
        return write_root / ".config" / "systemd" / "user" / "krellbot-tick.timer"
    if sys.platform == "win32":
        return write_root / "Tasks" / "krellbot-tick.xml"
    raise RuntimeError(f"unsupported test platform: {sys.platform}")


def _owner_path(home: Path) -> Path:
    return home / "service" / "owners" / "default.owner"


def test_cli_service_install_dry_run_exits_zero_and_writes_nothing(tmp_path):
    """``service install --dry-run --root X`` exits 0, prints the unit,
    and writes nothing under the root or the home."""
    wr = tmp_path / "wr"

    proc = _run_service_cli(tmp_path, "install", "--dry-run", "--root", str(wr))

    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert _platform_marker() in proc.stdout
    # Nothing written under the injected write root...
    assert not wr.exists() or not any(wr.rglob("*")), "dry run wrote under write_root"
    # ...and no owner file (or owners directory) appeared under the home.
    assert not (tmp_path / "home" / "service" / "owners").exists()


def test_dry_run_ignores_existing_owner_file(home, capsys):
    """A dry run is read-only: an existing owner file does not refuse it
    (no owner_conflict) and its bytes are untouched."""
    from krellbot.service import install

    wr = home / "wr"
    owner = _owner_path(home)
    owner.parent.mkdir(parents=True, exist_ok=True)
    original = (
        b"# krellbot supervised execution owner\n"
        b"executable=/some/old/bin/krellbot\n"
        b"krellbot_home=/tmp/elsewhere\n"
        b"interval=hourly\n"
    )
    owner.write_bytes(original)

    rc = install(home, write_root=wr, dry_run=True)
    captured = capsys.readouterr()

    assert rc == 0
    assert "owner_conflict" not in captured.err
    assert owner.read_bytes() == original
    assert not wr.exists() or not any(wr.rglob("*"))


def test_real_install_prints_installed_line(home, capsys):
    """A successful real install prints one stdout line starting with
    ``installed `` naming the written unit path(s)."""
    from krellbot.service import install

    wr = home / "wr"
    rc = install(home, executable="/usr/local/bin/krellbot", write_root=wr)
    captured = capsys.readouterr()

    assert rc == 0
    installed_lines = [line for line in captured.out.splitlines() if line.startswith("installed ")]
    assert installed_lines, f"no 'installed ' line in stdout: {captured.out!r}"
    # The line names the unit path that was actually written.
    assert str(_expected_unit_path(wr)) in installed_lines[0]


def test_cli_service_install_real_writes_under_root(tmp_path):
    """``service install --root X --executable E`` (no --dry-run) writes
    the unit under the root and the owner file under the home; a second
    run hits the owner conflict (rc 2, owner_conflict on stderr)."""
    wr = tmp_path / "wr"

    first = _run_service_cli(
        tmp_path,
        "install",
        "--root",
        str(wr),
        "--executable",
        "/usr/local/bin/krellbot",
    )
    assert first.returncode == 0, f"stdout={first.stdout!r} stderr={first.stderr!r}"
    assert _expected_unit_path(wr).is_file()
    assert _owner_path(tmp_path / "home").is_file()
    assert any(line.startswith("installed ") for line in first.stdout.splitlines()), (
        f"no 'installed ' line in stdout: {first.stdout!r}"
    )

    second = _run_service_cli(
        tmp_path,
        "install",
        "--root",
        str(wr),
        "--executable",
        "/usr/local/bin/krellbot",
    )
    assert second.returncode == 2
    assert "owner_conflict" in second.stderr
