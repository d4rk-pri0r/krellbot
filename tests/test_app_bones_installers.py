"""App-bones installers (W1) — local install + click-to-launch tests.

Covers the three real deliverables of the slice:

1. ``scripts/installers/install-krellbot.sh`` — a POSIX per-user
   installer that copies the full one-dir payload into a user-owned
   location (``$XDG_DATA_HOME/Krellbot``), writes an XDG application
   entry plus a clickable Desktop launcher, and refuses unsafe
   source/destination nesting, symlink escapes, and missing payloads.
   Paths containing spaces must work. User data (``~/.krellbot`` /
   ``KRELLBOT_HOME``) must be preserved untouched.

2. ``scripts/installers/Install-Krellbot.cmd`` / ``.ps1`` — content
   review only on Linux. These are Windows-native scripts; executing
   them here and calling it "verification" would be dishonest. The
   tests pin the safety-relevant content (no downloads, no elevation,
   no execution-policy override, LOCALAPPDATA destination, quoted
   paths) and label native execution NOT RUN.

3. The staged artifact — every freeze output carries the installer
   helpers plus the runtime resource packages the installed app needs
   (see tests/test_f03_freeze_shell.py for the build-side checks; here
   we assert the helper files ship next to the payload pattern).

Every filesystem-touching test runs under pytest's private ``tmp_path``
(a real per-test scratch directory), never system ``/tmp`` fixtures.
The Linux installer is exercised for real via ``bash`` subprocesses
against fabricated one-dir payloads, including paths with spaces.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLERS_DIR = REPO_ROOT / "scripts" / "installers"
LINUX_INSTALLER = INSTALLERS_DIR / "install-krellbot.sh"
WINDOWS_CMD = INSTALLERS_DIR / "Install-Krellbot.cmd"
WINDOWS_PS1 = INSTALLERS_DIR / "Install-Krellbot.ps1"
INSTALL_TXT = INSTALLERS_DIR / "INSTALL.txt"

# The success-path installer checks inspect POSIX ``mode & 0o111`` bits after
# ``chmod 0o755`` and assert that the installed launcher binary is executable
# on the host. Windows NTFS metadata does not honor POSIX x-bits, and the
# companion .cmd/.ps1 install path is exercised in CI on Windows runners as a
# separate, native ``Install-Krellbot.cmd`` job — never through this POSIX
# helper. The refusal-path tests below keep running on every platform that
# can find bash (Linux + macOS + Windows with bash on PATH) so the negative
# coverage does not silently disappear off-host.
IS_LINUX = sys.platform.startswith("linux")


def _bash() -> str:
    exe = shutil.which("bash")
    if exe is None:
        pytest.skip("bash is required to exercise the Linux installer")
    return exe


def _make_payload(dest: Path) -> Path:
    """Fabricate a minimal one-dir frozen payload (no PyInstaller needed).

    Includes a copy of the real installer helper so the payload mirrors
    an extracted release archive (helper beside the executable).
    """
    dest.mkdir(parents=True, exist_ok=True)
    launcher = dest / "krellbot"
    launcher.write_text(
        "#!/bin/sh\nprintf 'Workstation running at http://127.0.0.1:44000/\\n'\nwhile [ 1 ]; do sleep 1; done\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    internal = dest / "_internal"
    internal.mkdir()
    (internal / "runtime.marker").write_text("payload\n", encoding="utf-8")
    helper = dest / "install-krellbot.sh"
    shutil.copyfile(LINUX_INSTALLER, helper)
    helper.chmod(0o755)
    return dest


def _run_installer(
    installer: Path,
    *,
    home: Path,
    xdg_data: Path,
    xdg_config: Path | None = None,
    args: list[str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    """Run install-krellbot.sh under a fully private HOME/XDG scratch."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "XDG_DATA_HOME": str(xdg_data),
        "LANG": "C.UTF-8",
        "TMPDIR": str(home),
    }
    if xdg_config is not None:
        env["XDG_CONFIG_HOME"] = str(xdg_config)
    argv = [_bash(), str(installer), *(args or [])]
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd or installer.parent),
        env=env,
        timeout=120,
    )


