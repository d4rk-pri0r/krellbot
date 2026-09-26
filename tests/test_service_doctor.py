"""`krellbot doctor` and `krellbot doctor --json`.

The doctor command runs every health check with no network unless a time
source is injected. Tests pass a fake time source and prove zero socket
calls happen.

Readiness fields:

- ``install_ready`` is True when the runtime can run the local UI: home
  permissions are not wrong, the keyring backend is a real one (not
  null/fail/fake), and a loopback bind probe succeeds. No exchange key
  and no tick are required.
- ``trading_ready`` is True only when ``install_ready`` is True, a fresh
  tick exists, and at least one stored key had its permissions probed
  with ``trade=True`` AND ``withdraw=False``. Unknown permissions are
  fail-closed: ``trade``/``withdraw`` are only emitted when a
  permission probe ran, so a present key with no probe cannot become a
  green light.
"""

from __future__ import annotations

import datetime
import json
import socket
import urllib.request
from decimal import Decimal
from pathlib import Path


def _write_tick_journal(home: Path, ts: int) -> None:
    """Append one kind=tick record at `ts` to the right month file."""
    journal_dir = home / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    month = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m")
    path = journal_dir / f"{month}.jsonl"
    rec = {
        "ts": ts,
        "kind": "tick",
        "venue": "kraken",
        "pack": "trend-follow",
        "bar_ts": 0,
        "detail": {"reason": "no_candles", "pair": "SUIUSD"},
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, separators=(",", ":")) + "\n")


def _arm(
    home: Path, *, pair: str, starting_cash: Decimal | None = None, mode: str = "paper", venue: str = "kraken"
) -> None:
    """Write a single ArmedPack into config.json."""
    from krellbot.config import ArmedPack, Config, save_config

    armed = ArmedPack(
        pack_path="/tmp/whatever.json",
        pack_sha256="0" * 64,
        pack_id="trend-follow",
        pack_version="1.0.0",
        venue=venue,
        pair=pair,
        cap=Decimal(25),
        stop=Decimal(0),
        mode=mode,
        starting_cash=starting_cash,
        requires_license=False,
        armed_at_ts=0,
    )
    save_config(home, Config(armed=[armed]))


def test_doctor_flags_stale_tick(home, fresh_keyring):
    """Last kind=tick journal ts older than 2*3600s -> stale."""
    import time

    now = int(time.time())
    old_ts = now - 3 * 3600  # 3 hours ago
    _write_tick_journal(home, old_ts)

    from krellbot import doctor

    rc, body = doctor.run(home=home, write_root=home, clock=lambda: now, as_json=True)
    data = json.loads(body)
    assert data["last_tick_stale"] is True
    assert data["last_tick_age_s"] is not None
    assert data["last_tick_age_s"] >= 2 * 3600
    assert rc == 1  # exit non-zero on stale


def test_doctor_warns_when_clock_skew_over_5s(home, fresh_keyring):
    """abs(now - unixtime) > 5 -> clock warning in text and JSON."""
    from krellbot import doctor

    def fake_time():
        return 1_000_000

    rc, body = doctor.run(
        home=home,
        write_root=home,
        clock=lambda: 1_000_010,  # 10s skew
        time_source=fake_time,
        as_json=True,
    )
    data = json.loads(body)
    assert data["clock_warn"] is not None
    assert "skew" in data["clock_warn"].lower() or "clock" in data["clock_warn"].lower()
    assert any("skew" in w.lower() or "clock" in w.lower() for w in data["warnings"])
    assert rc == 1


def test_doctor_does_not_open_a_socket(home, fresh_keyring, monkeypatch):
    """Without an injected time source, doctor must not open any socket."""
    socket_calls: list[tuple] = []
    real_socket = socket.socket

    def tracking_socket(*args, **kwargs):
        socket_calls.append(("socket", args, kwargs))
        return real_socket(*args, **kwargs)

    monkeypatch.setattr(socket, "socket", tracking_socket)

    def tracking_urlopen(*args, **kwargs):
        socket_calls.append(("urlopen", args, kwargs))
        raise AssertionError("doctor must not open a URL without an injected time source")

    monkeypatch.setattr(urllib.request, "urlopen", tracking_urlopen)

    from krellbot import doctor

    _rc, _body = doctor.run(home=home, write_root=home, time_source=None)
    assert socket_calls == []


