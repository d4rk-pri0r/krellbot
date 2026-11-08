"""Separate-process synthetic paper commands must not publish stale config."""

import json
import os
import subprocess
import sys
import time
from decimal import Decimal

import pytest

from krellbot.application.paper import PaperService
from krellbot.config import ArmedPack, Config, load_config, save_config

CHILD = r"""
import json, os, sys, time
from pathlib import Path
from decimal import Decimal
from krellbot import cli, config
from krellbot.application.paper import PaperService
home, barrier, label, operation, pair = Path(sys.argv[1]), Path(sys.argv[2]), *sys.argv[3:]
def mark(name): (barrier / (label + '.' + name)).write_text('synthetic', encoding='utf-8')
def wait(name):
    deadline = time.monotonic() + 20
    while not (barrier / name).exists():
        if time.monotonic() >= deadline: raise TimeoutError(name)
        time.sleep(0.01)
original_save = config.save_config
def save(home_arg, value):
    if label == 'A':
        mark('ready')
        wait('A.release')
    original_save(home_arg, value)
config.save_config = save
# Observe the actual lock denial if a transaction exists; never fake a syscall.
if os.name == 'nt':
    import msvcrt
    original_lock = msvcrt.locking
    def lock(fd, mode, size):
        try: return original_lock(fd, mode, size)
        except OSError:
            if label == 'B' and mode == msvcrt.LK_NBLCK: mark('blocked')
            raise
    msvcrt.locking = lock
else:
    import fcntl
    original_lock = fcntl.flock
    def lock(fd, mode):
        try: return original_lock(fd, mode)
        except OSError:
            if label == 'B' and mode & fcntl.LOCK_NB: mark('blocked')
            raise
    fcntl.flock = lock
mark('started')
if operation.startswith('cli:'):
    rc = cli.main(['krellbot', 'stop', '--venue', 'kraken', '--pair', pair, '--price', operation.split(':')[1]])
    result = {'rc': rc}
else:
    service = PaperService(home=home)
    if operation.startswith('stop:'):
        result = service.raise_stop(venue='kraken', pair=pair, new_stop=Decimal(operation.split(':')[1])).to_dict()
    elif operation == 'pause':
        result = service.pause_entries(venue='kraken', pair=pair).to_dict()
    else:
        result = service.resume_entries(venue='kraken', pair=pair).to_dict()
    rc = 0 if result['ok'] else 1
mark('done')
print(json.dumps(result), flush=True)
sys.exit(rc)
"""

SNAPSHOT = """
import json, sys
from pathlib import Path
from krellbot.config import load_config
print(json.dumps({a.pair: {'stop': str(a.stop), 'paused': a.entries_paused} for a in load_config(Path(sys.argv[1])).armed}))
"""


def _seed(home, paused=False):
    save_config(
        home,
        Config(
            armed=[
                ArmedPack(
                    "synthetic.json",
                    "0" * 64,
                    "synthetic",
                    "1",
                    "kraken",
                    pair,
                    Decimal(10),
                    Decimal(90),
                    "paper",
                    Decimal(1000),
                    False,
                    0,
                    entries_paused=paused,
                )
                for pair in ("SUIUSD", "ETHUSD")
            ]
        ),
    )


def _env(home):
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}}
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        KRELLBOT_HOME=str(home),
        TMPDIR=str(home),
        TMP=str(home),
        TEMP=str(home),
        KRELLBOT_ENABLE_LIVE="0",
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
    )
    return env


