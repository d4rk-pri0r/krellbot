"""Append-only, redacted journal under $KRELLBOT_HOME/journal/.

Each record is one JSON object per line, file-per-month, mode 0o600 on POSIX.
Records are walked through sanitize.redact before serialization so a stray
secret string never lands in the journal.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

from krellbot import paths, sanitize

_REQUIRED_KEYS = ("ts", "kind", "venue", "pack", "bar_ts", "detail")
_IS_WINDOWS = sys.platform == "win32"


def append(record: dict) -> Path:
    """Append one record to this-month's journal file. Returns the file path."""
    for key in _REQUIRED_KEYS:
        if key not in record:
            raise ValueError(f"journal record missing '{key}'")

    utc_ts = datetime.datetime.fromtimestamp(int(record["ts"]), tz=datetime.timezone.utc)
    journal_dir = paths.ensure_layout() / "journal"
    file_path = journal_dir / f"{utc_ts:%Y-%m}.jsonl"

    safe = sanitize.redact(record)

    fd = os.open(str(file_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        with os.fdopen(fd, "a", encoding="utf-8", newline="\n", closefd=False) as fh:
            fh.write(json.dumps(safe, separators=(",", ":"), ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    if not _IS_WINDOWS:
        os.chmod(file_path, 0o600)
    return file_path
