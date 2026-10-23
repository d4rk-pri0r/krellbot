"""Real interpreter restarts over one isolated paper home, with no transport."""

import json
import os
import subprocess
import sys
from pathlib import Path

PROCESS = """
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import keyring

from tests.test_issue111_marker_matrix import BAR, PAIR, Reader, history, saved, venue_at

assert os.environ['KRELLBOT_ENABLE_LIVE'] == '0'
assert type(keyring.get_keyring()).__name__ == 'FakeKeyring'
home = Path(os.environ['KRELLBOT_HOME'])
venue = venue_at(home, Reader(history()))
if sys.argv[1] == 'entry':
    venue.place_entry_with_stop('entry', Decimal(5), Decimal(8), pair=PAIR)
else:
    venue.snapshot()
print(json.dumps({
    'pid': os.getpid(),
    'marker': saved(home).get('last_applied_ts'),
    'owned': str(venue.owned_qty(PAIR)),
    'stop': str(venue.resting_stop(PAIR)),
    'fills': saved(home)['recent_fills'],
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
    return json.loads(result.stdout)


def test_row2_entry_then_separate_process_restart_snapshot(tmp_path):
    entry = run_process(tmp_path, "entry")
    restarted = run_process(tmp_path, "snapshot")
    assert entry["pid"] != restarted["pid"]
    assert restarted["owned"] == "5"
    assert restarted["stop"] == "8.0000"
    assert [fill["side"] for fill in restarted["fills"]] == ["buy"]
    assert entry["marker"] == restarted["marker"] == 3_600_000
