"""`krellbot service install|uninstall`.

Owns the supervised tick execution. ``install`` writes two artifacts:

1. The platform scheduler unit (launchd plist on macOS, systemd user
   timer+service on Linux, Windows task XML) under ``write_root``. The
   unit fires the tick on an hourly cadence and sets ``KRELLBOT_HOME``
   in its environment block so the supervised process finds the data
   home without an interactive shell.
2. A per-venue owner file under ``<home>/service/owners/<venue>.owner``
   that records the executable path, the ``KRELLBOT_HOME`` value, and
   an explicit hourly interval marker. The owner file is the
   ownership marker: a second ``install`` for the same venue (same
   home) while the file exists is refused with exit code 2 and
   ``owner_conflict`` on stderr, and neither the unit file nor the
   owner file is rewritten.

The runner module (``krellbot.service.runner``) is the stable entry
point the scheduler unit invokes. ``install`` imports it so a broken
runner fails the install, not the scheduled tick three hours later.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import render, runner  # noqa: F401 — runner must be importable at install-time

LAUNCHD_LABEL = "dev.krellbot.tick"
LAUNCHD_FILENAME = f"{LAUNCHD_LABEL}.plist"

# Per-venue owner filename for the default supervised install. The
# supervised tick is a single per-user context, so the default venue
# is the only one this leaf writes. Different homes are different
# venues: each home's owner file lives at its own
# ``<home>/service/owners/default.owner`` and conflicts only with
# another install in the same home.
DEFAULT_VENUE = "default"


def launchd_unit_path(home: Path) -> Path:
    """Where the macOS plist is installed relative to the user's home."""
    return home / "Library" / "LaunchAgents" / LAUNCHD_FILENAME


def systemd_unit_dir(home: Path) -> Path:
    """Where Linux systemd user units live, relative to the user's home."""
    return home / ".config" / "systemd" / "user"


def windows_unit_path(home: Path) -> Path:
    """Where the Windows task XML is dropped, relative to the user's home."""
    return home / "Tasks" / "krellbot-tick.xml"


def owner_path(home: Path, venue: str = DEFAULT_VENUE) -> Path:
    """Where the per-venue owner file lives, relative to the data home."""
    return home / "service" / "owners" / f"{venue}.owner"


def _resolve_executable(explicit: str | None) -> str:
    """Return the executable path passed by the caller.

    Renderers take the absolute path. We do not call ``Path.home()`` or
    read the keyring; the caller passes the path explicitly. The CLI
    default is the current interpreter (so ``python -m krellbot`` and
    ``krellbot`` both work under the test runner).
    """
    if explicit:
        return explicit
    return sys.executable


def _render_owner(
    *,
    executable: str,
    home: Path,
    hour_interval: bool,
) -> bytes:
    """Render the per-venue owner file body.

    The body records the three things the brief requires: the
    executable path, the ``KRELLBOT_HOME`` value, and an explicit
    hourly interval marker. ``hour_interval=False`` is recorded as a
    daily marker (only ``hour_interval=True`` is currently supported by
    the renderers, but the owner file records the requested cadence
    so a future renderer can switch without ambiguity).
    """
    cadence = "interval=hourly" if hour_interval else "interval=daily"
    body = f"# krellbot supervised execution owner\nexecutable={executable}\nkrellbot_home={home}\n{cadence}\n"
    return body.encode("utf-8")


def install(
    home: Path,
    *,
    executable: str | None = None,
    hour_interval: bool = True,
    write_root: Path | None = None,
) -> int:
    """Install the supervised tick scheduler unit.

    Writes the platform unit under ``write_root`` (default: the user's
    home, where ``~/Library/LaunchAgents`` /
    ``~/.config/systemd/user`` / ``~/Tasks`` live) and the per-venue
    owner file under ``home/service/owners/default.owner``.

    Returns ``0`` on success, ``2`` on an existing owner file for the
    same venue (``owner_conflict`` on stderr, nothing is rewritten),
    or ``1`` for an unsupported platform.
    """
    home = Path(home)
    executable_path = _resolve_executable(executable)
    if write_root is None:
        write_root = Path.home()
    else:
        write_root = Path(write_root)

    own = owner_path(home)
    if own.exists():
        print("owner_conflict", file=sys.stderr)
        return 2

    if sys.platform == "darwin":
        body = render.render_launchd(executable_path, home)
        target = write_root / "Library" / "LaunchAgents" / LAUNCHD_FILENAME
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    elif sys.platform.startswith("linux"):
        units = render.render_systemd(executable_path, home)
        d = write_root / ".config" / "systemd" / "user"
        d.mkdir(parents=True, exist_ok=True)
        for name, body in units.items():
            (d / name).write_bytes(body)
    elif sys.platform == "win32":
        body = render.render_windows(executable_path, home)
        target = write_root / "Tasks" / "krellbot-tick.xml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    else:
        print(f"unsupported platform: {sys.platform}", file=sys.stderr)
        return 1

    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_bytes(
        _render_owner(
            executable=executable_path,
            home=home,
            hour_interval=hour_interval,
        )
    )
    return 0


def uninstall(home: Path, *, write_root: Path | None = None) -> int:
    """Remove the owner file and the scheduler unit this module wrote.

    Returns ``0`` on success or no-op, ``1`` on unsupported platform.
    The owner file is the ownership marker; clearing it lets a future
    ``install`` succeed without an ``owner_conflict``.
    """
    home = Path(home)
    if write_root is None:
        write_root = Path.home()
    else:
        write_root = Path(write_root)

    own = owner_path(home)
    if own.exists():
        own.unlink()

    if sys.platform == "darwin":
        target = write_root / "Library" / "LaunchAgents" / LAUNCHD_FILENAME
        if target.exists():
            target.unlink()
    elif sys.platform.startswith("linux"):
        d = write_root / ".config" / "systemd" / "user"
        for name in ("krellbot-tick.timer", "krellbot-tick.service"):
            p = d / name
            if p.exists():
                p.unlink()
    elif sys.platform == "win32":
        target = write_root / "Tasks" / "krellbot-tick.xml"
        if target.exists():
            target.unlink()
    else:
        print(f"unsupported platform: {sys.platform}", file=sys.stderr)
        return 1

    return 0