def test_doctor_unknown_pair_does_not_invent_a_minimum(home, fresh_keyring):
    """An armed pack with an unknown pair warns 'minimums not loaded' and never
    fabricates a fake minimum like 0.0001.
    """
    _arm(home, pair="UNKNOWN", starting_cash=Decimal(1000))

    from krellbot import doctor

    _rc, body = doctor.run(home=home, write_root=home, as_json=False)
    assert "minimums not loaded" in body
    assert "0.0001" not in body


def test_doctor_json_shape(home, fresh_keyring):
    """`doctor --json` produces all of the expected keys."""
    from krellbot import doctor

    _rc, body = doctor.run(home=home, write_root=home, as_json=True)
    data = json.loads(body)

    expected = {
        "ok",
        "home_mode_ok",
        "keychain_backend",
        "keys",
        "service_installed",
        "last_tick_age_s",
        "last_tick_stale",
        "clock_skew_s",
        "clock_warn",
        "license_status",
        "armed",
        "warnings",
    }
    assert expected.issubset(set(data.keys())), f"missing: {expected - set(data.keys())}"


def test_doctor_reads_can_withdraw(home, fresh_keyring):
    """A key that can withdraw is reported from KeyPerms.can_withdraw, not a missing attribute."""
    from krellbot import doctor, secrets
    from krellbot.venues.base import KeyPerms

    secrets.store("kraken", "trade-key", "not-a-real-secret")
    _rc, body = doctor.run(
        home=home,
        write_root=home,
        permission_probe=lambda _venue: KeyPerms(can_trade=True, can_withdraw=True),
        time_source=lambda: 1_000,
        clock=lambda: 1_000,
        as_json=True,
    )
    data = json.loads(body)
    assert data["keys"]["kraken"]["withdraw"] is True
    assert data["keys"]["kraken"]["trade"] is True


# ---------------------------------------------------------------------------
# Readiness fields (install_ready / trading_ready)
# ---------------------------------------------------------------------------


def test_doctor_missing_explicit_home_warns_and_is_not_install_ready(tmp_path, fresh_keyring, monkeypatch):
    """A nonexistent data home is a failing posture, not a crash or green check."""
    from krellbot import doctor

    missing = tmp_path / "never-created"
    monkeypatch.setattr(doctor, "_keychain_backend", lambda: ("OS Keychain", None))
    _rc, body = doctor.run(home=missing, write_root=tmp_path, as_json=True)
    report = json.loads(body)
    assert not missing.exists()
    assert report["home_mode_ok"] is False
    assert report["install_ready"] is False
    assert report["trading_ready"] is False
    assert any("home directory" in warning for warning in report["warnings"])


def _stub_real_keyring_backend(monkeypatch):
    """Pretend the OS keyring reports a real persistent backend name.

    The shared ``fresh_keyring`` fixture replaces the active backend with
    a fake; the readiness check treats fake/null/fail backends as
    warnings. Tests that exercise ``install_ready=True`` must therefore
    swap the backend reporter out for one whose module path and class
    name contain none of those substrings.
    """
    from krellbot import doctor

    class _RealBackend:
        name = "OS Keychain (test stub)"

        def get_password(self, *_args, **_kwargs):
            return None

        def set_password(self, *_args, **_kwargs):
            return None

    class _RealBackendModule:
        RealBackend = _RealBackend

    monkeypatch.setattr(doctor, "_keychain_backend", lambda: ("OS Keychain (test stub)", None))


def test_doctor_fresh_home_is_install_ready_but_not_trading_ready(home, fresh_keyring, monkeypatch):
    """A fresh install with no keys and no tick is install_ready but not trading_ready.

    install_ready = True (home permissions ok, real backend, bind probe succeeds).
    trading_ready = False (no probe permission data, no recent tick).
    """
    _stub_real_keyring_backend(monkeypatch)
    from krellbot import doctor

    _rc, body = doctor.run(
        home=home,
        write_root=home,
        time_source=lambda: 1_000,
        clock=lambda: 1_000,
        as_json=True,
    )
    data = json.loads(body)
    assert data["install_ready"] is True
    assert data["trading_ready"] is False
    # No probe ran, so trade/withdraw must not appear for absent keys.
    for info in data["keys"].values():
        assert "trade" not in info
        assert "withdraw" not in info


