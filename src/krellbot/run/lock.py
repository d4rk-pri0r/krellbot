"""Per-venue file lock for the tick loop.

On POSIX the lock is an `fcntl.flock` on `<home>/run/<venue>.lock`. On Windows
the lock is best-effort via `msvcrt.locking`. The lock is non-blocking: if the
file is already held, `TickLock.acquire()` returns False and the caller exits
0 with `another tick running`. The lock file is removed only when the lock is
released in the same process (no stale removal across processes).
"""

from __future__ import annotations

import os
from pathlib import Path


class TickLock:
    """Acquire `<home>/run/<venue>.lock`. Released on close()."""

    def __init__(self, home: Path, venue: str) -> None:
        self._lock_path = Path(home) / "run" / f"{venue}.lock"
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fd: int | None = None
        self._is_windows = os.name == "nt"

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True on success, False if held."""
        if self._fd is not None:
            return True
        flags = os.O_RDWR | os.O_CREAT
        fd = os.open(str(self._lock_path), flags, 0o600)
        try:
            if self._is_windows:
                import msvcrt

                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                except OSError:
                    os.close(fd)
                    return False
            else:
                import fcntl

                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except (BlockingIOError, OSError):
                    os.close(fd)
                    return False
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        self._fd = fd
        return True

    def release(self) -> None:
        """Release the lock and remove the file. Safe to call when not held."""
        if self._fd is None:
            return
        fd = self._fd
        self._fd = None
        try:
            if self._is_windows:
                import msvcrt

                try:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                self._lock_path.unlink()
            except FileNotFoundError:
                pass

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
