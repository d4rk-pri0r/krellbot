"""Real new interpreters exercise ordinary and conservative legacy restarts."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_paper_pair_cursors import PAIRS

PROCESS = """
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import keyring

from tests.test_paper_pair_cursors import PAIRS, Reader, bar, legacy_state, saved, venue_at


def deny_network(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo'}:
        raise AssertionError('paper cursor journeys forbid venue network')


sys.addaudithook(deny_network)
assert os.environ['KRELLBOT_ENABLE_LIVE'] == '0'
assert os.environ['PYTHON_KEYRING_BACKEND'] == 'tests.fakes.fake_keyring.FakeKeyring'
assert type(keyring.get_keyring()).__name__ == 'FakeKeyring'
home = Path(os.environ['KRELLBOT_HOME'])
stage, mode = sys.argv[1:]
if stage == 'legacy':
    markers = {'last_applied_ts': 100} if mode == 'scalar' else {}
    if mode == 'mixed':
        markers = {'last_applied_ts': 100, 'last_applied_ts_by_pair': {PAIRS[0]: 10}}
    legacy_state(home, **markers)
    print(json.dumps({'pid': os.getpid(), 'stage': stage, 'state': saved(home)}))
    sys.exit(0)

bars = {PAIRS[0]: [bar(100), bar(0, '1')], PAIRS[1]: [bar(10), bar(0, '1')]}
if mode in {'none', 'mixed'}:
    bars = {PAIRS[0]: [bar(10), bar(0, '1')], PAIRS[1]: None}
if stage == 'fill':
    if mode == 'ordinary':
        bars = {PAIRS[0]: [bar(200, '7', '7'), bar(100)],
                PAIRS[1]: [bar(20, '6', '6'), bar(10)]}
    elif mode == 'scalar':
        bars = {PAIRS[0]: [bar(101, '7', '7'), bar(0, '1')],
                PAIRS[1]: [bar(101, '6', '6'), bar(0, '1')]}
    else:
        bars = {PAIRS[0]: [bar(11, '7', '7'), bar(0, '1')],
                PAIRS[1]: [bar(101 if mode == 'mixed' else 0, '6', '6')]}
venue = venue_at(home, Reader(bars))
loaded = dict(venue._state.get('last_applied_ts_by_pair', {}))
if stage == 'entry':
    for pair in reversed(PAIRS):
        venue.place_entry_with_stop('entry-' + pair, Decimal(5), Decimal(8), pair=pair)
else:
    venue.snapshot()
print(json.dumps({'pid': os.getpid(), 'stage': stage, 'loaded': loaded, 'state': saved(home)}))
"""


def run_process(home: Path, stage: str, mode: str, sequence: int) -> dict:
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        HOME=str(home),
        KRELLBOT_HOME=str(home),
        KRELLBOT_ENABLE_LIVE="0",
        PYTHON_KEYRING_BACKEND="tests.fakes.fake_keyring.FakeKeyring",
    )
    argv = [sys.executable, "-c", PROCESS, stage, mode]
    cwd = Path(__file__).resolve().parents[1]
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=30, check=False)
    record = {
        "argv": argv,
        "cwd": str(cwd),
        "exit": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    (home / f"process-{sequence}-{stage}.json").write_text(json.dumps(record, indent=2))
    assert result.returncode == 0, result.stdout + result.stderr
    body = json.loads(result.stdout)
    print(json.dumps({"mode": mode, **body}))
    return body


def assert_held(body: dict, cursors: dict, buy_count: int) -> None:
    state = body["state"]
    assert state["last_applied_ts_by_pair"] == cursors
    assert len(state["open_orders"]) == 2
    assert len(state["recent_fills"]) == buy_count
    assert all(fill["side"] == "buy" for fill in state["recent_fills"])
    assert all(state["balances"][pair[:-3]] == "5" for pair in PAIRS)


def assert_sold(body: dict, cursors: dict, buy_count: int) -> None:
    state = body["state"]
    assert state["last_applied_ts_by_pair"] == cursors
    assert state["open_orders"] == []
    assert all(state["balances"][pair[:-3]] == "0.00000" for pair in PAIRS)
    assert len(state["recent_fills"]) == buy_count + 2
    sells = [fill for fill in state["recent_fills"] if fill["side"] == "sell"]
    assert {fill["pair"]: fill["price"] for fill in sells} == {PAIRS[0]: "6.9965", PAIRS[1]: "5.9970"}


def test_ordinary_pair_cursors_survive_distinct_processes_without_skipping_slow_pair(tmp_path):
    entry = run_process(tmp_path, "entry", "ordinary", 1)
    expected = {PAIRS[0]: 100, PAIRS[1]: 10}
    assert_held(entry, expected, 2)
    restarted = run_process(tmp_path, "snapshot", "ordinary", 2)
    assert restarted["loaded"] == expected
    assert_held(restarted, expected, 2)
    filled = run_process(tmp_path, "fill", "ordinary", 3)
    assert filled["loaded"] == expected
    assert_sold(filled, {PAIRS[0]: 200, PAIRS[1]: 20}, 2)
    repeated = run_process(tmp_path, "fill", "ordinary", 4)
    assert repeated["state"] == filled["state"]
    assert len({body["pid"] for body in [entry, restarted, filled, repeated]}) == 4


@pytest.mark.parametrize(
    "mode,expected,after",
    [
        ("scalar", {PAIRS[0]: 100, PAIRS[1]: 100}, {PAIRS[0]: 101, PAIRS[1]: 101}),
        ("none", {PAIRS[0]: 10, PAIRS[1]: -1}, {PAIRS[0]: 11, PAIRS[1]: 0}),
        ("mixed", {PAIRS[0]: 10, PAIRS[1]: 100}, {PAIRS[0]: 11, PAIRS[1]: 101}),
    ],
)
def test_legacy_file_migration_then_independent_new_process_restart(tmp_path, mode, expected, after):
    created = run_process(tmp_path, "legacy", mode, 1)
    migrated = run_process(tmp_path, "snapshot", mode, 2)
    assert migrated["loaded"] == expected
    assert_held(migrated, expected, 0)
    restarted = run_process(tmp_path, "snapshot", mode, 3)
    assert restarted["loaded"] == expected
    assert_held(restarted, expected, 0)
    filled = run_process(tmp_path, "fill", mode, 4)
    assert filled["loaded"] == expected
    assert_sold(filled, after, 0)
    repeated = run_process(tmp_path, "fill", mode, 5)
    assert repeated["state"] == filled["state"]
    assert len({body["pid"] for body in [created, migrated, restarted, filled, repeated]}) == 5