def _launch(home, barrier, label, operation, pair="SUIUSD"):
    return subprocess.Popen(
        [sys.executable, "-u", "-c", CHILD, str(home), str(barrier), label, operation, pair],
        cwd=home,
        env=_env(home),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_any(paths):
    deadline = time.monotonic() + 10
    while not any(p.exists() for p in paths):
        assert time.monotonic() < deadline, "child did not reach its real save/lock boundary"
        time.sleep(0.01)


def _finish(process):
    out, err = process.communicate(timeout=15)
    assert not err, err
    return process.returncode, json.loads(out.splitlines()[-1])


def _snapshot(home):
    run = subprocess.run(
        [sys.executable, "-c", SNAPSHOT, str(home)],
        cwd=home,
        env=_env(home),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return json.loads(run.stdout)


@pytest.mark.parametrize(
    "first,second,paused,other_pair,expected_stop,expected_paused,second_rc",
    [
        ("cli:95", "cli:99", False, False, "99", False, 0),
        ("cli:99", "cli:95", False, False, "99", False, 1),
        ("cli:95", "cli:95", False, False, "95", False, 1),
        ("stop:95", "stop:99", False, True, "95", False, 0),
        ("pause", "stop:99", False, False, "99", True, 0),
        ("stop:95", "pause", False, False, "95", True, 0),
        ("resume", "stop:99", True, False, "99", False, 0),
        ("stop:95", "resume", True, False, "95", False, 0),
    ],
)
def test_concurrent_commands_preserve_successful_updates(
    home, first, second, paused, other_pair, expected_stop, expected_paused, second_rc
):
    _seed(home, paused)
    barrier = home / "barrier"
    barrier.mkdir()
    processes = []
    try:
        a = _launch(home, barrier, "A", first)
        processes.append(a)
        _wait_any([barrier / "A.ready"])
        b = _launch(home, barrier, "B", second, "ETHUSD" if other_pair else "SUIUSD")
        processes.append(b)
        _wait_any([barrier / "B.done", barrier / "B.blocked"])
        # BASE B has already saved; a correct transaction can instead report
        # a real lock denial. Release A in either case, never demand an unsafe save.
        (barrier / "A.release").write_text("release", encoding="utf-8")
        a_rc, a_result = _finish(a)
        b_rc, b_result = _finish(b)
        assert a_rc == 0
        assert b_rc == second_rc, b_result
        state = _snapshot(home)  # New interpreter sees durable, not cached, state.
        assert state["SUIUSD"] == {"stop": expected_stop, "paused": expected_paused}
        if other_pair:
            assert state["ETHUSD"]["stop"] == "99"
        if "revision_after" in a_result and "revision_before" in b_result:
            assert b_result["revision_before"] == a_result["revision_after"]
    finally:
        (barrier / "A.release").write_text("release", encoding="utf-8")
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=10)


def test_transaction_timeout_distinct_homes_and_exception_cleanup(home, monkeypatch):
    from krellbot import config as module

    _seed(home)
    transaction = module._paper_command_transaction
    with transaction(home) as acquired:
        assert acquired
        inode = (home / ".paper-command.lock").stat().st_ino
        started = time.monotonic()
        with transaction(home, timeout=0.05) as competing:
            assert not competing
        assert time.monotonic() - started < 5
        with transaction(home / "other-home", timeout=0.05) as independent:
            assert independent
        monkeypatch.setattr(module, "_paper_command_transaction", lambda target: transaction(target, timeout=0.05))
        before = (home / "config.json").read_bytes()
        result = PaperService(home=home).raise_stop(venue="kraken", pair="SUIUSD", new_stop=Decimal(99))
        assert not result.ok and result.code == "invalid_request"
        assert result.revision_before == result.revision_after
        assert (home / "config.json").read_bytes() == before
    with pytest.raises(RuntimeError, match="synthetic"), transaction(home) as acquired:
        assert acquired
        raise RuntimeError("synthetic transaction failure")
    with transaction(home, timeout=0.05) as acquired:
        assert acquired
        assert (home / ".paper-command.lock").stat().st_ino == inode


def test_windows_lock_acquires_without_an_unlocked_initialization_write(home, monkeypatch):
    from types import SimpleNamespace

    from krellbot import config as module

    calls = []

    def denied_write(*args):
        raise PermissionError("synthetic locked-byte write denial")

    windows_os = SimpleNamespace(
        name="nt",
        O_RDWR=os.O_RDWR,
        O_CREAT=os.O_CREAT,
        SEEK_SET=os.SEEK_SET,
        open=os.open,
        close=os.close,
        lseek=os.lseek,
        fstat=os.fstat,
        write=denied_write,
    )
    windows_lock = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=lambda fd, mode, size: calls.append((mode, size)))
    monkeypatch.setattr(module, "os", windows_os)
    monkeypatch.setitem(sys.modules, "msvcrt", windows_lock)
    with module._paper_command_transaction(home) as acquired:
        assert acquired
    assert calls == [(1, 1), (2, 1)]
    # This is a Windows-branch ordering control, not native Windows race proof.
    assert (home / ".paper-command.lock").read_bytes() == b""


def test_kernel_releases_transaction_when_process_exits(home):
    from krellbot.config import _paper_command_transaction

    script = """
import os, sys
from pathlib import Path
from krellbot.config import _paper_command_transaction
with _paper_command_transaction(Path(sys.argv[1])) as acquired:
    assert acquired
    os._exit(0)
"""
    run = subprocess.run(
        [sys.executable, "-c", script, str(home)],
        cwd=home,
        env=_env(home),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    with _paper_command_transaction(home, timeout=0.05) as acquired:
        assert acquired


def test_sequential_refusals_idempotence_and_supplied_home(home, monkeypatch):
    _seed(home)
    monkeypatch.setenv("KRELLBOT_HOME", str(home / "wrong-home"))
    service = PaperService(home=home)
    assert service.raise_stop(venue="kraken", pair="SUIUSD", new_stop=Decimal(95)).ok
    before = (home / "config.json").read_bytes()
    refusal = service.raise_stop(venue="kraken", pair="SUIUSD", new_stop=Decimal(94))
    assert not refusal.ok and refusal.code == "invalid_stop"
    assert refusal.revision_before == refusal.revision_after
    assert (home / "config.json").read_bytes() == before
    assert service.pause_entries(venue="kraken", pair="SUIUSD").ok
    assert service.pause_entries(venue="kraken", pair="SUIUSD").code == "already_paused"
    assert service.resume_entries(venue="kraken", pair="SUIUSD").ok
    assert service.resume_entries(venue="kraken", pair="SUIUSD").code == "already_resumed"
    assert service.raise_stop(venue="unknown", pair="SUIUSD", new_stop=Decimal(99)).code == "unknown_venue"
    config = load_config(home)
    config.armed[0].mode = "live"
    save_config(home, config)
    before = (home / "config.json").read_bytes()
    assert service.raise_stop(venue="kraken", pair="SUIUSD", new_stop=Decimal(99)).code == "stored_mode_not_paper"
    assert service.pause_entries(venue="kraken", pair="SUIUSD").code == "stored_mode_not_paper"
    assert (home / "config.json").read_bytes() == before
