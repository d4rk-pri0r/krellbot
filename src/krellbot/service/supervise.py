"""Supervision helpers for the scheduled tick.

The OS scheduler fires ``krellbot tick`` (or ``krellbot.service.runner``,
which delegates) on an hourly cadence. After a sleep/wake cycle the gap
between scheduled firings can be much larger than an hour. ``record_wake_gap``
detects that gap and journals a ``kind=supervision / event=wake_gap`` record
so the operator and the doctor can see a long absence happened.

The wake-gap check fires *before* the tick evaluates the latest bar: it is a
supervision signal, not a backfill request. The engine itself does no replay
of missed bars; ``run.tick`` already coalesces by feeding every candle up to
the latest into ``evaluate.run`` so the indicator state is correct on the
post-wake bar, and outbox coids prevent a duplicate send for a bar that was
already sent.

Platform enable (``systemctl`` / ``launchctl`` / ``schtasks``) lives behind
the ``PlatformSupervisor`` seam so the loopback API and tests never call the
real OS scheduler unless a production supervisor is selected.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from krellbot import doctor
from krellbot import journal as kb_journal

SCHEMA_VERSION = "1"
LAST_ERROR_FILENAME = "last_error"
LAUNCHD_LABEL = "dev.krellbot.tick"
LAUNCHD_FILENAME = f"{LAUNCHD_LABEL}.plist"
SYSTEMD_TIMER_NAME = "krellbot-tick.timer"
SYSTEMD_SERVICE_NAME = "krellbot-tick.service"
WINDOWS_TASK_NAME = r"\krellbot\tick"
WINDOWS_TASK_FILENAME = "krellbot-tick.xml"


def last_tick_ts(home: Path, venue: str) -> int | None:
    """Return the maximum ``ts`` of ``kind=tick`` journal records for ``venue``.

    Skips unparseable lines. Returns None when no tick record exists for
    the venue. ``home`` is the krellbot data home (does not create it).
    """
    journal_dir = Path(home) / "journal"
    if not journal_dir.is_dir():
        return None
    latest_ts = 0
    found = False
    for path in sorted(journal_dir.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") != "tick":
                continue
            if rec.get("venue") != venue:
                continue
            try:
                ts = int(rec.get("ts", 0) or 0)
            except (TypeError, ValueError):
                continue
            if ts <= 0:
                continue
            found = True
            latest_ts = max(latest_ts, ts)
    if not found:
        return None
    return latest_ts


def record_wake_gap(
    home: Path,
    venue: str,
    *,
    now: int,
    threshold: int = doctor.TICK_STALE_SECONDS,
) -> int | None:
    """Journal a wake-gap record when the gap since the last tick is large.

    When ``last_tick_ts`` is not None and ``now - last >= threshold``, a
    journal record of the form::

        {"ts": now, "kind": "supervision", "venue": venue,
         "pack": "-", "bar_ts": 0,
         "detail": {"event": "wake_gap", "gap_s": now - last,
                    "last_tick_ts": last}}

    is appended and the gap in seconds is returned. Otherwise (no tick
    record, or the gap is below the threshold) nothing is journaled and
    None is returned. Failures to journal (e.g. read-only home) are
    swallowed so the tick itself is never blocked by supervision IO.
    """
    last = last_tick_ts(home, venue)
    if last is None:
        return None
    gap = int(now) - int(last)
    if gap < int(threshold):
        return None
    try:
        kb_journal.append(
            {
                "ts": int(now),
                "kind": "supervision",
                "venue": venue,
                "pack": "-",
                "bar_ts": 0,
                "detail": {
                    "event": "wake_gap",
                    "gap_s": gap,
                    "last_tick_ts": int(last),
                },
            }
        )
    except (OSError, ValueError):
        pass
    return gap


def latest_wake_gap(home: Path, venue: str | None = None) -> int | None:
    """Return the ``gap_s`` of the newest ``wake_gap`` record, or None.

    When ``venue`` is None, looks across all venues. ``home`` is the
    data home and is not created.
    """
    journal_dir = Path(home) / "journal"
    if not journal_dir.is_dir():
        return None
    newest_ts = -1
    newest_gap: int | None = None
    for path in sorted(journal_dir.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") != "supervision":
                continue
            detail = rec.get("detail") or {}
            if detail.get("event") != "wake_gap":
                continue
            if venue is not None and rec.get("venue") != venue:
                continue
            try:
                ts = int(rec.get("ts", 0) or 0)
            except (TypeError, ValueError):
                continue
            if ts < newest_ts:
                continue
            newest_ts = ts
            try:
                newest_gap = int(detail.get("gap_s", 0) or 0)
            except (TypeError, ValueError):
                newest_gap = None
    return newest_gap


def resolve_owner(home: Path) -> dict | None:
    """Parse the default owner file, returning the supervisor record or None.

    Returns None when the owner file does not exist. Keys are sorted
    alphabetically. ``home`` is the data home; it is not created here.
    """
    owner = Path(home) / "service" / "owners" / "default.owner"
    if not owner.exists():
        return None
    try:
        text = owner.read_text(encoding="utf-8")
    except OSError:
        return None
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        out[key] = value
    return out or None


# ---------------------------------------------------------------------------
# Scheduler install / enable / status (API seam)
# ---------------------------------------------------------------------------


def last_error_path(home: Path) -> Path:
    """Where the durable scheduler ``last_error`` text lives under the data home."""
    return Path(home) / "service" / LAST_ERROR_FILENAME


def get_last_error(home: Path) -> str | None:
    """Return the last scheduler error string, or None when clear/missing."""
    path = last_error_path(home)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def set_last_error(home: Path, message: str | None) -> None:
    """Persist or clear the scheduler ``last_error`` under ``home/service``.

    ``message=None`` or empty removes the file. Failures to write are
    swallowed so a read-only home cannot block status reads; callers that
    need a durable error should still surface the in-memory message.
    """
    path = last_error_path(home)
    if not message:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(message).strip() + "\n", encoding="utf-8")
    except OSError:
        pass


def units_installed(write_root: Path) -> bool:
    """True when the platform unit files exist under ``write_root``."""
    root = Path(write_root)
    if sys.platform == "darwin":
        return (root / "Library" / "LaunchAgents" / LAUNCHD_FILENAME).is_file()
    if sys.platform.startswith("linux"):
        d = root / ".config" / "systemd" / "user"
        return (d / SYSTEMD_TIMER_NAME).is_file() and (d / SYSTEMD_SERVICE_NAME).is_file()
    if sys.platform == "win32":
        return (root / "Tasks" / WINDOWS_TASK_FILENAME).is_file()
    return False


class PlatformSupervisor(Protocol):
    """OS enable/query surface used by the scheduler API.

    Production code uses ``platform_supervisor()``. Tests inject a
    ``FakeSupervisor`` so no ``systemctl`` / ``launchctl`` / ``schtasks``
    process is ever spawned.
    """

    def enable(self, *, write_root: Path) -> None:
        """Enable (and start) the installed scheduler unit under ``write_root``."""

    def is_enabled(self, *, write_root: Path) -> bool:
        """Return whether the platform reports the unit as enabled."""


@dataclass
class FakeSupervisor:
    """In-memory supervisor for tests. Never talks to the OS."""

    enabled: bool = False
    fail_message: str | None = None
    enable_calls: list[Path] = field(default_factory=list)

    def enable(self, *, write_root: Path) -> None:
        self.enable_calls.append(Path(write_root))
        if self.fail_message:
            raise RuntimeError(self.fail_message)
        self.enabled = True

    def is_enabled(self, *, write_root: Path) -> bool:
        return bool(self.enabled)


@dataclass(frozen=True)
class UnavailableSupervisor:
    """Used on platforms without a known scheduler enable path."""

    reason: str = "unsupported platform"

    def enable(self, *, write_root: Path) -> None:
        raise RuntimeError(self.reason)

    def is_enabled(self, *, write_root: Path) -> bool:
        return False


def _run_checked(argv: list[str], *, label: str) -> None:
    """Run ``argv``; raise RuntimeError with stderr/stdout on non-zero exit."""
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{label}: {exc}") from exc
    if completed.returncode == 0:
        return
    detail = (completed.stderr or completed.stdout or "").strip()
    if detail:
        raise RuntimeError(f"{label}: {detail}")
    raise RuntimeError(f"{label}: exit {completed.returncode}")


@dataclass(frozen=True)
class SystemdUserSupervisor:
    """Linux: ``systemctl --user`` enable/start of ``krellbot-tick.timer``."""

    def enable(self, *, write_root: Path) -> None:
        # ``write_root`` is expected to be the user home so the units land
        # where ``systemctl --user`` already looks (``~/.config/systemd/user``).
        _ = write_root
        _run_checked(
            ["systemctl", "--user", "daemon-reload"],
            label="systemctl daemon-reload",
        )
        _run_checked(
            ["systemctl", "--user", "enable", "--now", SYSTEMD_TIMER_NAME],
            label="systemctl enable",
        )

    def is_enabled(self, *, write_root: Path) -> bool:
        _ = write_root
        try:
            completed = subprocess.run(
                ["systemctl", "--user", "is-enabled", SYSTEMD_TIMER_NAME],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        state = (completed.stdout or "").strip()
        return completed.returncode == 0 and state in {"enabled", "static", "indirect"}


@dataclass(frozen=True)
class LaunchdSupervisor:
    """macOS: ``launchctl bootstrap`` / ``enable`` for ``dev.krellbot.tick``."""

    def enable(self, *, write_root: Path) -> None:
        plist = Path(write_root) / "Library" / "LaunchAgents" / LAUNCHD_FILENAME
        if not plist.is_file():
            raise RuntimeError(f"unit not installed: {plist}")
        domain = _launchd_domain()
        # bootstrap may fail if already loaded; enable + kickstart cover that.
        try:
            _run_checked(
                ["launchctl", "bootstrap", domain, str(plist)],
                label="launchctl bootstrap",
            )
        except RuntimeError:
            pass
        _run_checked(
            ["launchctl", "enable", f"{domain}/{LAUNCHD_LABEL}"],
            label="launchctl enable",
        )

    def is_enabled(self, *, write_root: Path) -> bool:
        _ = write_root
        domain = _launchd_domain()
        try:
            completed = subprocess.run(
                ["launchctl", "print", f"{domain}/{LAUNCHD_LABEL}"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0


def _launchd_domain() -> str:
    """Return ``gui/<uid>`` for the current user (best-effort)."""
    try:
        import os

        return f"gui/{os.getuid()}"
    except AttributeError:
        return "gui/501"


@dataclass(frozen=True)
class WindowsTaskSupervisor:
    """Windows: register/enable the ``\\krellbot\\tick`` scheduled task."""

    def enable(self, *, write_root: Path) -> None:
        xml_path = Path(write_root) / "Tasks" / WINDOWS_TASK_FILENAME
        if not xml_path.is_file():
            raise RuntimeError(f"unit not installed: {xml_path}")
        _run_checked(
            [
                "schtasks",
                "/Create",
                "/TN",
                WINDOWS_TASK_NAME,
                "/XML",
                str(xml_path),
                "/F",
            ],
            label="schtasks create",
        )
        _run_checked(
            ["schtasks", "/Change", "/TN", WINDOWS_TASK_NAME, "/ENABLE"],
            label="schtasks enable",
        )

    def is_enabled(self, *, write_root: Path) -> bool:
        _ = write_root
        try:
            completed = subprocess.run(
                ["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0


def platform_supervisor() -> PlatformSupervisor:
    """Return the production supervisor for ``sys.platform``."""
    if sys.platform == "darwin":
        return LaunchdSupervisor()
    if sys.platform.startswith("linux"):
        return SystemdUserSupervisor()
    if sys.platform == "win32":
        return WindowsTaskSupervisor()
    return UnavailableSupervisor(reason=f"unsupported platform: {sys.platform}")


def scheduler_status(
    home: Path,
    *,
    write_root: Path,
    supervisor: PlatformSupervisor,
) -> dict[str, object]:
    """Closed-shape scheduler status for the loopback API."""
    installed = units_installed(write_root)
    enabled = False
    if installed:
        try:
            enabled = bool(supervisor.is_enabled(write_root=Path(write_root)))
        except Exception:  # noqa: BLE001 — status must never raise
            enabled = False
    return {
        "schema_version": SCHEMA_VERSION,
        "installed": installed,
        "enabled": enabled,
        "last_error": get_last_error(home),
    }


def install_scheduler(
    home: Path,
    *,
    write_root: Path,
    supervisor: PlatformSupervisor,
    executable: str | None = None,
) -> dict[str, object]:
    """Install unit files via ``service.install`` and return scheduler status.

    Already-installed homes (unit files present) are treated as success
    without rewriting. Failures set ``last_error`` and leave units alone.
    Uses a silent install (stdout discarded) so the API log stays clean.
    """
    import io
    from contextlib import redirect_stderr, redirect_stdout

    from krellbot import service as kb_service

    root = Path(write_root)
    if units_installed(root):
        set_last_error(home, None)
        return scheduler_status(home, write_root=root, supervisor=supervisor)

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
        rc = kb_service.install(
            home=Path(home),
            executable=executable,
            write_root=root,
            dry_run=False,
        )

    if rc == 0:
        set_last_error(home, None)
    elif rc == 2:
        set_last_error(home, "owner_conflict")
    else:
        detail = stderr_buf.getvalue().strip() or f"install failed (rc={rc})"
        set_last_error(home, detail)

    return scheduler_status(home, write_root=root, supervisor=supervisor)


def enable_scheduler(
    home: Path,
    *,
    write_root: Path,
    supervisor: PlatformSupervisor,
) -> dict[str, object]:
    """Enable the installed unit via ``supervisor`` and return status."""
    root = Path(write_root)
    if not units_installed(root):
        set_last_error(home, "not_installed")
        return scheduler_status(home, write_root=root, supervisor=supervisor)

    try:
        supervisor.enable(write_root=root)
    except Exception as exc:  # noqa: BLE001 — surface as last_error
        set_last_error(home, str(exc) or "enable failed")
        return scheduler_status(home, write_root=root, supervisor=supervisor)

    set_last_error(home, None)
    return scheduler_status(home, write_root=root, supervisor=supervisor)
