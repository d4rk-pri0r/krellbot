"""Soak report prints PASS only for a clean hourly journal window.

Pins ``scripts/soak_report.py``: every hour must have a tick, consecutive
ticks must not gap over two hours, unresolved reconcile and stale-data
alerts fail the soak, and PASS requires ≥1 journalled evaluated entry
decision (not a pure ``metadata_refusal``). Uses an isolated
``KRELLBOT_HOME`` and never contacts a venue.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from krellbot.storage.database import OperationalStore
from krellbot.storage.outbox import audit_needs_reconcile
from scripts.soak_report import (
    HOUR_SECONDS,
    evaluate,
    failing_hours,
    format_hour,
    hour_floor,
    main,
    window_hour_starts,
)

# Fixed "now": 2026-11-15 12:30:00 UTC → window ends at 12:00 UTC.
NOW = int(datetime.datetime(2026, 11, 15, 12, 30, 0, tzinfo=datetime.timezone.utc).timestamp())


def _write_tick(
    home: Path,
    ts: int,
    *,
    reason: str | None = None,
    metadata_refusal: str | None = None,
) -> None:
    journal_dir = home / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    month = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m")
    path = journal_dir / f"{month}.jsonl"
    detail: dict = {"pair": "XBTUSD"}
    if reason is not None:
        detail["reason"] = reason
    if metadata_refusal is not None:
        detail["metadata_refusal"] = metadata_refusal
    rec = {
        "ts": ts,
        "kind": "tick",
        "venue": "kraken",
        "pack": "soak-pack",
        "bar_ts": hour_floor(ts),
        "detail": detail,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, separators=(",", ":")) + "\n")


def _write_wake_gap(home: Path, ts: int, *, gap_s: int) -> None:
    journal_dir = home / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    month = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m")
    path = journal_dir / f"{month}.jsonl"
    rec = {
        "ts": ts,
        "kind": "supervision",
        "venue": "kraken",
        "pack": "-",
        "bar_ts": 0,
        "detail": {"event": "wake_gap", "gap_s": gap_s, "last_tick_ts": ts - gap_s},
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, separators=(",", ":")) + "\n")


def _seed_hourly_ticks(
    home: Path,
    *,
    days: int,
    now: int = NOW,
    skip: set[int] | None = None,
    decision_reason: str | None = "flat",
) -> list[int]:
    """Write one tick at the start of each window hour; optionally skip some.

    By default each tick carries an evaluated pack ``reason`` so hourly
    coverage alone is not mistaken for a coverage-only soak. Pass
    ``decision_reason=None`` for coverage-only fixtures.
    """
    skip = skip or set()
    hours = window_hour_starts(now=now, days=days)
    for hour in hours:
        if hour in skip:
            continue
        _write_tick(home, hour + 60, reason=decision_reason)  # one minute into the hour
    return hours


def test_full_hourly_coverage_prints_pass(home: Path) -> None:
    """A tick in every hour with no gaps, reconcile, or stale alert → PASS."""
    _seed_hourly_ticks(home, days=1, now=NOW)
    assert evaluate(home, days=1, now=NOW) == "PASS"
    assert failing_hours(home, days=1, now=NOW) == []


def test_coverage_only_journal_without_entry_evaluation_fails(home: Path) -> None:
    """Hourly ticks with no pack-evaluator reason must not PASS the soak."""
    hours = _seed_hourly_ticks(home, days=1, now=NOW, decision_reason=None)
    fails = failing_hours(home, days=1, now=NOW)
    assert fails == hours
    assert evaluate(home, days=1, now=NOW) != "PASS"


def test_metadata_refusal_only_journal_fails(home: Path) -> None:
    """Ticks whose outcome is only metadata_refusal are not evaluated decisions."""
    hours = window_hour_starts(now=NOW, days=1)
    for hour in hours:
        _write_tick(home, hour + 60, reason="entry", metadata_refusal="metadata_unavailable")
    fails = failing_hours(home, days=1, now=NOW)
    assert fails == hours
    assert evaluate(home, days=1, now=NOW) != "PASS"


def test_one_evaluated_entry_decision_allows_pass(home: Path) -> None:
    """≥1 evaluated entry decision in an otherwise clean window → PASS."""
    hours = _seed_hourly_ticks(home, days=1, now=NOW, decision_reason=None)
    _write_tick(home, hours[0] + 90, reason="entry")
    assert evaluate(home, days=1, now=NOW) == "PASS"
    assert failing_hours(home, days=1, now=NOW) == []


def test_missing_hour_is_printed(home: Path) -> None:
    """A window hour with no tick is listed as a failing hour."""
    hours = _seed_hourly_ticks(home, days=1, now=NOW, skip={window_hour_starts(now=NOW, days=1)[3]})
    missing = hours[3]
    body = evaluate(home, days=1, now=NOW)
    assert body != "PASS"
    assert format_hour(missing) in body.splitlines()
    assert failing_hours(home, days=1, now=NOW) == [missing]


def test_gap_over_two_hours_marks_hours_in_the_hole(home: Path) -> None:
    """Consecutive ticks more than two hours apart fail the hours in the gap."""
    hours = window_hour_starts(now=NOW, days=1)
    # Tick hour 0 and hour 3 only — gap from ~H0 to ~H3 is > 2h; H1 and H2 missing.
    _write_tick(home, hours[0] + 10, reason="flat")
    _write_tick(home, hours[3] + 10, reason="flat")
    # Fill the rest so only the gap region fails for missing/gap reasons.
    for hour in hours:
        if hour in {hours[0], hours[1], hours[2], hours[3]}:
            continue
        _write_tick(home, hour + 10, reason="flat")
    fails = failing_hours(home, days=1, now=NOW)
    assert hours[1] in fails
    assert hours[2] in fails
    body = evaluate(home, days=1, now=NOW)
    assert format_hour(hours[1]) in body
    assert format_hour(hours[2]) in body
    assert "PASS" not in body


def test_unresolved_reconcile_fails_every_hour(home: Path) -> None:
    """An outstanding needs_reconcile row fails the whole soak window."""
    hours = _seed_hourly_ticks(home, days=1, now=NOW)
    store = OperationalStore(home / "ops.sqlite")
    audit_needs_reconcile(store, coid="stuck-coid")
    fails = failing_hours(home, days=1, now=NOW)
    assert fails == hours
    assert evaluate(home, days=1, now=NOW) != "PASS"


def test_stale_data_tick_reason_fails_that_hour(home: Path) -> None:
    """A tick whose detail.reason is stale_data fails its hour."""
    hours = _seed_hourly_ticks(home, days=1, now=NOW)
    target = hours[5]
    # Overwrite/add an explicit stale_data tick in that hour.
    _write_tick(home, target + 120, reason="stale_data")
    fails = failing_hours(home, days=1, now=NOW)
    assert fails == [target]
    assert evaluate(home, days=1, now=NOW) == format_hour(target)


def test_wake_gap_supervision_is_a_stale_data_alert(home: Path) -> None:
    """A supervision wake_gap record in the window fails its hour."""
    hours = _seed_hourly_ticks(home, days=1, now=NOW)
    target = hours[7]
    _write_wake_gap(home, target + 30, gap_s=3 * HOUR_SECONDS)
    assert failing_hours(home, days=1, now=NOW) == [target]


def test_cli_days_flag_prints_pass_and_exits_zero(home: Path, capsys) -> None:
    """``--days`` drives the window; clean coverage exits 0 with PASS."""
    _seed_hourly_ticks(home, days=1, now=NOW)
    rc = main(["--days", "1"], home=home, clock=lambda: NOW)
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.strip() == "PASS"


def test_cli_prints_failing_hours_and_exits_nonzero(home: Path, capsys) -> None:
    """Missing coverage exits 1 and prints each failing hour, not PASS."""
    hours = _seed_hourly_ticks(home, days=1, now=NOW, skip={window_hour_starts(now=NOW, days=1)[0]})
    rc = main(["--days", "1"], home=home, clock=lambda: NOW)
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out.strip() == format_hour(hours[0])
