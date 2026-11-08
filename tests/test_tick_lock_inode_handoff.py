"""Real POSIX flock handoffs in isolated synthetic paper namespaces."""

import json
import os
import select
import subprocess
import sys

import pytest

from krellbot.run.lock import TickLock

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX kernel flock handoff; not Windows qualification")

CHILD = """
import json, os, sys
from pathlib import Path
from krellbot.run.lock import TickLock
lock = TickLock(Path(sys.argv[1]), sys.argv[2])
acquired = lock.acquire()
print(json.dumps({'acquired': acquired, 'inode': os.fstat(lock._fd).st_ino if acquired else None}), flush=True)
if acquired and sys.argv[3] == 'hold':
    sys.stdin.readline()
lock.release()
"""


def _env(home):
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL"}}
    env.update(
        HOME=str(home),
        KRELLBOT_HOME=str(home / "app"),
        TMPDIR=str(home),
        KRELLBOT_ENABLE_LIVE="0",
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
    )
    return env


def _probe(home, venue):
    run = subprocess.run(
        [sys.executable, "-u", "-c", CHILD, str(home), venue, "probe"],
        cwd=home,
        env=_env(home),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return json.loads(run.stdout)


def _holder(home, venue):
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", CHILD, str(home), venue, "hold"],
        cwd=home,
        env=_env(home),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready, _, _ = select.select([process.stdout], [], [], 10)
        assert ready, "successor did not report its real acquire result"
        outcome = json.loads(process.stdout.readline())
        assert outcome["acquired"] is True, outcome
        return process, outcome["inode"]
    except BaseException:
        process.terminate()
        process.communicate(timeout=10)
        raise


@pytest.mark.parametrize("venue", ["kraken", "coinbase"])
@pytest.mark.parametrize("handoffs", [1, 3])
def test_successor_remains_exclusive_across_predecessor_release(home, monkeypatch, venue, handoffs):
    import fcntl

    real_flock = fcntl.flock
    for _ in range(handoffs):
        predecessor = TickLock(home, venue)
        assert predecessor.acquire()
        assert _probe(home, venue)["acquired"] is False
        original_inode = os.fstat(predecessor._fd).st_ino
        holder = []

        def unlock_then_acquire_successor(fd, operation, holder=holder):
            result = real_flock(fd, operation)  # Actual unlock before successor, never a fabricated outcome.
            if operation == fcntl.LOCK_UN:
                holder.append(_holder(home, venue))
            return result

        try:
            with monkeypatch.context() as patch:
                patch.setattr(fcntl, "flock", unlock_then_acquire_successor)
                predecessor.release()
            assert len(holder) == 1
            assert holder[0][1] == original_inode
            assert _probe(home, venue)["acquired"] is False
            assert (home / "run" / f"{venue}.lock").stat().st_ino == original_inode
            predecessor.release()  # Idempotent release cannot disturb the successor.
            assert _probe(home, venue)["acquired"] is False
        finally:
            for process, _inode in holder:
                process.communicate("release\n", timeout=10)
                assert process.returncode == 0
            predecessor.release()
        assert _probe(home, venue)["acquired"] is True


def test_lifecycle_controls_leave_no_stale_holder(home):
    lock = TickLock(home, "kraken")
    lock.release()
    assert not lock.held
    assert lock.acquire() and lock.acquire() and lock.held
    assert _probe(home, "coinbase")["acquired"] is True
    contender = TickLock(home, "kraken")
    assert not contender.acquire()
    contender.release()
    assert _probe(home, "kraken")["acquired"] is False
    lock.release()
    lock.release()
    assert not lock.held
    assert _probe(home, "kraken")["acquired"] is True
    with pytest.raises(RuntimeError, match="synthetic"), lock as acquired:
        assert acquired
        raise RuntimeError("synthetic body failure")
    assert not lock.held
    assert _probe(home, "kraken")["acquired"] is True
