"""Synthetic fault-injected key rotation through fresh CLI processes only."""

import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import keyring
import pytest

from krellbot import cli, secrets
from tests.fakes.fake_keyring import FakeKeyring

OLD = ("synthetic-old-key", "synthetic-old-secret")
NEW = ("synthetic-new-key", "synthetic-new-secret")


class FaultKeyring(FakeKeyring):
    name = "synthetic-memory-backend"

    def __init__(self, venue, prior, fault):
        super().__init__()
        self.fault, self.fired, self.started, self.restoring = fault, False, False, False
        for slot, value in zip(("key", "secret"), prior, strict=True):
            if value is not None:
                self._store[(f"krellbot:{venue}", slot)] = value
        self._store[("synthetic-unrelated-service", "key")] = "synthetic-other"

    def set_password(self, service, username, password):
        if password in NEW:
            self.started = True
            if not self.fired and username == "key" and self.fault == "first-write-raise":
                super().set_password(service, username, password)
                self.fired = True
                raise RuntimeError("synthetic failed " + NEW[0])
            if not self.fired and username == "secret":
                if self.fault in {"second-raise", "restore-raise", "restore-noop", "restore-readback"}:
                    self.fired = True
                    raise RuntimeError("synthetic failed " + NEW[1])
                if self.fault == "second-noop":
                    self.fired = True
                    return
        elif self.started:
            self.restoring = True
            if self.fault == "restore-raise":
                raise RuntimeError("synthetic restoration failure " + OLD[0])
            if self.fault == "restore-noop":
                return
        super().set_password(service, username, password)

    def get_password(self, service, username):
        if self.fault == "snapshot-raise" and not self.started:
            raise RuntimeError("synthetic snapshot failure " + OLD[1])
        if self.fault == "readback-raise" and self.started and not self.fired:
            self.fired = True
            raise RuntimeError("synthetic readback failure " + NEW[1])
        if self.fault == "restore-readback" and self.restoring:
            raise RuntimeError("synthetic restore readback failure " + OLD[1])
        return super().get_password(service, username)

    def delete_password(self, service, username):
        self.restoring = True
        super().delete_password(service, username)


def _exercise(home, venue, prior_kind, fault, interface):
    prior = {"pair": OLD, "empty": (None, None), "key-only": (OLD[0], None), "secret-only": (None, OLD[1])}[prior_kind]
    backend = FaultKeyring(venue, prior, fault)
    keyring.set_keyring(backend)
    before = dict(backend._store)
    keyfile = home / "synthetic-input.txt"
    keyfile.write_text("\n".join(NEW), encoding="utf-8")
    keyfile.chmod(0o600)
    out, err = io.StringIO(), io.StringIO()
    message, returned = "", None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        if interface == "cli":
            rc = cli.main(["krellbot", "keys", "add", venue, "--file", str(keyfile)])
        else:
            try:
                returned = secrets.store(venue, *NEW)
                rc = 0
            except RuntimeError as exc:
                message = str(exc)
                rc = 1
    try:
        read = secrets.get(venue)
    except (ValueError, FileNotFoundError, RuntimeError):
        read = None
    text = out.getvalue() + err.getvalue() + message
    return {
        "rc": rc,
        "prior_preserved": backend._store == before,
        "new_pair_readable": read == NEW,
        "old_pair_readable": read == OLD,
        "reader_refused": read is None,
        "secret_free": all(s not in text for s in (*OLD, *NEW)),
        "uncertain": "uncertain" in message.lower(),
        "claims_restored": "restored" in message.lower(),
        "backend_name": returned,
        "unrelated_unchanged": backend._store.get(("synthetic-unrelated-service", "key")) == "synthetic-other",
        "write_started": backend.started,
    }


def _fresh(home, venue, prior, fault, interface="cli"):
    root = home / "process"
    root.mkdir()
    script = """
import json, sys
from pathlib import Path
from tests.test_cli_key_rotation_integrity import _exercise
print(json.dumps(_exercise(Path(sys.argv[1]), *sys.argv[2:])))
"""
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}}
    env.update(
        HOME=str(root),
        USERPROFILE=str(root),
        KRELLBOT_HOME=str(root),
        TMPDIR=str(root),
        TMP=str(root),
        TEMP=str(root),
        PYTHONPATH=str(Path(__file__).resolve().parents[1]),
        KRELLBOT_ENABLE_LIVE="0",
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        PYTHONNOUSERSITE="1",
    )
    run = subprocess.run(
        [sys.executable, "-c", script, str(root), venue, prior, fault, interface],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert not run.stderr, "fresh synthetic CLI harness emitted an unexpected error"
    return json.loads(run.stdout)


@pytest.mark.parametrize("venue", ["kraken", "coinbase"])
@pytest.mark.parametrize("prior", ["pair", "empty", "key-only", "secret-only"])
@pytest.mark.parametrize("fault", ["second-raise", "second-noop", "first-write-raise", "readback-raise"])
def test_failed_fresh_cli_rotation_preserves_exact_prior_state(home, venue, prior, fault):
    result = _fresh(home, venue, prior, fault)
    assert result["rc"] != 0
    assert result["prior_preserved"]
    assert result["secret_free"] and result["unrelated_unchanged"]
    assert result["old_pair_readable"] if prior == "pair" else result["reader_refused"]


@pytest.mark.parametrize("venue", ["kraken", "coinbase"])
@pytest.mark.parametrize("interface", ["cli", "store"])
def test_successful_rotation_roundtrips_and_returns_backend_name(home, venue, interface):
    result = _fresh(home, venue, "pair", "none", interface)
    assert result["rc"] == 0 and result["new_pair_readable"]
    assert result["secret_free"] and result["unrelated_unchanged"]
    if interface == "store":
        assert result["backend_name"] == "synthetic-memory-backend"


@pytest.mark.parametrize("fault", ["restore-raise", "restore-noop", "restore-readback"])
def test_unverified_restoration_fails_closed_and_reports_secret_free_uncertainty(home, fault):
    result = _fresh(home, "kraken", "pair", fault, "store")
    assert result["rc"] != 0
    assert result["uncertain"] and not result["claims_restored"]
    assert result["secret_free"] and result["unrelated_unchanged"]
    assert result["reader_refused"]


def test_failed_snapshot_does_not_start_a_write(home):
    result = _fresh(home, "kraken", "pair", "snapshot-raise", "store")
    assert result["rc"] != 0 and result["prior_preserved"]
    assert not result["write_started"] and result["secret_free"]
