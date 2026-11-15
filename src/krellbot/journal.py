"""Append-only, redacted journal under $KRELLBOT_HOME/journal/.

Each record is one JSON object per line, file-per-month, mode 0o600 on POSIX.
Records are walked through sanitize.redact before serialization so a stray
secret string never lands in the journal.

Browse helpers mirror the CLI ``krellbot journal --tail N | --since 24h|14d
[--json]`` selection subset for the web API: fixed since-windows, positive
tail, and export-time secret-field dropping.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from krellbot import paths, sanitize

_REQUIRED_KEYS = ("ts", "kind", "venue", "pack", "bar_ts", "detail")
_IS_WINDOWS = sys.platform == "win32"

# CLI ``--since`` windows (seconds). Only these two values are accepted.
WINDOW_SECONDS: dict[str, int] = {"24h": 24 * 3600, "14d": 14 * 86400}

# Fields dropped for CLI ``--json`` / web journal export (any depth).
_EXPORT_SECRET_FIELDS = ("key", "secret", "license", "balance")

DEFAULT_TAIL = 5


class BrowseError(ValueError):
    """Invalid journal browse parameters (maps to HTTP 400 / CLI exit 2)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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


def drop_export_secret_fields(record: Any) -> Any:
    """Recursively drop ``key``, ``secret``, ``license``, ``balance``.

    Matches CLI ``krellbot journal --json`` so web browse never returns
    those fields even if a pre-redact line somehow retained them.
    """

    if isinstance(record, dict):
        return {k: drop_export_secret_fields(v) for k, v in record.items() if k not in _EXPORT_SECRET_FIELDS}
    if isinstance(record, list):
        return [drop_export_secret_fields(v) for v in record]
    return record


def read_records_lenient(home: Path) -> list[dict]:
    """Return valid dict journal records under ``home/journal``, oldest first.

    Malformed lines and unreadable files are skipped (API/history style),
    never fatal: a torn last line must not take the browse panel down.
    Non-dict JSON values are skipped.
    """

    journal_dir = Path(home) / "journal"
    if not journal_dir.is_dir():
        return []
    records: list[dict] = []
    for path in sorted(journal_dir.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def browse(
    home: Path,
    *,
    tail: int | None = None,
    since: str | None = None,
    now: float | None = None,
) -> list[dict]:
    """Select journal records with CLI ``journal`` filter parity.

    - ``since`` in ``{24h, 14d}``: keep records whose ``ts`` is an int and
      ``ts >= now - window``. When ``since`` is set it wins; ``tail`` is
      ignored for selection (same as the CLI when both flags appear).
    - otherwise: return the last ``tail`` records (default ``DEFAULT_TAIL``).
    - Always returns export-redacted copies (``--json`` field drop).

    Raises ``BrowseError`` with ``code`` ``invalid_tail`` or
    ``unsupported_since`` for refused parameters.
    """

    if since is not None and since not in WINDOW_SECONDS:
        raise BrowseError(
            "unsupported_since",
            f"unsupported --since value: {since!r}; use one of 24h, 14d",
        )

    if since is None and tail is None:
        tail = DEFAULT_TAIL

    # Validate an explicit (or defaulted) tail even when since later wins
    # for selection — CLI parses --tail before applying either filter.
    if tail is not None and (not isinstance(tail, int) or isinstance(tail, bool) or tail < 1):
        raise BrowseError("invalid_tail", f"invalid --tail: {tail}")

    records = read_records_lenient(home)
    if not records:
        return []

    if since is not None:
        if now is None:
            now = time.time()
        threshold = int(now) - WINDOW_SECONDS[since]
        selected = [r for r in records if isinstance(r.get("ts"), int) and r["ts"] >= threshold]
    else:
        assert tail is not None
        selected = records[-tail:]

    return [drop_export_secret_fields(r) for r in selected]