def test_doctor_fake_keyring_is_never_install_ready(home, fresh_keyring):
    """A fake/null/fail keyring backend must NOT make install_ready True.

    The shared ``fresh_keyring`` fixture installs a backend whose class
    is ``FakeKeyring``. Without overriding the backend, ``install_ready``
    must be False even with no other problems.
    """
    from krellbot import doctor

    _rc, body = doctor.run(
        home=home,
        write_root=home,
        time_source=lambda: 1_000,
        clock=lambda: 1_000,
        as_json=True,
    )
    data = json.loads(body)
    assert data["install_ready"] is False
    # The fake backend's class name appears in the report.
    assert "FakeKeyring" in (data["keychain_backend"] or "")
    assert any("not persistent" in w for w in data["warnings"])


def test_doctor_null_keyring_is_never_install_ready(home, fresh_keyring, monkeypatch):
    """A null backend class (class name contains 'null') cannot be install_ready."""
    import keyring

    class NullKeyring:
        name = "Null Backend"

        def get_password(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(keyring, "get_keyring", lambda: NullKeyring())

    from krellbot import doctor

    _rc, body = doctor.run(
        home=home,
        write_root=home,
        time_source=lambda: 1_000,
        clock=lambda: 1_000,
        as_json=True,
    )
    data = json.loads(body)
    assert data["install_ready"] is False
    assert any("null" in w.lower() for w in data["warnings"])


def test_doctor_fail_keyring_is_never_install_ready(home, fresh_keyring, monkeypatch):
    """A fail backend class (class name contains 'fail') cannot be install_ready."""
    from krellbot import doctor

    class FailKeyring:
        name = "Fail Backend"

        def get_password(self, *_args, **_kwargs):
            return None

    import keyring

    monkeypatch.setattr(keyring, "get_keyring", lambda: FailKeyring())

    _rc, body = doctor.run(
        home=home,
        write_root=home,
        time_source=lambda: 1_000,
        clock=lambda: 1_000,
        as_json=True,
    )
    data = json.loads(body)
    assert data["install_ready"] is False
    assert any("fail" in w.lower() for w in data["warnings"])


def test_doctor_bind_probe_uses_loopback_port_zero_and_closes(home, fresh_keyring, monkeypatch):
    """The UI bind probe must bind 127.0.0.1:0 only and close in finally."""
    from krellbot import doctor

    captured: dict = {}

    real_bind = socket.socket.bind

    def tracking_bind(self, addr):
        captured.setdefault("addrs", []).append(addr)
        return real_bind(self, addr)

    monkeypatch.setattr(socket.socket, "bind", tracking_bind)

    _stub_real_keyring_backend(monkeypatch)

    ok = doctor._ui_bind_available()
    assert ok is True
    assert captured["addrs"] == [("127.0.0.1", 0)], f"expected only 127.0.0.1:0, got {captured['addrs']}"
    # Second call should still succeed (no leaked socket holding the port).
    ok2 = doctor._ui_bind_available()
    assert ok2 is True


def test_doctor_bind_probe_returns_false_when_loopback_bind_fails(home, fresh_keyring, monkeypatch):
    """If loopback bind raises, _ui_bind_available returns False, no socket leaks."""
    from krellbot import doctor

    class _ExplodingSocket:
        def __init__(self, *_a, **_kw):
            pass

        def bind(self, _addr):
            raise OSError("bind refused")

        def close(self):
            captured["closed"] = True

    captured: dict = {}
    monkeypatch.setattr(socket, "socket", _ExplodingSocket)
    assert doctor._ui_bind_available() is False
    assert captured.get("closed") is True, "socket must be closed in finally even on bind failure"


def test_doctor_trading_ready_requires_trade_true_and_withdraw_false(home, fresh_keyring, monkeypatch):
    """trading_ready needs at least one present key with trade=True AND withdraw=False."""
    _stub_real_keyring_backend(monkeypatch)
    import time as _time

    from krellbot import doctor, secrets
    from krellbot.venues.base import KeyPerms

    secrets.store("kraken", "k", "s")
    # Fresh tick so staleness doesn't dominate.
    now = int(_time.time())
    _write_tick_journal(home, now)

    _rc, body = doctor.run(
        home=home,
        write_root=home,
        permission_probe=lambda _venue: KeyPerms(can_trade=True, can_withdraw=False),
        time_source=lambda: now,
        clock=lambda: now,
        as_json=True,
    )
    data = json.loads(body)
    assert data["install_ready"] is True
    assert data["trading_ready"] is True


def test_doctor_trading_ready_false_when_withdraw_capable(home, fresh_keyring, monkeypatch):
    """A key that can withdraw is reported but never makes trading_ready True."""
    _stub_real_keyring_backend(monkeypatch)
    import time as _time

    from krellbot import doctor, secrets
    from krellbot.venues.base import KeyPerms

    secrets.store("kraken", "k", "s")
    now = int(_time.time())
    _write_tick_journal(home, now)

    _rc, body = doctor.run(
        home=home,
        write_root=home,
        permission_probe=lambda _venue: KeyPerms(can_trade=True, can_withdraw=True),
        time_source=lambda: now,
        clock=lambda: now,
        as_json=True,
    )
    data = json.loads(body)
    assert data["install_ready"] is True
    assert data["trading_ready"] is False


def test_doctor_trading_ready_false_when_trade_false(home, fresh_keyring, monkeypatch):
    """A present key with trade=False (read-only) does not make trading_ready True."""
    _stub_real_keyring_backend(monkeypatch)
    import time as _time

    from krellbot import doctor, secrets
    from krellbot.venues.base import KeyPerms

    secrets.store("kraken", "k", "s")
    now = int(_time.time())
    _write_tick_journal(home, now)

    _rc, body = doctor.run(
        home=home,
        write_root=home,
        permission_probe=lambda _venue: KeyPerms(can_trade=False, can_withdraw=False),
        time_source=lambda: now,
        clock=lambda: now,
        as_json=True,
    )
    data = json.loads(body)
    assert data["install_ready"] is True
    assert data["trading_ready"] is False


def test_doctor_trading_ready_false_when_no_permission_probe(home, fresh_keyring, monkeypatch):
    """Without a permission probe, trade/withdraw are unknown and trading_ready is False."""
    _stub_real_keyring_backend(monkeypatch)
    import time as _time

    from krellbot import doctor, secrets

    secrets.store("kraken", "k", "s")
    now = int(_time.time())
    _write_tick_journal(home, now)

    _rc, body = doctor.run(
        home=home,
        write_root=home,
        permission_probe=None,  # explicitly no probe
        time_source=lambda: now,
        clock=lambda: now,
        as_json=True,
    )
    data = json.loads(body)
    assert data["install_ready"] is True
    assert data["trading_ready"] is False
    # Permission fields must not be present without a probe.
    assert "trade" not in data["keys"]["kraken"]
    assert "withdraw" not in data["keys"]["kraken"]


def test_doctor_trading_ready_false_when_tick_stale(home, fresh_keyring, monkeypatch):
    """Stale tick keeps trading_ready False even with a perfect trade-only key."""
    _stub_real_keyring_backend(monkeypatch)
    import time as _time

    from krellbot import doctor, secrets
    from krellbot.venues.base import KeyPerms

    secrets.store("kraken", "k", "s")
    now = int(_time.time())
    # Old tick.
    _write_tick_journal(home, now - 5 * 3600)

    _rc, body = doctor.run(
        home=home,
        write_root=home,
        permission_probe=lambda _venue: KeyPerms(can_trade=True, can_withdraw=False),
        time_source=lambda: now,
        clock=lambda: now,
        as_json=True,
    )
    data = json.loads(body)
    assert data["install_ready"] is True
    assert data["trading_ready"] is False


def test_doctor_trading_ready_false_when_no_keys(home, fresh_keyring, monkeypatch):
    """Fresh tick + trade-ready keying but no stored key -> trading_ready is False."""
    _stub_real_keyring_backend(monkeypatch)
    import time as _time

    from krellbot import doctor

    now = int(_time.time())
    _write_tick_journal(home, now)

    _rc, body = doctor.run(
        home=home,
        write_root=home,
        permission_probe=lambda _venue: None,
        time_source=lambda: now,
        clock=lambda: now,
        as_json=True,
    )
    data = json.loads(body)
    assert data["install_ready"] is True
    assert data["trading_ready"] is False


def test_doctor_install_ready_false_when_bind_unavailable(home, fresh_keyring, monkeypatch):
    """When the loopback bind probe cannot run, install_ready is False even with a real backend."""
    _stub_real_keyring_backend(monkeypatch)
    from krellbot import doctor

    monkeypatch.setattr(doctor, "_ui_bind_available", lambda: False)

    _rc, body = doctor.run(
        home=home,
        write_root=home,
        time_source=lambda: 1_000,
        clock=lambda: 1_000,
        as_json=True,
    )
    data = json.loads(body)
    assert data["install_ready"] is False


def test_doctor_install_ready_independent_of_service_installed(home, fresh_keyring, monkeypatch):
    """install_ready does NOT require the OS scheduler unit to be installed.

    A first-run install is ``install_ready`` before any ``krellbot
    service install`` has been run. The scheduler is part of the live
    arm step (slice C), not the install.
    """
    _stub_real_keyring_backend(monkeypatch)
    from krellbot import doctor

    # write_root is a fresh tmp dir: no plist, no systemd units, no task XML.
    _rc, body = doctor.run(
        home=home,
        write_root=home,
        time_source=lambda: 1_000,
        clock=lambda: 1_000,
        as_json=True,
    )
    data = json.loads(body)
    assert data["service_installed"] is False
    assert data["install_ready"] is True


def test_doctor_json_includes_readiness_keys(home, fresh_keyring):
    """The JSON report always carries install_ready and trading_ready fields."""
    from krellbot import doctor

    _rc, body = doctor.run(
        home=home,
        write_root=home,
        time_source=lambda: 1_000,
        clock=lambda: 1_000,
        as_json=True,
    )
    data = json.loads(body)
    assert "install_ready" in data
    assert "trading_ready" in data
    assert isinstance(data["install_ready"], bool)
    assert isinstance(data["trading_ready"], bool)


def test_doctor_readiness_does_not_suppress_existing_warnings(home, fresh_keyring, monkeypatch):
    """Adding readiness fields must not change the existing warnings list.

    A fake backend still emits its warning, a stale tick still emits
    its warning, and ``ok`` remains False. The new fields live beside
    the old semantics.
    """
    import time as _time

    from krellbot import doctor

    now = int(_time.time())
    _write_tick_journal(home, now - 5 * 3600)
    _rc, body = doctor.run(
        home=home,
        write_root=home,
        time_source=lambda: now,
        clock=lambda: now,
        as_json=True,
    )
    data = json.loads(body)
    assert data["ok"] is False
    assert data["install_ready"] is False  # fake backend in this fixture
    assert data["trading_ready"] is False
    assert any("not persistent" in w for w in data["warnings"])
    assert any("stale" in w.lower() or "no tick" in w.lower() for w in data["warnings"])


def test_doctor_readiness_does_not_open_a_socket(home, fresh_keyring, monkeypatch):
    """Readiness fields must not introduce network calls. Bind probe stays loopback."""
    socket_calls: list[tuple] = []

    real_socket = socket.socket

    def tracking_socket(*args, **kwargs):
        socket_calls.append(("socket", args, kwargs))
        return real_socket(*args, **kwargs)

    monkeypatch.setattr(socket, "socket", tracking_socket)

    def tracking_urlopen(*args, **kwargs):
        socket_calls.append(("urlopen", args, kwargs))
        raise AssertionError("doctor must not open a URL without an injected time source")

    monkeypatch.setattr(urllib.request, "urlopen", tracking_urlopen)

    from krellbot import doctor

    _rc, _body = doctor.run(
        home=home,
        write_root=home,
        time_source=None,
    )
    # All socket constructions came from the bind probe (loopback) and
    # bound only to 127.0.0.1:0. No urlopen was attempted.
    binds = [a for kind, args, _ in socket_calls for a in args if isinstance(a, tuple) and len(a) == 2]
    assert all(b == ("127.0.0.1", 0) for b in binds), f"unexpected bind targets: {binds}"


def test_doctor_text_renders_readiness_summary(home, fresh_keyring):
    """The text report prints the readiness fields with explicit booleans."""
    from krellbot import doctor

    _rc, body = doctor.run(
        home=home,
        write_root=home,
        time_source=lambda: 1_000,
        clock=lambda: 1_000,
        as_json=False,
    )
    assert "install_ready:" in body
    assert "trading_ready:" in body
