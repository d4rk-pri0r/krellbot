"""Bounded local first-run preferences.

The only thing this module is allowed to remember is whether the local
user has reached the dashboard at least once. It writes one tiny JSON
file via krellbot.paths.atomic_write (mode 0o600) and reads it back,
treating any malformed payload as "not visited" so a partial write can
never silently flip the user back into the wizard.

The file lives directly under the krellbot home so it never widens the
home directory's permissions — atomic_write only chmods the file it
creates, and mark_visited_dashboard only creates the home if it does
not already exist (preserving any existing mode).
"""

from __future__ import annotations

import json
import os
import sys
from json import JSONDecodeError
from pathlib import Path

from krellbot.paths import atomic_write

_PREF_FILENAME = "ui-preferences.json"
_IS_WINDOWS = sys.platform == "win32"


def _pref_path(home: Path) -> Path:
    return home / _PREF_FILENAME


def _ensure_home(home: Path) -> None:
    """Create the data home privately on POSIX if it does not yet exist.

    The freshly created home (and any missing parents) is created with an
    explicit mode of 0o700 so the result is independent of the calling
    process's umask: a permissive umask such as 0o000 cannot leak the
    data home to other local users.

    An already-existing home keeps its mode untouched — we never chmod a
    directory we did not create, so a caller that pre-set a stricter or
    more permissive mode keeps it.

    mkdir errors propagate: callers depend on the directory existing, and
    silently swallowing OSError here would let ``atomic_write`` crash
    later with an ambiguous FileNotFoundError. Privacy is fail-closed:
    if we cannot make the directory private, we do not make it at all.
    """
    existed = home.exists()
    if existed:
        return
    home.mkdir(parents=True, mode=0o700, exist_ok=True)
    if _IS_WINDOWS:
        return
    # Explicit mode on mkdir is honored by POSIX, but a hostile umask or a
    # filesystem that ignores the mode argument (e.g. some FUSE mounts)
    # could still leave the directory too open. Stat and enforce 0o700
    # so the privacy guarantee holds regardless of those factors.
    try:
        st = os.stat(str(home))
    except OSError:
        return
    if (st.st_mode & 0o777) != 0o700:
        os.chmod(home, 0o700)


def has_visited_dashboard(home: Path) -> bool:
    """Return True if the local user has previously reached the dashboard.

    Any read failure (missing file, unreadable, malformed JSON, wrong
    type, missing key) is treated as "not visited" — the wizard is
    idempotent, the file is not authoritative. The check is strict:
    only the exact JSON literal ``true`` returns True, so a hand-edited
    file with ``"true"`` / ``1`` / ``[]`` cannot silently re-arm the
    dashboard.
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
    return data.get("visited_dashboard") is True


def mark_visited_dashboard(home: Path) -> None:
    """Record that the local user has reached the dashboard.

    Creates the data home privately (mode 0o700 on POSIX) if it does
    not already exist; never chmods a pre-existing home. The preference
    file itself is written atomically with mode 0o600.
    """
    _ensure_home(home)
    payload = json.dumps({"visited_dashboard": True}, separators=(",", ":")).encode("utf-8") + b"\n"
    atomic_write(_pref_path(home), payload, mode=0o600)


__all__ = ["has_visited_dashboard", "mark_visited_dashboard"]
