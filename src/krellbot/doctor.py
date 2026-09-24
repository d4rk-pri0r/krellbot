"""`krellbot doctor` and `krellbot doctor --json`.

The doctor runs every health check with no network unless a time source is
injected. The CLI passes a `time_source` callable that reads the public
Kraken Time endpoint; tests pass a fake and prove zero socket calls.

Checks (each a row in text and a field in JSON):

- Home directory mode is `0o700` on POSIX. Windows reports the check
  skipped, not failed.
- Keychain backend name. A null, fail, or fake backend is a warning.
- For `kraken` and `coinbase`: key present or absent. Permission probe is
  injected; with no probe we report present/absent only, never a live
  `WithdrawMethods` call.
- Service unit file exists for this platform under the injected root.
- Last `kind=tick` journal `ts` age. Stale when age is greater than or equal
  to `2 * 3600` seconds. Missing journal is stale.
- Clock skew versus injected Kraken `unixtime`. Warn when
  `abs(now - unixtime) > 5`. Missing source warns `clock not checked` and
  does not raise.
- License cache status, or `missing`.
- Each armed pack: cap cash versus `paper.default_rules(pair)` when that pair
  is known. Unknown pair warns `minimums not loaded`. We never invent a
  fake minimum.
"""

from __future__ import annotations

import json
import sys
import time as _time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from krellbot import config as kb_config
from krellbot import license as kb_license
from krellbot import paths as kb_paths
from krellbot import secrets as kb_secrets

TICK_STALE_SECONDS = 2 * 3600
CLOCK_SKEW_WARN_SECONDS = 5


def _home_mode_ok(home: Path) -> bool | None:
    """True if home mode is `0o700`, None on Windows (skipped), False otherwise."""
    if sys.platform == "win32":
        return None
    return (home.stat().st_mode & 0o777) == 0o700


def _keychain_backend() -> tuple[str | None, str | None]:
    """Return (backend_name, warning). A warning is set for null/fail/fake."""
    try:
        import keyring

        backend = keyring.get_keyring()
    except (ImportError, AttributeError, OSError, RuntimeError):
        return (None, "keychain backend unavailable")
    cls = type(backend)
    module_path = (cls.__module__ or "").lower()
    cls_name = cls.__name__.lower()
    name_attr = getattr(backend, "name", None)
    if isinstance(name_attr, str) and name_attr:
        backend_name: str | None = name_attr
    else:
        backend_name = cls.__name__
    is_fake = "fake" in module_path or "fake" in cls_name
    is_null = "null" in module_path or "null" in cls_name
    is_fail = "fail" in module_path or "fail" in cls_name
    if is_fake or is_null or is_fail:
        return (backend_name, f"keychain backend is {cls.__name__} (not persistent)")
    return (backend_name, None)


