"""NS15 supervised execution ownership — `krellbot service install|uninstall`.

The supervised tick (launchd plist / systemd timer / Windows task XML) is
installed with an ownership marker: a per-venue owner file under
``<home>/service/owners/<venue>.owner`` that records the executable path,
the KRELLBOT_HOME value, and an explicit hourly interval marker. A second
install for the same venue while the owner file exists is an
``owner_conflict`` (rc=2, stderr ``owner_conflict``) and leaves both the
unit file and the owner file untouched. ``uninstall(home)`` removes the
owner file.

The unit (plist / timer+service / task XML) must set ``KRELLBOT_HOME`` in
its environment block, and the cadence must be hourly — an interval, not
a once-daily calendar.

``src/krellbot/service/runner.py`` is the entry point the scheduler
invokes. It must be importable, and ``install`` imports it (so a missing
or broken runner fails install, not just at scheduler fire time).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _expected_unit_path(write_root: Path) -> Path | dict[str, Path]:
    """Return the path(s) where install() drops the scheduler unit.

    macOS: ``<write_root>/Library/LaunchAgents/dev.krellbot.tick.plist``
    Linux: ``<write_root>/.config/systemd/user/{krellbot-tick.timer,
            krellbot-tick.service}``
    Windows: ``<write_root>/Tasks/krellbot-tick.xml``
    """
    if sys.platform == "darwin":
        return write_root / "Library" / "LaunchAgents" / "dev.krellbot.tick.plist"
    if sys.platform.startswith("linux"):
        d = write_root / ".config" / "systemd" / "user"
        return {
            "timer": d / "krellbot-tick.timer",
            "service": d / "krellbot-tick.service",
        }
    if sys.platform == "win32":
        return write_root / "Tasks" / "krellbot-tick.xml"
    raise RuntimeError(f"unsupported test platform: {sys.platform}")


def _unit_contents(path: Path | dict[str, Path]) -> str:
    """Concatenate the unit file(s) into one searchable blob."""
    if isinstance(path, dict):
        parts = []
        for p in path.values():
            parts.append(p.read_text(encoding="utf-8"))
        return "\n".join(parts)
    return path.read_text(encoding="utf-8")


def _expected_owner_path(home: Path, venue: str = "default") -> Path:
    """Where the per-venue owner file lives."""
    return home / "service" / "owners" / f"{venue}.owner"


# ---------------------------------------------------------------------------
# Owner file write — install creates it
# ---------------------------------------------------------------------------


def test_install_writes_owner_file_under_home(home):
    """install writes the per-venue owner file under <home>/service/owners/."""
    from krellbot.service import install

    rc = install(
        home,
        executable="/usr/local/bin/krellbot",
        write_root=home,
    )

    owner_path = _expected_owner_path(home)
    assert rc == 0
    assert owner_path.is_file(), f"owner file not written: {owner_path}"


def test_owner_file_records_executable_and_home_and_interval(home):
    """The owner file contains the executable path, KRELLBOT_HOME value,
    and an explicit hourly interval marker.
    """
    from krellbot.service import install

    executable = "/usr/local/bin/krellbot"
    install(home, executable=executable, write_root=home)

    body = _expected_owner_path(home).read_text(encoding="utf-8")
    assert executable in body
    assert str(home) in body
    # An explicit hourly interval marker is present (case-insensitive on
    # the keyword, since the test does not pin the exact spelling).
    lowered = body.lower()
    assert "interval" in lowered
    assert "hour" in lowered


# ---------------------------------------------------------------------------
# Unit file write — KRELLBOT_HOME and hourly cadence
# ---------------------------------------------------------------------------


def test_install_writes_scheduler_unit_under_write_root(home):
    """install writes the platform-appropriate unit under write_root."""
    from krellbot.service import install

    rc = install(
        home,
        executable="/usr/local/bin/krellbot",
        write_root=home,
    )

    unit = _expected_unit_path(home)
    assert rc == 0
    if isinstance(unit, dict):
        for p in unit.values():
            assert p.is_file(), f"missing unit file: {p}"
    else:
        assert unit.is_file(), f"missing unit file: {unit}"


def test_unit_file_sets_krellbot_home_in_environment(home):
    """The rendered unit sets KRELLBOT_HOME in its environment block.

    This must hold for every platform the test runs on. The hour-interval
    cadence (every hour, not once a day) is checked separately below.
    """
    from krellbot.service import install

    install(home, executable="/usr/local/bin/krellbot", write_root=home)

    body = _unit_contents(_expected_unit_path(home))
    assert "KRELLBOT_HOME" in body
    assert str(home) in body


def test_unit_file_uses_hourly_cadence_not_daily_calendar(home):
    """Hourly cadence is an interval, not a once-daily calendar.

    Platform semantics:
      - macOS launchd: StartCalendarInterval has Minute=1 and no Hour key
        (fires every hour at minute 1, not once a day).
      - Linux systemd: OnCalendar fires every hour at minute 1
        (``*-*-* *:01:00``); no day-of-week restriction.
      - Windows task XML: <CalendarTrigger> with <Interval>PT1H</Interval>.

    The unit must not be a "once a day" calendar (e.g., no ``Hour=0``
    only, no ``*-*-* 00:00:00``).
    """
    from krellbot.service import install

    install(home, executable="/usr/local/bin/krellbot", write_root=home)

    unit = _expected_unit_path(home)
    body = _unit_contents(unit)

    if sys.platform == "darwin":
        # Minute=1 is present (hourly). No Hour key restricting to a single
        # hour-of-day (which would make it once daily).
        assert "<key>Minute</key>" in body
        assert "<integer>1</integer>" in body
        assert "<key>Hour</key>" not in body
    elif sys.platform.startswith("linux"):
        # OnCalendar fires every hour at minute 1. Must not be
        # "*-*-* 00:00:00" (midnight daily) or "*-*-* 0:00:00".
        assert "OnCalendar=*-*-* *:01:00" in body
        assert "OnCalendar=*-*-* 00:00:00" not in body
        assert "Persistent=true" in body
    elif sys.platform == "win32":
        assert "<CalendarTrigger>" in body
        assert "<Interval>PT1H</Interval>" in body
        # Once-daily triggers use ScheduleByDay, not a CalendarTrigger with
        # an hourly interval.
        assert "ScheduleByDay" not in body


# ---------------------------------------------------------------------------
# Conflict semantics — second install for the same venue fails cleanly
# ---------------------------------------------------------------------------


def test_second_install_for_same_venue_returns_2_and_owner_conflict(home, capsys):
    """A second install for the same venue (same home) while the owner
    file exists returns 2 and prints ``owner_conflict`` to stderr.
    """
    from krellbot.service import install

    install(home, executable="/usr/local/bin/krellbot", write_root=home)
    rc = install(home, executable="/usr/local/bin/krellbot", write_root=home)
    captured = capsys.readouterr()

    assert rc == 2
    assert "owner_conflict" in captured.err


def test_conflict_does_not_overwrite_owner_file(home):
    """On owner_conflict the existing owner file is preserved byte-for-byte."""
    from krellbot.service import install

    install(home, executable="/usr/local/bin/krellbot", write_root=home)
    owner_path = _expected_owner_path(home)
    original_owner = owner_path.read_bytes()

    # A conflicting install must not rewrite the owner file. Give the FS
    # a chance to update mtime by sleeping briefly — but reading the
    # bytes is enough: they must match.
    rc = install(home, executable="/usr/local/bin/krellbot", write_root=home)
    assert rc == 2

    assert owner_path.read_bytes() == original_owner


def test_conflict_does_not_overwrite_unit_file(home):
    """On owner_conflict the existing unit file is preserved byte-for-byte."""
    from krellbot.service import install

    install(home, executable="/usr/local/bin/krellbot", write_root=home)
    unit = _expected_unit_path(home)
    if isinstance(unit, dict):
        original_unit = {k: v.read_bytes() for k, v in unit.items()}
    else:
        original_unit = unit.read_bytes()

    rc = install(home, executable="/usr/local/bin/krellbot", write_root=home)
    assert rc == 2

    if isinstance(unit, dict):
        for k, p in unit.items():
            assert p.read_bytes() == original_unit[k], f"unit file {k} changed on conflict"
    else:
        assert unit.read_bytes() == original_unit


def test_different_home_is_different_venue_no_conflict(tmp_path):
    """Different homes are different venues — no conflict between them.

    Each install lives in its own data home, so two installs at
    different homes both succeed and produce independent owner files.
    """
    from krellbot.service import install

    home_a = tmp_path / "a"
    home_b = tmp_path / "b"

    rc_a = install(home_a, executable="/usr/local/bin/krellbot", write_root=home_a)
    rc_b = install(home_b, executable="/usr/local/bin/krellbot", write_root=home_b)

    assert rc_a == 0
    assert rc_b == 0
    assert _expected_owner_path(home_a).is_file()
    assert _expected_owner_path(home_b).is_file()


# ---------------------------------------------------------------------------
# uninstall removes the owner file
# ---------------------------------------------------------------------------


def test_uninstall_removes_owner_file(home):
    """uninstall(home) removes the owner file under <home>/service/owners/."""
    from krellbot.service import install, uninstall

    install(home, executable="/usr/local/bin/krellbot", write_root=home)
    owner_path = _expected_owner_path(home)
    assert owner_path.is_file()

    rc = uninstall(home, write_root=home)
    assert rc == 0
    assert not owner_path.exists()


def test_uninstall_after_install_then_reinstall_succeeds(home):
    """After uninstall, a fresh install for the same venue succeeds again.

    uninstall clears the ownership marker, so the conflict check no
    longer triggers.
    """
    from krellbot.service import install, uninstall

    install(home, executable="/usr/local/bin/krellbot", write_root=home)
    uninstall(home, write_root=home)

    rc = install(home, executable="/usr/local/bin/krellbot", write_root=home)
    assert rc == 0
    assert _expected_owner_path(home).is_file()


# ---------------------------------------------------------------------------
# Runner module — must be importable, install imports it
# ---------------------------------------------------------------------------


def test_runner_module_is_importable():
    """`krellbot.service.runner` is importable without side effects."""
    mod = importlib.import_module("krellbot.service.runner")
    assert mod is not None


def test_install_module_imports_runner():
    """`krellbot.service.__init__` imports the runner at install-time.

    The runner is loaded when install() runs (not lazily inside the
    scheduler unit), so a broken runner fails the install, not the
    scheduled tick.
    """
    import krellbot.service as kb_service
    from krellbot.service import runner

    # `install` triggers the import; importing the package itself must
    # already expose `runner` as an attribute so a stale install that
    # only imports the package can still detect a missing runner.
    assert hasattr(kb_service, "runner")
    assert kb_service.runner is runner