# ---------------------------------------------------------------------------
# Linux installer — happy paths
# ---------------------------------------------------------------------------


def test_linux_installer_installs_payload_with_spaces_in_paths(tmp_path: Path) -> None:
    """A source path AND install path containing spaces install cleanly."""
    _bash()
    if not IS_LINUX:
        pytest.skip("POSIX installer x-bit check (mode & 0o111) is Linux-only")
    home = tmp_path / "home dir"
    home.mkdir()
    xdg_data = home / ".local" / "share"

    src_root = tmp_path / "extracted krellbot"
    payload = _make_payload(src_root / "krellbot")

    proc = _run_installer(payload / "install-krellbot.sh", home=home, xdg_data=xdg_data, xdg_config=home / ".config")
    assert proc.returncode == 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"

    installed = xdg_data / "Krellbot"
    assert (installed / "krellbot").is_file()
    assert (installed / "_internal" / "runtime.marker").is_file()
    mode = (installed / "krellbot").stat().st_mode & 0o777
    assert mode & 0o111, f"installed launcher must stay executable; mode={mode:o}"

    desktop = xdg_data / "applications" / "krellbot.desktop"
    assert desktop.is_file(), proc.stdout
    content = desktop.read_text(encoding="utf-8")
    assert f'Exec="{installed / "krellbot"}"' in content, content
    assert f"Path={installed}" in content, content
    assert "Terminal=" in content, content