def _keys_status(permission_probe: Callable[[str], Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for venue in sorted(kb_secrets.VENUES):
        info: dict[str, Any] = {"present": False}
        try:
            kb_secrets.get(venue)
            info["present"] = True
        except (FileNotFoundError, ValueError, PermissionError):
            info["present"] = False
        if permission_probe is not None and info["present"]:
            try:
                perms = permission_probe(venue)
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                perms = None
            if perms is not None:
                info["trade"] = bool(getattr(perms, "can_trade", False))
                info["withdraw"] = bool(getattr(perms, "can_withdraw", False))
        out[venue] = info
    return out


def _service_installed(write_root: Path) -> bool:
    if sys.platform == "darwin":
        return (write_root / "Library" / "LaunchAgents" / "dev.krellbot.tick.plist").exists()
    if sys.platform.startswith("linux"):
        d = write_root / ".config" / "systemd" / "user"
        return (d / "krellbot-tick.timer").exists() and (d / "krellbot-tick.service").exists()
    if sys.platform == "win32":
        return (write_root / "Tasks" / "krellbot-tick.xml").exists()
    return False


def _last_tick_age(home: Path, now: int) -> int | None:
    """Return seconds since the last `kind=tick` journal record, or None.

    None means there is no journal directory or no tick record at all (which
    the caller reports as stale).
    """
    journal_dir = home / "journal"
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
            if rec.get("kind") == "tick":
                found = True
                ts = int(rec.get("ts", 0) or 0)
                latest_ts = max(latest_ts, ts)
    if not found or latest_ts <= 0:
        return None
    return max(0, now - latest_ts)


def _clock_check(now: int, time_source: Callable[[], int] | None) -> tuple[int | None, str | None]:
    """Return (skew_seconds, warning_string).

    A missing time source is `clock not checked`, not an exception.
    """
    if time_source is None:
        return (None, "clock not checked")
    try:
        remote = int(time_source())
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return (None, "clock not checked")
    skew = int(now) - int(remote)
    if abs(skew) > CLOCK_SKEW_WARN_SECONDS:
        return (skew, f"clock skew {skew}s (>{CLOCK_SKEW_WARN_SECONDS}s)")
    return (skew, None)


def _license_status(home: Path) -> str:
    cache = kb_license.read_cache(home)
    if cache is None:
        return "missing"
    status = cache.get("status")
    if isinstance(status, str) and status:
        return status
    return "missing"


def _armed_check(armed: list) -> list[dict[str, Any]]:
    """For each armed pack, check cap cash versus paper.default_rules(pair)."""
    from krellbot.venues.paper import default_rules

    out: list[dict[str, Any]] = []
    for a in armed:
        entry: dict[str, Any] = {
            "venue": a.venue,
            "pair": a.pair,
            "cap": str(a.cap),
            "ok": True,
            "warning": None,
        }
        if a.starting_cash is None:
            out.append(entry)
            continue
        try:
            rules = default_rules(a.pair)
        except ValueError:
            entry["ok"] = False
            entry["warning"] = "minimums not loaded"
            out.append(entry)
            continue
        cash_for_cap = a.starting_cash * a.cap / Decimal(100)
        if cash_for_cap < rules.costmin:
            entry["ok"] = False
            entry["warning"] = f"cap {cash_for_cap} cannot meet pair minimum ({rules.costmin})"
        out.append(entry)
    return out


def _render_text(report: dict[str, Any]) -> str:
    lines = []
    home_mode_ok = report["home_mode_ok"]
    if home_mode_ok is None:
        lines.append("home mode: skipped (Windows)")
    elif home_mode_ok:
        lines.append("home mode: 0o700 ok")
    else:
        lines.append("home mode: NOT 0o700")
    lines.append(f"keychain backend: {report['keychain_backend'] or 'unknown'}")
    for venue, info in sorted(report["keys"].items()):
        present = info.get("present", False)
        if present and "trade" in info:
            t = "on" if info["trade"] else "off"
            w = "on" if info["withdraw"] else "off"
            lines.append(f"{venue} key: present (trade={t}, withdraw={w})")
        else:
            lines.append(f"{venue} key: {'present' if present else 'absent'}")
    lines.append(f"service installed: {'yes' if report['service_installed'] else 'no'}")
    age = report["last_tick_age_s"]
    if age is None:
        lines.append("last tick: never")
    else:
        suffix = " (stale)" if report["last_tick_stale"] else ""
        lines.append(f"last tick: {age}s ago{suffix}")
    skew = report["clock_skew_s"]
    if skew is None:
        lines.append("clock: not checked")
    else:
        warn = report["clock_warn"]
        suffix = f" ({warn})" if warn else ""
        lines.append(f"clock skew: {skew}s{suffix}")
    lines.append(f"license cache: {report['license_status']}")
    for entry in report["armed"]:
        if entry["warning"]:
            lines.append(f"{entry['venue']} {entry['pair']}: {entry['warning']}")
    if report["warnings"]:
        lines.append(f"warnings: {'; '.join(report['warnings'])}")
    else:
        lines.append("warnings: none")
    return "\n".join(lines)


def run(
    *,
    home: Path | None = None,
    write_root: Path | None = None,
    permission_probe: Callable[[str], Any] | None = None,
    time_source: Callable[[], int] | None = None,
    clock: Callable[[], int | float] | None = None,
    as_json: bool = False,
) -> tuple[int, str]:
    """Run the doctor. Returns (exit_code, body_string).

    Exit code is 0 when `ok` is true (no warnings), 1 otherwise. The body is
    JSON when `as_json=True` or text otherwise. No HTTP unless a `time_source`
    is injected.
    """
    home = Path(home) if home is not None else kb_paths.home()
    write_root = Path(write_root) if write_root is not None else home

    clock_fn = clock if clock is not None else _time.time
    now = int(clock_fn())

    warnings: list[str] = []

    home_mode_ok = _home_mode_ok(home)
    if home_mode_ok is False:
        warnings.append("home directory mode is not 0o700")

    backend_name, backend_warn = _keychain_backend()
    if backend_warn is not None:
        warnings.append(backend_warn)

    keys = _keys_status(permission_probe)
    for venue, info in keys.items():
        if not info["present"]:
            warnings.append(f"{venue}: key not stored")

    service_installed = _service_installed(write_root)

    last_tick_age_s = _last_tick_age(home, now)
    last_tick_stale = last_tick_age_s is None or last_tick_age_s >= TICK_STALE_SECONDS
    if last_tick_stale:
        if last_tick_age_s is None:
            warnings.append("no tick in the last 2h")
        else:
            warnings.append(f"last tick {last_tick_age_s}s ago (stale)")

    clock_skew_s, clock_warn = _clock_check(now, time_source)
    if clock_warn is not None:
        warnings.append(clock_warn)

    license_status = _license_status(home)

    config = kb_config.load_config(home)
    armed_status = _armed_check(config.armed)
    for entry in armed_status:
        if entry["warning"]:
            warnings.append(f"{entry['venue']} {entry['pair']}: {entry['warning']}")

    ok = len(warnings) == 0

    report = {
        "ok": ok,
        "home_mode_ok": home_mode_ok,
        "keychain_backend": backend_name,
        "keys": keys,
        "service_installed": service_installed,
        "last_tick_age_s": last_tick_age_s,
        "last_tick_stale": last_tick_stale,
        "clock_skew_s": clock_skew_s,
        "clock_warn": clock_warn,
        "license_status": license_status,
        "armed": armed_status,
        "warnings": warnings,
    }

    if as_json:
        return (0 if ok else 1, json.dumps(report, sort_keys=True))
    return (0 if ok else 1, _render_text(report))
