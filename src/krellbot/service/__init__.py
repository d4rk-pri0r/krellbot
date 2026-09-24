"""`krellbot service install|uninstall [--dry-run]`.

Install renders the scheduler unit for the current platform and writes it
under an injected write_root. The render layer (`render.py`) is platform-
agnostic; this module only knows where each unit goes.

Install without `--dry-run` writes only under the write_root argument. The
CLI passes `Path.home()` for a real install or a test directory for a dry
run; tests never call the write path against the real home.

Uninstall deletes only the unit files it wrote. The names are fixed per
platform so there is no ambiguity (the brief: "deletes only the unit files
it wrote").
"""

from __future__ import annotations

import sys
from pathlib import Path

from krellbot import paths as kb_paths

from . import render

LAUNCHD_LABEL = "dev.krellbot.tick"
LAUNCHD_FILENAME = f"{LAUNCHD_LABEL}.plist"


def launchd_unit_path(home: Path) -> Path:
    """Where the macOS plist is installed relative to the user's home."""
    return home / "Library" / "LaunchAgents" / LAUNCHD_FILENAME


def systemd_unit_dir(home: Path) -> Path:
    """Where Linux systemd user units live, relative to the user's home."""
    return home / ".config" / "systemd" / "user"


def windows_unit_path(home: Path) -> Path:
    """Where the Windows task XML is dropped, relative to the user's home."""
    return home / "Tasks" / "krellbot-tick.xml"


def _resolve_executable(explicit: str | None) -> str:
    """Return the executable path passed by the caller.

    Renderers take the absolute path. We do not call Path.home() or read the
    keyring; the caller passes the path explicitly. The CLI default is the
    current interpreter (so `python -m krellbot` and `krellbot` both work
    under the test runner).
    """
    if explicit:
        return explicit
    return sys.executable


def install(
    *,
    executable: str | None = None,
    home: Path | None = None,
    write_root: Path | None = None,
    dry_run: bool,
) -> int:
    """Install (or dry-run-print) the scheduler unit for sys.platform.

    With `dry_run=True`, prints the unit to stdout and writes nothing. With
    `dry_run=False`, writes only under `write_root` (which the caller must
    supply). Returns 0 on success, 2 on bad arguments, 1 on unsupported
    platform.
    """
    home = Path(home) if home is not None else kb_paths.home()
    executable_path = _resolve_executable(executable)

    if sys.platform == "darwin":
        body = render.render_launchd(executable_path, home)
        if dry_run:
            sys.stdout.buffer.write(body)
            return 0
        if write_root is None:
            print("service install requires an injected write root", file=sys.stderr)
            return 2
        target = write_root / "Library" / "LaunchAgents" / LAUNCHD_FILENAME
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        print(f"installed {target}")
        return 0

    if sys.platform.startswith("linux"):
        units = render.render_systemd(executable_path, home)
        if dry_run:
            for name, body in units.items():
                sys.stdout.buffer.write(b"=== " + name.encode("utf-8") + b" ===\n")
                sys.stdout.buffer.write(body)
                sys.stdout.buffer.write(b"\n")
            return 0
        if write_root is None:
            print("service install requires an injected write root", file=sys.stderr)
            return 2
        d = write_root / ".config" / "systemd" / "user"
        d.mkdir(parents=True, exist_ok=True)
        for name, body in units.items():
            (d / name).write_bytes(body)
        print(f"installed {d / 'krellbot-tick.timer'} and {d / 'krellbot-tick.service'}")
        return 0

    if sys.platform == "win32":
        body = render.render_windows(executable_path, home)
        if dry_run:
            sys.stdout.buffer.write(body)
            return 0
        if write_root is None:
            print("service install requires an injected write root", file=sys.stderr)
            return 2
        target = write_root / "Tasks" / "krellbot-tick.xml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        print(f"installed {target}")
        return 0

    print(f"unsupported platform: {sys.platform}", file=sys.stderr)
    return 1


def uninstall(*, home: Path | None = None, write_root: Path) -> int:
    """Delete only the unit files this module wrote.

    Returns 0 on success or no-op, 1 on unsupported platform.
    """
    home = Path(home) if home is not None else kb_paths.home()

    if sys.platform == "darwin":
        target = write_root / "Library" / "LaunchAgents" / LAUNCHD_FILENAME
        if target.exists():
            target.unlink()
        print(f"uninstalled {target}")
        return 0
    if sys.platform.startswith("linux"):
        d = write_root / ".config" / "systemd" / "user"
        for name in ("krellbot-tick.timer", "krellbot-tick.service"):
            p = d / name
            if p.exists():
                p.unlink()
        print(f"uninstalled from {d}")
        return 0
    if sys.platform == "win32":
        target = write_root / "Tasks" / "krellbot-tick.xml"
        if target.exists():
            target.unlink()
        print(f"uninstalled {target}")
        return 0
    print(f"unsupported platform: {sys.platform}", file=sys.stderr)
    return 1
