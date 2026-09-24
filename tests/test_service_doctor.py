"""`krellbot doctor` and `krellbot doctor --json`.

The doctor command runs every health check with no network unless a time
source is injected. Tests pass a fake time source and prove zero socket
calls happen.
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
