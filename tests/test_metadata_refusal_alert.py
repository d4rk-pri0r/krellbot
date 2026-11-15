"""A journalled ``metadata_refusal`` must surface as an Operations alert.

Pins M2.5: when a tick records ``metadata_refusal``, ``alerts.collect``
returns an unacknowledged warning alert for that refusal. No silent
skip — a fake home + journal fixture is enough; the collector never
creates files on a read-only collect.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

from krellbot.application import alerts
from krellbot.data.instruments import METADATA_UNAVAILABLE


def _append_journal_record(home: Path, record: dict) -> None:
    """Append one journal record using the UTC month file naming scheme."""

    journal_dir = home / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    utc = datetime.datetime.fromtimestamp(int(record["ts"]), tz=datetime.timezone.utc)
    file_path = journal_dir / f"{utc:%Y-%m}.jsonl"
    fd = os.open(str(file_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        line = json.dumps(record, separators=(",", ":")) + "\n"
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def test_metadata_refusal_tick_yields_unacknowledged_alert(home: Path) -> None:
    """A tick whose detail carries ``metadata_refusal`` becomes an
    unacknowledged Operations alert after collect."""

    ts = 1_700_000_000
    _append_journal_record(
        home,
        {
            "ts": ts,
            "kind": "tick",
            "venue": "kraken",
            "pack": "trend-follow",
            "bar_ts": ts,
            "detail": {
                "pair": "BTCUSD",
                "reason": "no_signal",
                "metadata_refusal": METADATA_UNAVAILABLE,
                "intent_refused": None,
            },
        },
    )

    before = set()
    if home.exists():
        for root, _dirs, files in os.walk(home):
            rel = Path(root).relative_to(home)
            for name in files:
                before.add(str(rel / name))

    result = alerts.collect(home, now=ts + 60)
    assert len(result) == 1, result
    alert = result[0]
    assert alert.kind == "metadata_refusal", alert
    assert alert.code == METADATA_UNAVAILABLE, alert
    assert alert.severity == "warning", alert
    assert alert.venue == "kraken", alert
    assert alert.pair == "BTCUSD", alert
    assert alert.count == 1, alert
    assert alert.first_ts == ts, alert
    assert alert.last_ts == ts, alert
    assert alert.acknowledged is False, alert

    after = set()
    for root, _dirs, files in os.walk(home):
        rel = Path(root).relative_to(home)
        for name in files:
            after.add(str(rel / name))
    assert before == after, (before, after)


def test_null_metadata_refusal_does_not_alert(home: Path) -> None:
    """Ticks that journal ``metadata_refusal: null`` stay silent."""

    ts = 1_700_000_100
    _append_journal_record(
        home,
        {
            "ts": ts,
            "kind": "tick",
            "venue": "kraken",
            "pack": "trend-follow",
            "bar_ts": ts,
            "detail": {
                "pair": "BTCUSD",
                "reason": "no_signal",
                "metadata_refusal": None,
                "intent_refused": None,
            },
        },
    )
    result = alerts.collect(home, now=ts + 1)
    assert result == [], result