def test_linux_installer_explicit_dest_with_spaces(tmp_path: Path) -> None:
    """An explicit DESTDIR argument with spaces is honoured verbatim."""
    _bash()
    if not IS_LINUX:
        pytest.skip("POSIX installer behavior under private HOME is Linux-only")
    home = tmp_path / "home"
    home.mkdir()
    xdg_data = home / ".local" / "share"

    payload = _make_payload(tmp_path / "src" / "krellbot")
    dest = tmp_path / "apps" / "Krell bot install"

    proc = _run_installer(
        payload / "install-krellbot.sh",
        home=home,
        xdg_data=xdg_data,
        xdg_config=home / ".config",
        args=[str(dest)],
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    assert (dest / "krellbot").is_file()
    assert (dest / "_internal" / "runtime.marker").is_file()

    desktop = xdg_data / "applications" / "krellbot.desktop"
    content = desktop.read_text(encoding="utf-8")
    assert f'Exec="{dest / "krellbot"}"' in content, content


def test_linux_installer_creates_clickable_desktop_launcher(tmp_path: Path) -> None:
    """When the user has a real XDG Desktop directory (declared through
    user-dirs.dirs), a clickable ``Launch-Krellbot`` file lands there."""
    _bash()
    if not IS_LINUX:
        pytest.skip("XDG desktop launcher creation is a Linux/POSIX behaviour")
    home = tmp_path / "home"
    home.mkdir()
    xdg_config = home / ".config"
    desktop_dir = home / "Desk top"
    desktop_dir.mkdir(parents=True)
    (xdg_config).mkdir(parents=True, exist_ok=True)
    (xdg_config / "user-dirs.dirs").write_text('XDG_DESKTOP_DIR="$HOME/Desk top"\n', encoding="utf-8")

    xdg_data = home / ".local" / "share"
    payload = _make_payload(tmp_path / "src" / "krellbot")

    proc = _run_installer(payload / "install-krellbot.sh", home=home, xdg_data=xdg_data, xdg_config=xdg_config)
    assert proc.returncode == 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"

    launch = desktop_dir / "Launch-Krellbot.desktop"
    assert launch.is_file(), proc.stdout
    content = launch.read_text(encoding="utf-8")
    assert "Type=Application" in content
    assert "Name=Launch Krellbot" in content
    assert f'Exec="{xdg_data / "Krellbot" / "krellbot"}"' in content, content


def test_linux_installer_preserves_user_data_and_reinstalls(tmp_path: Path) -> None:
    """Pre-existing user state survives both a fresh install and a
    reinstall over the installed program."""
    _bash()
    if not IS_LINUX:
        pytest.skip("User-data preservation under the Linux installer is Linux-only")
    home = tmp_path / "home"
    home.mkdir()
    xdg_data = home / ".local" / "share"

    krellbot_home = home / ".krellbot"
    krellbot_home.mkdir()
    marker = krellbot_home / "state.json"
    marker.write_text('{"keep": true}\n', encoding="utf-8")
    packs = krellbot_home / "packs"
    packs.mkdir()
    (packs / "mine.json").write_text('{"id": "mine"}\n', encoding="utf-8")

    payload = _make_payload(tmp_path / "src" / "krellbot")
    installer = payload / "install-krellbot.sh"

    first = _run_installer(installer, home=home, xdg_data=xdg_data, xdg_config=home / ".config")
    assert first.returncode == 0, first.stderr

    # Simulate the program writing user state after install.
    installed_state = xdg_data / "Krellbot" / "_internal" / "runtime.marker"
    assert installed_state.is_file()
    installed_state.write_text("program file changed by update\n", encoding="utf-8")

    # Reinstall: program files replaced, user data untouched.
    second = _run_installer(installer, home=home, xdg_data=xdg_data, xdg_config=home / ".config")
    assert second.returncode == 0, second.stderr
    assert marker.read_text(encoding="utf-8") == '{"keep": true}\n'
    assert (packs / "mine.json").is_file()
    assert installed_state.read_text(encoding="utf-8") == "payload\n"


# ---------------------------------------------------------------------------
# Linux installer — refusals
# ---------------------------------------------------------------------------


def test_linux_installer_refuses_missing_payload(tmp_path: Path) -> None:
    _bash()
    home = tmp_path / "home"
    home.mkdir()
    empty = tmp_path / "not a payload"
    empty.mkdir()
    proc = _run_installer(empty / "install-krellbot.sh", home=home, xdg_data=home / ".local" / "share")
    # The helper itself is absent; the refusal must come from the real
    # script when its payload checks fail, so run the REAL installer from
    # a directory without a payload beside it.
    real = LINUX_INSTALLER
    proc = subprocess.run(
        [_bash(), str(real)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(empty),
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
        },
        timeout=60,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "refused" in (proc.stdout + proc.stderr).lower()


def test_linux_installer_refuses_destination_inside_source(tmp_path: Path) -> None:
    _bash()
    home = tmp_path / "home"
    home.mkdir()
    payload = _make_payload(tmp_path / "src" / "krellbot")
    nested = payload / "sub install"
    nested.mkdir()
    proc = _run_installer(
        payload / "install-krellbot.sh",
        home=home,
        xdg_data=home / ".local" / "share",
        xdg_config=home / ".config",
        args=[str(nested)],
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "refused" in (proc.stdout + proc.stderr).lower()
    assert not (nested / "krellbot").exists()


def test_linux_installer_refuses_symlink_destination(tmp_path: Path) -> None:
    _bash()
    home = tmp_path / "home"
    home.mkdir()
    payload = _make_payload(tmp_path / "src" / "krellbot")

    outside = tmp_path / "outside target"
    outside.mkdir()
    link_parent = tmp_path / "link parent"
    link_parent.mkdir()
    dest = link_parent / "Krellbot"
    os.symlink(outside, dest)

    proc = _run_installer(
        payload / "install-krellbot.sh",
        home=home,
        xdg_data=home / ".local" / "share",
        xdg_config=home / ".config",
        args=[str(dest)],
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "refused" in (proc.stdout + proc.stderr).lower()
    # Nothing was written through the link.
    assert list(outside.iterdir()) == []


def test_linux_installer_usage_for_bad_arguments(tmp_path: Path) -> None:
    _bash()
    home = tmp_path / "home"
    home.mkdir()
    payload = _make_payload(tmp_path / "src" / "krellbot")
    proc = _run_installer(
        payload / "install-krellbot.sh",
        home=home,
        xdg_data=home / ".local" / "share",
        args=["a", "b", "c"],
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_linux_installer_help_flag_is_usage(tmp_path: Path) -> None:
    _bash()
    home = tmp_path / "home"
    home.mkdir()
    payload = _make_payload(tmp_path / "src" / "krellbot")
    proc = _run_installer(
        payload / "install-krellbot.sh",
        home=home,
        xdg_data=home / ".local" / "share",
        args=["--help"],
    )
    if IS_LINUX:
        assert proc.returncode == 2, proc.stdout + proc.stderr
        assert "Usage" in proc.stderr
    else:
        # Native platform refusal precedes help processing. Preserve that
        # refusal instead of requiring Linux behaviour on another host.
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "this installer is for Linux" in proc.stderr
        assert "Nothing has been changed" in proc.stderr
        assert not (home / ".local" / "share" / "Krellbot").exists()


# ---------------------------------------------------------------------------
# Static / packaging checks
# ---------------------------------------------------------------------------


def test_linux_installer_passes_bash_n() -> None:
    """The shipped helper must at least parse under bash."""
    bash = _bash()
    proc = subprocess.run([bash, "-n", str(LINUX_INSTALLER)], capture_output=True, text=True, check=False, timeout=60)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    "name",
    ["Install-Krellbot.cmd", "Install-Krellbot.ps1", "install-krellbot.sh", "INSTALL.txt"],
)
def test_freeze_stages_every_installer_helper(name: str) -> None:
    """The helpers exist in the repo at the exact paths freeze.py stages."""
    assert (INSTALLERS_DIR / name).is_file(), name


def test_windows_cmd_content_safety() -> None:
    """Content review of the Windows entry point (native run NOT RUN here).

    Pins: invokes the companion .ps1 from the extracted artifact, never
    downloads, never elevates, never overrides the execution policy, and
    quotes paths so spaces survive.
    """
    text = WINDOWS_CMD.read_text(encoding="utf-8", errors="replace")
    low = text.lower()
    assert "install-krellbot.ps1" in low
    assert "-file" in low
    assert "invoke-webrequest" not in low
    assert "curl " not in low
    assert "wget" not in low
    assert "runas" not in low
    assert "start-process -verb" not in low
    # No execution-policy override shipped by the installer itself.
    assert "-executionpolicy" not in low
    assert "%~dp0" in text  # resolves beside the .cmd, spaces-safe quoting follows


def test_windows_ps1_content_safety() -> None:
    """Content review of the Windows installer script (native run NOT RUN).

    Pins: per-user LOCALAPPDATA destination, payload presence checks,
    nesting + reparse-point refusals, quoted shortcut paths with a safe
    working directory, and no downloads/elevation/policy/secrets.
    """
    text = WINDOWS_PS1.read_text(encoding="utf-8", errors="replace")
    low = text.lower()
    assert "localapplicationdata" in low
    assert "krellbot.exe" in low
    assert "_internal" in low
    assert "reparsepoint" in low
    assert "workingdirectory" in low
    assert "invoke-webrequest" not in low
    assert "downloadfile" not in low
    assert "start-bitstransfer" not in low
    assert "-verb runas" not in low
    assert "set-executionpolicy" not in low
    # The real Windows installation failed with robocopy exit 16 when
    # the job-summary flag was misspelled as /NYS. Native CI also runs
    # this entire installer against the actual frozen payload.
    assert "/njs" in low
    assert "/nys" not in low
    # Never writes the user's data home: no path construction targeting
    # it (mentioning it in a "we never touch this" comment is fine).
    for forbidden in ("krellbot_home =", "$env:krellbot_home", "join-path $home", "join-path $env:home"):
        assert forbidden not in low, forbidden


def test_install_txt_documents_unsigned_and_launch_stop() -> None:
    """INSTALL.txt must state the unsigned status honestly and explain
    launch/stop without requiring source, Python, or npm."""
    text = INSTALL_TXT.read_text(encoding="utf-8")
    low = text.lower()
    assert "not signed" in low or "unsigned" in low
    assert "ctrl+c" in low
    assert "install-krellbot.cmd" in low
    assert "install-krellbot.sh" in low
    assert "python" in low  # used in the "you do NOT need Python" sense
    assert "no developer tools" in low or "development tooling" in low
