"""Read-only local security posture snapshot.

The first-run wizard and the dashboard both need to tell the user
"here is what is true about this machine right now" without ever
touching a credential. This module exposes the only view of the
local posture that is allowed into the UI layer.

Everything in the returned dict is presentation-only:
  - home / home_mode: where state lives, and how private the directory is.
  - keychain_backend / keychain_ok: identity-only; no secret lookups.
  - bind: the loopback interface only.
  - live_arm_ui_allowed / trade_only_required: safety rails.

This module never reads, writes, or imports any venue credential. The
keychain backend identity is exposed as a *name* (class path) and a
boolean; if the backend is null/fake/fail, keychain_ok is False.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from krellbot.doctor import _keychain_backend

_IS_WINDOWS = sys.platform == "win32"


def _home_mode_or_none(home: Path) -> str | None:
    """Return home's POSIX mode as an octal string, or None if unreadable.

    On Windows we return None — the wizard has nothing useful to say
    about DACLs in this version.
    """
    if _IS_WINDOWS:
        return None
    try:
        st = os.stat(str(home))
    except OSError:
        return None
    return oct(stat.S_IMODE(st.st_mode))


def trust_snapshot(home: Path) -> dict[str, object]:
    """Return a presentation-only snapshot of local trust posture.

    The dict shape is fixed. Callers must not depend on extra keys.
    """
    backend, warning = _keychain_backend()
    return {
        "home": str(home),
        "home_mode": _home_mode_or_none(home),
        "keychain_backend": backend,
        "keychain_ok": warning is None,
        "bind": "127.0.0.1",
        "live_arm_ui_allowed": False,
        "trade_only_required": True,
    }


__all__ = ["trust_snapshot"]
