"""Read-only local security posture snapshot.

The first-run wizard and the dashboard both need to tell the user
"here is what is true about this machine right now" without ever
touching a credential. This module exposes the only view of the
local posture that is allowed into the UI layer.

Everything in the returned dict is presentation-only:
  - home / home_mode: where state lives, and how private the directory is.
  - keychain_backend / keychain_ok: identity-only; no secret lookups.
  - posture_ok / posture_warning: the **aggregate** posture.
    posture_ok is True only when BOTH the backend is persistent
    AND the home mode is 0o700 (or unreadable — that is itself a
    posture issue we cannot hide from the user).
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

# A home directory is "private" exactly when its POSIX mode is 0o700.
# A wider mode means other local users can read the keys, journal, and
# receipts. We never accept 0o755, 0o775, or 0o777 as private.
_HOME_MODE_PRIVATE = "0o700"


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

    The ``posture_ok`` aggregate is True only when the backend is
    persistent AND the home mode is the private 0o700. Any other
    combination produces a non-empty ``posture_warning`` string the
    UI can render so the user sees the truth.
    """
    backend, backend_warn = _keychain_backend()
    backend_ok = backend_warn is None
    home_mode = _home_mode_or_none(home)
    home_mode_ok = home_mode == _HOME_MODE_PRIVATE

    warnings: list[str] = []
    if not backend_ok:
        # Trust snapshot must not invent a backend name; surface the
        # backend warning verbatim.
        warnings.append(
            backend_warn or "keychain backend unavailable"
        )
    if home_mode is None:
        if _IS_WINDOWS:
            warnings.append(
                "home mode not checkable on Windows; review DACLs manually"
            )
        else:
            warnings.append(
                "home mode is unreadable; cannot confirm 0o700"
            )
    elif not home_mode_ok:
        warnings.append(
            f"home mode is {home_mode}, expected {_HOME_MODE_PRIVATE} — "
            "another local user may read this directory"
        )
    posture_ok = not warnings
    posture_warning = None if posture_ok else "; ".join(warnings)

    return {
        "home": str(home),
        "home_mode": home_mode,
        "home_mode_ok": home_mode_ok,
        "keychain_backend": backend,
        "keychain_ok": backend_ok,
        "posture_ok": posture_ok,
        "posture_warning": posture_warning,
        "bind": "127.0.0.1",
        "live_arm_ui_allowed": False,
        "trade_only_required": True,
    }


__all__ = ["trust_snapshot"]
