"""Real interpreter restarts over one isolated paper home, with no transport."""

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

PROCESS = """
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import keyring

from krellbot.config import load_config, save_config
from tests.test_issue111_marker_matrix import BAR, PAIR, Reader, arm_test_pack, candle, history, saved, venue_at


def deny_network(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo'}:
        raise AssertionError('network is forbidden in paper marker tests')


sys.addaudithook(deny_network)
assert os.environ['KRELLBOT_ENABLE_LIVE'] == '0'
assert type(keyring.get_keyring()).__name__ == 'FakeKeyring'
home = Path(os.environ['KRELLBOT_HOME'])
action = sys.argv[1]
bars = history()
if action == 'snapshot-new':
    bars.append(candle(2 * BAR, low='7', open_='7', close='7'))
venue = venue_at(home, Reader(bars))
loaded_marker = saved(home).get('last_applied_ts')
if action in {'entry', 'entry-paused'}:
    venue.place_entry_with_stop('entry', Decimal(5), Decimal(8), pair=PAIR)
    if action == 'entry-paused':
        arm_test_pack(home)
        config = load_config(home)
        config.armed[0].entries_paused = True
        config.armed[0].owned_qty = Decimal(5)
        save_config(home, config)
else:
    venue.snapshot()
armed = load_config(home).armed
print(json.dumps({
    'pid': os.getpid(),
    'loaded_marker': loaded_marker,
    'marker': saved(home).get('last_applied_ts'),
    'owned': str(venue.owned_qty(PAIR)),
    'stop': str(venue.resting_stop(PAIR)),
    'fills': saved(home)['recent_fills'],
    'paused': armed[0].entries_paused if armed else None,
    'pack_owned': str(armed[0].owned_qty) if armed else None,
}))
"""


def run_process(home: Path, action: str) -> dict:
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        HOME=str(home),
        KRELLBOT_HOME=str(home),
        TMPDIR=str(home),
        KRELLBOT_ENABLE_LIVE="0",
        PYTHON_KEYRING_BACKEND="tests.fakes.fake_keyring.FakeKeyring",
    )
    argv = [sys.executable, "-c", PROCESS, action]
    result = subprocess.run(
        argv,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    (home / f"process-{action}.json").write_text(
        json.dumps({"argv": argv, "exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.splitlines()[-1])


def test_row2_entry_then_separate_process_restart_snapshot(tmp_path):
    entry = run_process(tmp_path, "entry")
    restarted = run_process(tmp_path, "snapshot")
    assert entry["pid"] != restarted["pid"]
    assert restarted["owned"] == "5"
    assert restarted["stop"] == "8.0000"
    assert [fill["side"] for fill in restarted["fills"]] == ["buy"]
    assert entry["marker"] == restarted["marker"] == 3_600_000


def test_rows2_5_restart_does_not_skip_a_genuinely_new_bar(tmp_path):
    entry = run_process(tmp_path, "entry")
    restarted = run_process(tmp_path, "snapshot-new")
    assert entry["pid"] != restarted["pid"]
    assert restarted["loaded_marker"] == entry["marker"] == 3_600_000
    assert restarted["marker"] == 7_200_000
    assert Decimal(restarted["owned"]) == 0
    assert restarted["stop"] == "None"
    assert [fill["side"] for fill in restarted["fills"]] == ["buy", "sell"]
    assert restarted["fills"][-1]["price"] == "6.9965"


def test_row9_paused_position_stop_and_marker_survive_separate_processes(tmp_path):
    entry = run_process(tmp_path, "entry-paused")
    restarted = run_process(tmp_path, "snapshot")
    assert entry["pid"] != restarted["pid"]
    assert restarted["owned"] == restarted["pack_owned"] == "5"
    assert restarted["stop"] == "8.0000"
    assert restarted["paused"] is True
    assert restarted["loaded_marker"] == restarted["marker"] == entry["marker"] == 3_600_000
    assert restarted["fills"] == entry["fills"]
