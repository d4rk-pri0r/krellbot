"""Local filesystem layout and atomic writes.

All krellbot state lives under $KRELLBOT_HOME (falling back to ~/.krellbot).
The directory tree is created on demand with mode 0o700 on POSIX so a shared
host cannot read the secrets and journal. atomic_write writes to a sibling
.tmp file then os.replace()s into place, so a crash mid-write never leaves
the live file half-written and never leaves a stray .tmp behind.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_IS_WINDOWS = sys.platform == "win32"
_LAYOUT_DIRS = ("packs", "packs/community", "catalog", "cache", "run", "journal", "receipts")


def home() -> Path:
    """Return the krellbot home directory, creating it if necessary."""
    base = os.environ.get("KRELLBOT_HOME")
    if base:
        path = Path(base)
    else:
        path = Path.home() / ".krellbot"
    path.mkdir(parents=True, exist_ok=True)
    if not _IS_WINDOWS:
        os.chmod(path, 0o700)
    return path


def ensure_layout() -> Path:
    """Return home() with the standard subdirectories present (mode 0o700)."""
    root = home()
    for name in _LAYOUT_DIRS:
        sub = root / name
        sub.mkdir(parents=True, exist_ok=True)
        if not _IS_WINDOWS:
            os.chmod(sub, 0o700)
    return root


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Write data to path via a sibling .tmp then os.replace.

    If os.replace raises, the original file (if any) is unchanged and the
    .tmp sibling is removed before the exception propagates.
    """
    tmp = path.with_name(path.name + ".tmp")
    # O_BINARY: without it, Windows opens in text mode and os.write turns every
    # "\n" into "\r\n", so the bytes on disk stop matching what the caller hashed.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    fd = os.open(str(tmp), flags, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    os.close(fd)
    if not _IS_WINDOWS:
        os.chmod(tmp, mode)
    try:
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    if not _IS_WINDOWS:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
