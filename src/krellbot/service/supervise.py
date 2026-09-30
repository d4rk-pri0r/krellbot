"""Supervision helpers for the scheduled tick.

The OS scheduler fires ``krellbot tick`` (or ``krellbot.service.runner``,
which delegates) on an hourly cadence. After a sleep/wake cycle the gap
between scheduled firings can be much larger than an hour. ``record_wake_gap``
detects that gap and journals a ``kind=supervision / event=wake_gap`` record
so the operator and the doctor can see a long absence happened.

The wake-gap check fires *before* the tick evaluates the latest bar: it is a
supervision signal, not a backfill request. The engine itself does no replay
of missed bars; ``run.tick`` already coalesces by feeding every candle up to
the latest into ``evaluate.run`` so the indicator state is correct on the
post-wake bar, and outbox coids prevent a duplicate send for a bar that was
already sent.
"""

from __future__ import annotations

import json
from pathlib import Path

from krellbot import doctor
from krellbot import journal as kb_journal


def last_tick_ts(home: Path, venue: str) -> int | None:
    """Return the maximum ``ts`` of ``kind=tick`` journal records for ``venue``.

    Skips unparseable lines. Returns None when no tick record exists for
    the venue. ``home`` is the krellbot data home (does not create it).
    """
    journal_dir = Path(home) / "journal"
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
            if rec.get("kind") != "tick":
                continue
            if rec.get("venue") != venue:
                continue
            try:
                ts = int(rec.get("ts", 0) or 0)
            except (TypeError, ValueError):
                continue
            if ts <= 0:
                continue
            found = True
            latest_ts = max(latest_ts, ts)
    if not found:
        return None
    return latest_ts


def record_wake_gap(
    home: Path,
    venue: str,
    *,
    now: int,
    threshold: int = doctor.TICK_STALE_SECONDS,
) -> int | None:
    """Journal a wake-gap record when the gap since the last tick is large.

    When ``last_tick_ts`` is not None and ``now - last >= threshold``, a
    journal record of the form::

        {"ts": now, "kind": "supervision", "venue": venue,
         "pack": "-", "bar_ts": 0,
         "detail": {"event": "wake_gap", "gap_s": now - last,
                    "last_tick_ts": last}}

    is appended and the gap in seconds is returned. Otherwise (no tick
    record, or the gap is below the threshold) nothing is journaled and
    None is returned. Failures to journal (e.g. read-only home) are
    swallowed so the tick itself is never blocked by supervision IO.
    """
    last = last_tick_ts(home, venue)
    if last is None:
        return None
    gap = int(now) - int(last)
    if gap < int(threshold):
        return None
    try:
        kb_journal.append(
            {
                "ts": int(now),
                "kind": "supervision",
                "venue": venue,
                "pack": "-",
                "bar_ts": 0,
                "detail": {
                    "event": "wake_gap",
                    "gap_s": gap,
                    "last_tick_ts": int(last),
                },
            }
        )
    except (OSError, ValueError):
        pass
    return gap


def latest_wake_gap(home: Path, venue: str | None = None) -> int | None:
    """Return the ``gap_s`` of the newest ``wake_gap`` record, or None.

    When ``venue`` is None, looks across all venues. ``home`` is the
    data home and is not created.
    """
    journal_dir = Path(home) / "journal"
    if not journal_dir.is_dir():
        return None
    newest_ts = -1
    newest_gap: int | None = None
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
            if rec.get("kind") != "supervision":
                continue
            detail = rec.get("detail") or {}
            if detail.get("event") != "wake_gap":
                continue
            if venue is not None and rec.get("venue") != venue:
                continue
            try:
                ts = int(rec.get("ts", 0) or 0)
            except (TypeError, ValueError):
                continue
            if ts < newest_ts:
                continue
            newest_ts = ts
            try:
                newest_gap = int(detail.get("gap_s", 0) or 0)
            except (TypeError, ValueError):
                newest_gap = None
    return newest_gap


def resolve_owner(home: Path) -> dict | None:
    """Parse the default owner file, returning the supervisor record or None.

    Returns None when the owner file does not exist. Keys are sorted
    alphabetically. ``home`` is the data home; it is not created here.
    """
    owner = Path(home) / "service" / "owners" / "default.owner"
    if not owner.exists():
        return None
    try:
        text = owner.read_text(encoding="utf-8")
    except OSError:
        return None
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        out[key] = value
    return out or None
