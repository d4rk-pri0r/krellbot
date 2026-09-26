"""Bounded local first-run preferences.

The only thing this module is allowed to remember is whether the local
user has reached the dashboard at least once. It writes one tiny JSON
file via krellbot.paths.atomic_write (mode 0o600) and reads it back,
treating any malformed payload as "not visited" so a partial write can
never silently flip the user back into the wizard.

The file lives directly under the krellbot home so it never widens the
home directory's permissions — atomic_write only chmods the file it
creates.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from json import JSONDecodeError
from pathlib import Path

from krellbot.paths import atomic_write

_PREF_FILENAME = "ui-preferences.json"
_IS_WINDOWS = sys.platform == "win32"


def _pref_path(home: Path) -> Path:
    return home / _PREF_FILENAME


def has_visited_dashboard(home: Path) -> bool:
    """Return True if the local user has previously reached the dashboard.

    Any read failure (missing file, unreadable, malformed JSON) is
    treated as "not visited" — the wizard is idempotent, the file is
    not authoritative.
    """
    path = _pref_path(home)
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    try:
        data = json.loads(raw)
    except JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    return bool(data.get("visited_dashboard"))


def mark_visited_dashboard(home: Path) -> None:
    """Record that the local user has reached the dashboard.

    Uses atomic_write with mode 0o600 so the file is private to the
    owner, and never chmods the surrounding home directory.
    """
    payload = json.dumps({"visited_dashboard": True}, separators=(",", ":")).encode("utf-8") + b"\n"
    atomic_write(_pref_path(home), payload, mode=0o600)


__all__ = ["has_visited_dashboard", "mark_visited_dashboard"]


# Quiet down an unused-import warning on Windows where stat.S_IMODE is
# available but we never call it from here.
_ = stat
_ = os
_ = _IS_WINDOWS
