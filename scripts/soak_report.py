"""Paper soak coverage report from the journal.

Owner run (M1.12)::

    uv run --no-sync python scripts/soak_report.py --days 7

Prints ``PASS`` only when every hour in the window has a ``kind=tick``
journal record, consecutive ticks never gap by more than two hours, no
unresolved ``needs_reconcile`` row remains, and no stale-data alert falls
in the window. Otherwise prints each failing hour (UTC, one per line).
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

from krellbot import paths as kb_paths
from krellbot.doctor import TICK_STALE_SECONDS

HOUR_SECONDS = 3600
# "Gap over two hours" — strictly greater than the doctor stale threshold.
MAX_GAP_SECONDS = TICK_STALE_SECONDS
STALE_DATA_REASON = "stale_data"
WAKE_GAP_EVENT = "wake_gap"
OPS_DB_FILENAME = "ops.sqlite"


def hour_floor(ts: int) -> int:
    """Return the UTC hour start containing ``ts``."""
    return (int(ts) // HOUR_SECONDS) * HOUR_SECONDS


def window_hour_starts(*, now: int, days: int) -> list[int]:
    """Complete UTC hours in ``[now - days, hour_floor(now))``."""
    if days < 1:
        raise ValueError("days must be >= 1")
    end = hour_floor(now)
    start = end - int(days) * 24 * HOUR_SECONDS
    return list(range(start, end, HOUR_SECONDS))


def format_hour(hour_ts: int) -> str:
    """Format an hour start as ``YYYY-MM-DDTHH:00:00Z``."""
    from datetime import datetime, timezone

    return datetime.fromtimestamp(int(hour_ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:00:00Z")


def _iter_journal_records(home: Path) -> list[dict]:
    """Read every parseable JSON object from ``<home>/journal/*.jsonl``."""
    journal_dir = Path(home) / "journal"
    if not journal_dir.is_dir():
        return []
    out: list[dict] = []
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
            if isinstance(rec, dict):
                out.append(rec)
    return out


def _tick_timestamps(records: list[dict]) -> list[int]:
    stamps: list[int] = []
    for rec in records:
        if rec.get("kind") != "tick":
            continue
        try:
            ts = int(rec.get("ts", 0) or 0)
        except (TypeError, ValueError):
            continue
        if ts > 0:
            stamps.append(ts)
    return sorted(stamps)


def _stale_alert_hours(records: list[dict], *, start: int, end: int) -> set[int]:
    """Hours that carry a stale-data alert inside ``[start, end)``.

    Sources (journal only):

    * ``kind=tick`` with ``detail.reason == \"stale_data\"``
    * ``kind=supervision`` with ``detail.event == \"wake_gap\"``
    """
    hours: set[int] = set()
    for rec in records:
        kind = rec.get("kind")
        detail = rec.get("detail")
        if not isinstance(detail, dict):
            detail = {}
        try:
            ts = int(rec.get("ts", 0) or 0)
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        hour = hour_floor(ts)
        if hour < start or hour >= end:
            continue
        if (kind == "tick" and detail.get("reason") == STALE_DATA_REASON) or (
            kind == "supervision" and detail.get("event") == WAKE_GAP_EVENT
        ):
            hours.add(hour)
    return hours


def _has_unresolved_reconcile(home: Path) -> bool:
    """True when ``ops.sqlite`` has a ``needs_reconcile`` ledger row.

    Missing store is clean. Opening the store never creates the file.
    """
    path = Path(home) / OPS_DB_FILENAME
    if not path.exists():
        return False
    from krellbot.storage.database import OperationalStore, StoreBusy, StoreCorrupt

    try:
        rows = OperationalStore(path).read_ledger()
    except (StoreBusy, StoreCorrupt, OSError):
        # Unreadable store: fail closed.
        return True
    for _row_id, kind, _payload in rows:
        if kind == "needs_reconcile":
            return True
    return False


def _hours_in_gap(prev_ts: int, next_ts: int, hour_starts: list[int]) -> set[int]:
    """Window hours that overlap the open gap interval ``(prev_ts, next_ts)``."""
    out: set[int] = set()
    for hour in hour_starts:
        if hour + HOUR_SECONDS > prev_ts and hour < next_ts:
            out.add(hour)
    return out


def failing_hours(
    home: Path,
    *,
    days: int,
    now: int | None = None,
) -> list[int]:
    """Return sorted UTC hour starts that fail soak criteria."""
    now_ts = int(time.time()) if now is None else int(now)
    hour_starts = window_hour_starts(now=now_ts, days=days)
    if not hour_starts:
        return []
    start = hour_starts[0]
    end = hour_starts[-1] + HOUR_SECONDS

    records = _iter_journal_records(home)
    ticks = _tick_timestamps(records)
    covered = {hour_floor(ts) for ts in ticks if start <= ts < end}

    failing: set[int] = set()
    for hour in hour_starts:
        if hour not in covered:
            failing.add(hour)

    # Consecutive-tick gap check. Include ticks just outside the window so
    # a hole that straddles the boundary still surfaces.
    bracketed = [ts for ts in ticks if start - MAX_GAP_SECONDS <= ts <= end + MAX_GAP_SECONDS]
    for prev_ts, next_ts in itertools.pairwise(bracketed):
        if next_ts - prev_ts > MAX_GAP_SECONDS:
            failing.update(_hours_in_gap(prev_ts, next_ts, hour_starts))

    # Unresolved reconcile is a global soak failure: every hour fails.
    if _has_unresolved_reconcile(Path(home)):
        failing.update(hour_starts)

    failing.update(_stale_alert_hours(records, start=start, end=end))
    return sorted(failing)


def evaluate(
    home: Path,
    *,
    days: int,
    now: int | None = None,
) -> str:
    """Return ``PASS`` or a newline-joined list of failing hours."""
    fails = failing_hours(home, days=days, now=now)
    if not fails:
        return "PASS"
    return "\n".join(format_hour(h) for h in fails)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paper soak coverage report from the journal.")
    parser.add_argument(
        "--days",
        type=int,
        required=True,
        help="Number of complete days (24h blocks) to inspect ending at the current hour.",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    home: Path | None = None,
    clock: Callable[[], float] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    if args.days < 1:
        print("days must be >= 1", file=sys.stderr)
        return 2
    root = Path(home) if home is not None else kb_paths.home()
    now = int((clock or time.time)())
    body = evaluate(root, days=args.days, now=now)
    print(body)
    return 0 if body == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
