"""Append-only, redacted journal under $KRELLBOT_HOME/journal/.

Each record is one JSON object per line, file-per-month, mode 0o600 on POSIX.
Records are walked through sanitize.redact before serialization so a stray
secret string never lands in the journal.

Browse helpers mirror the CLI ``krellbot journal --tail N | --since 24h|14d
[--json]`` selection subset for the web API: fixed since-windows, positive
tail, and export-time secret-field dropping. Optional ``mode=paper|live``
filters classify records for the Operations journal panel (M20.5).
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

# Web browse mode filter values (``?mode=paper|live``).
BROWSE_MODES = frozenset({"paper", "live"})

# Live refuse / fence reasons journalled by the live tick path (no ``detail.mode``).
_LIVE_REASON_MARKERS = frozenset({"live_refused", "live_fenced"})

DEFAULT_TAIL = 5


class BrowseError(ValueError):
    """Invalid journal browse parameters (maps to HTTP 400 / CLI exit 2)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def classify_mode(record: dict) -> str:
    """Return ``paper`` or ``live`` for a journal record.

    Prefer an explicit ``detail.mode`` when present. Otherwise treat
    ``live_refused`` / ``live_fenced`` ticks as live. Unlabeled historical
    ticks default to paper (same posture as paper-history projection).
    """

    detail = record.get("detail")
    if isinstance(detail, dict):
        explicit = detail.get("mode")
        if explicit in BROWSE_MODES:
            return str(explicit)
        reason = detail.get("reason")
        if reason in _LIVE_REASON_MARKERS:
            return "live"
    return "paper"


def summarize_record(record: dict, *, mode: str | None = None) -> str:
    """One human-readable line for Operations journal browse.

    Mirrors CLI tick summary intent without importing CLI (or risk paths).
    Always safe after ``drop_export_secret_fields``.
    """

    kind = str(record.get("kind") or "")
    detail = record.get("detail")
    resolved_mode = mode if mode in BROWSE_MODES else classify_mode(record)

    if not isinstance(detail, dict):
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        return kind or "—"

    pair = str(detail.get("pair") or "")
    venue = str(record.get("venue") or "")
    pack = str(record.get("pack") or "")
    reason = detail.get("reason")
    head = f"{venue} {pair} {pack} ({resolved_mode}):".strip()
    head = " ".join(head.split())

    def qty(key: str) -> str:
        return str(detail.get(key) or "0")

    if reason == "live_refused":
        code = detail.get("code") or "refused"
        return f"live refused: {code}" + (f" ({pair})" if pair else "")
    if reason == "live_fenced":
        code = detail.get("code") or "fenced"
        return f"live fenced: {code}" + (f" ({pair})" if pair else "")
    if reason == "store_refused":
        code = detail.get("code") or "store_refused"
        return f"refused: {code}" + (f" ({pair})" if pair else "")
    intent = detail.get("intent_refused")
    if intent:
        return f"refused: {intent}" + (f" ({pair})" if pair else "")

    if kind == "tick":
        if reason == "entry" and qty("entry_qty") not in ("0", "0.0"):
            return f"{head} bought {qty('entry_qty')}, protective stop resting"
        if reason == "exit" and qty("exit_qty") not in ("0", "0.0"):
            return f"{head} sold {qty('exit_qty')}"
        if qty("stop_qty") not in ("0", "0.0"):
            return f"{head} stop filled, sold {qty('stop_qty')}"
        owned = qty("owned_qty_after")
        if reason == "no_candles":
            return f"{head} no closed candle yet, nothing to do"
        if reason == "warmup":
            return f"{head} warming up indicators, no trade"
        if owned not in ("0", "0.0"):
            return f"{head} holding {owned}, stop resting"
        if reason:
            return f"{head} {reason}"
        return f"{head} no signal, staying flat"

    if reason:
        return f"{kind}: {reason}" + (f" ({pair})" if pair else "")
    event = detail.get("event")
    if event:
        return f"{kind}: {event}"
    try:
        return json.dumps(detail, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        return kind or "—"


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
    mode: str | None = None,
    now: float | None = None,
) -> list[dict]:
    """Select journal records with CLI ``journal`` filter parity.

    - ``mode`` in ``{paper, live}``: keep only matching records
      (``classify_mode``), applied **before** tail/since so "last 5 live"
      means the last five live-classified events.
    - ``since`` in ``{24h, 14d}``: keep records whose ``ts`` is an int and
      ``ts >= now - window``. When ``since`` is set it wins; ``tail`` is
      ignored for selection (same as the CLI when both flags appear).
    - otherwise: return the last ``tail`` records (default ``DEFAULT_TAIL``).
    - Always returns export-redacted copies (``--json`` field drop) with
      projected sibling fields ``mode`` and ``summary`` for the web UI.

    Raises ``BrowseError`` with ``code`` ``invalid_tail``,
    ``unsupported_since``, or ``unsupported_mode`` for refused parameters.
    """

    if mode is not None and mode not in BROWSE_MODES:
        raise BrowseError(
            "unsupported_mode",
            f"unsupported mode value: {mode!r}; use one of paper, live",
        )

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

    if mode is not None:
        records = [r for r in records if classify_mode(r) == mode]

    if since is not None:
        if now is None:
            now = time.time()
        threshold = int(now) - WINDOW_SECONDS[since]
        selected = [r for r in records if isinstance(r.get("ts"), int) and r["ts"] >= threshold]
    else:
        assert tail is not None
        selected = records[-tail:]

    projected: list[dict] = []
    for raw in selected:
        cleaned = drop_export_secret_fields(raw)
        if not isinstance(cleaned, dict):
            continue
        # Classify from the source record (secret drop never removes mode/reason).
        classified = classify_mode(raw if isinstance(raw, dict) else cleaned)
        out = dict(cleaned)
        out["mode"] = classified
        out["summary"] = summarize_record(cleaned, mode=classified)
        projected.append(out)
    return projected
