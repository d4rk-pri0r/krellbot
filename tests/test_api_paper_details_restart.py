"""Persist real paper stops, then read them in new API instances/interpreters.

Synthetic local orders only: place_stop does not buy or infer an owned fill.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.venues.paper import PaperVenue, default_rules
from tests.test_api_paper_details import (
    _arm,
    _assert_repeated_reads,
    _expected,
    _session,
    _snapshot,
)
from tests.test_ns06_api import _build_app

pytestmark = pytest.mark.usefixtures("fresh_keyring")


def _venue(home: Path) -> PaperVenue:
    return PaperVenue("kraken", rules_provider=default_rules, candle_reader=lambda venue, pair: [], home=home)


# A new interpreter imports the real API, bootstraps a new session, and GETs
# through the same ASGI transport as the existing API security tests.
_CHILD = """
import json, os, sys
from pathlib import Path
from tests.test_api_paper_details import _get, _session
from tests.test_ns06_api import _build_app
app = _build_app(Path(sys.argv[1]))
session = _session(app)
reads = []
for _ in range(3):
    status, headers, raw, cookies = _get(app, session)
    reads.append({'status': status, 'headers': headers, 'body': json.loads(raw), 'cookies': cookies})
print(json.dumps({'pid': os.getpid(), 'reads': reads}))
"""


def _read_new_process(home: Path, expected: dict) -> dict:
    before = _snapshot(home)
    result = subprocess.run(
        [sys.executable, "-c", _CHILD, str(home)], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    record = json.loads(result.stdout)
    assert record["pid"] != os.getpid()
    for read in record["reads"]:
        assert read["status"] == 200, read
        assert read["body"] == expected
        assert [v for k, v in read["headers"] if k.lower() == "cache-control"] == ["no-store"]
        assert read["cookies"] == []
    assert _snapshot(home) == before
    print("fresh-interpreter paper details:", json.dumps(record, sort_keys=True))
    return record


def test_persisted_stop_and_raise_survive_new_app_without_reads_mutating_state(home: Path) -> None:
    _arm(home)
    venue = _venue(home)
    venue.place_stop("synthetic-protection", Decimal("5"), Decimal("3.8"), pair="SUIUSD")
    path = home / "run" / "paper-kraken.json"
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["open_orders"][0]["stop_price"] == "3.8000"
    assert persisted["recent_fills"] == []
    assert persisted["balances"] == {}
    first_app = _build_app(home)
    _assert_repeated_reads(first_app, home, _session(first_app), _expected(resting_stop="3.8"))

    # A different venue instance loads and updates the durable stop. The old
    # app must not cache it; a fresh app must recover it without engine work.
    _venue(home).raise_stop("SUIUSD", Decimal("4.125"))
    second_app = _build_app(home)
    _assert_repeated_reads(second_app, home, _session(second_app), _expected(resting_stop="4.125"))
    old_session = next(iter(first_app.state.krellbot.sessions))
    _assert_repeated_reads(first_app, home, old_session, _expected(resting_stop="4.125"))
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["recent_fills"] == []
    assert persisted["balances"] == {}


def test_new_process_reads_durable_stop_then_later_update_not_initial_setting(home: Path) -> None:
    _arm(home)
    venue = _venue(home)
    venue.place_stop("synthetic-protection", Decimal("5"), Decimal("3.8"), pair="SUIUSD")
    first = _read_new_process(home, _expected(resting_stop="3.8"))
    # First interpreter has exited before a real local venue updates state.
    _venue(home).raise_stop("SUIUSD", Decimal("4.125"))
    second = _read_new_process(home, _expected(resting_stop="4.125"))
    assert second["pid"] != first["pid"]
    persisted = json.loads((home / "run" / "paper-kraken.json").read_text(encoding="utf-8"))
    assert persisted["recent_fills"] == []
    assert persisted["balances"] == {}
    assert list((home / "journal").iterdir()) == []
