"""Final doctor health includes late storage warnings.

Synthetic aggregation cases inject storage results, never claim store corruption.
Real-storage cases use journal.append/import_legacy and an actual SQLite backup;
only non-storage readiness/keyring boundaries are synthetically injected. No
exchange credentials or network are used, and all state is temporary.
"""

from __future__ import annotations

import json
import socket
import urllib.request
from pathlib import Path

import pytest

from krellbot import doctor, journal
from krellbot.storage import backup, import_legacy
from krellbot.storage.database import OperationalStore

NOW = 1_700_000_000
PROJECTION_WARNING = "legacy journal projection mismatch"
BACKUP_WARNING = "backup round-trip failed"
EARLY_WARNING = "clock not checked"
REPORT_KEYS = {
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
    "projection_status",
    "warnings",
    "install_ready",
    "trading_ready",
    "backup_ok",
    "backup_checked",
    "bundle_preview",
}


@pytest.fixture
def synthetic_non_storage(home, fresh_keyring, monkeypatch):
    """Explicit synthetic key/readiness boundaries; real fresh tick and home.

    The active keyring remains FakeKeyring. Reported presence/permissions below
    are injected booleans, not real stored or probed exchange keys.
    """
    home.chmod(0o700)
    cwd = home / "fresh-cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(doctor, "_keychain_backend", lambda: ("synthetic persistent backend report", None))
    monkeypatch.setattr(
        doctor,
        "_keys_status",
        lambda _probe: {"kraken": {"present": True, "trade": True, "withdraw": False}},
    )
    monkeypatch.setattr(doctor, "_ui_bind_available", lambda: True)

    def no_network(*_args, **_kwargs):
        raise AssertionError("doctor aggregation tests must not use network")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    record = {
        "ts": NOW,
        "kind": "tick",
        "venue": "kraken",
        "pack": "aggregation-test",
        "bar_ts": NOW,
        "detail": {"reason": "healthy-control"},
    }
    journal_path = journal.append(record)
    return home, record, journal_path


def _run(home: Path, *, as_json: bool, early_warning: bool = False):
    return doctor.run(
        home=home,
        write_root=home,
        clock=lambda: NOW,
        time_source=None if early_warning else lambda: NOW,
        as_json=as_json,
    )


def _assert_health(rc, body, *, as_json, warnings, projection_status, backup_ok, backup_checked):
    expected_ok = not warnings
    expected_trading_ready = backup_ok is not False and projection_status != import_legacy.PROJECTION_MISMATCH
    warning_text = "; ".join(warnings) if warnings else "none"
    if as_json:
        report = json.loads(body)
        assert set(report) == REPORT_KEYS
        assert report["warnings"] == warnings
        assert report["projection_status"] == projection_status
        assert report["backup_ok"] is backup_ok
        assert report["backup_checked"] is backup_checked
        assert report["install_ready"] is True
        assert report["trading_ready"] is expected_trading_ready
        assert report["ok"] is expected_ok
        preview_lines = report["bundle_preview"].splitlines()
        assert preview_lines[0] == f"ok: {expected_ok}"
        assert f"warnings: {warning_text}" in preview_lines
        assert f"backup_ok: {backup_ok}" in preview_lines
        assert f"backup_checked: {backup_checked}" in preview_lines
        assert f"projection_status: {projection_status}" in preview_lines
        assert "install_ready: True" in preview_lines
        assert f"trading_ready: {expected_trading_ready}" in preview_lines
    else:
        # Pin ordinary text formatting, not merely warning substrings.
        expected_lines = [
            "home mode: 0o700 ok" if doctor.sys.platform != "win32" else "home mode: skipped (Windows)",
            "keychain backend: synthetic persistent backend report",
            "kraken key: present (trade=on, withdraw=off)",
            "service installed: no",
            "last tick: 0s ago",
            "clock: not checked" if EARLY_WARNING in warnings else "clock skew: 0s",
            "license cache: missing",
            f"warnings: {warning_text}",
            "install_ready: True",
            f"trading_ready: {expected_trading_ready}",
        ]
        assert body == "\n".join(expected_lines)
    assert rc == (0 if expected_ok else 1)


@pytest.mark.parametrize("as_json", [True, False], ids=["json", "text"])
@pytest.mark.parametrize("early_warning", [False, True], ids=["no-early-warning", "early-warning"])
@pytest.mark.parametrize("backup_ok", [True, False], ids=["backup-healthy", "backup-failed"])
@pytest.mark.parametrize("projection_mismatch", [False, True], ids=["projection-match", "projection-mismatch"])
def test_synthetic_late_storage_health_aggregation(
    synthetic_non_storage, monkeypatch, projection_mismatch, backup_ok, early_warning, as_json
):
    """Synthetic late failures separately/combined, plus healthy/early controls."""
    home, _record, _journal_path = synthetic_non_storage
    store_path = home / import_legacy.DEFAULT_STORE_FILENAME
    store_path.touch()  # Synthetic existence boundary, not a populated SQLite store.
    projection_status = import_legacy.PROJECTION_MISMATCH if projection_mismatch else import_legacy.PROJECTION_MATCH
    calls = []

    def synthetic_projection(actual_home):
        assert actual_home == home
        calls.append("projection")
        return projection_status

    def synthetic_round_trip(actual_store_path):
        assert actual_store_path == store_path
        calls.append("backup")
        return {"ok": backup_ok}

    monkeypatch.setattr(import_legacy, "compare_legacy_projection", synthetic_projection)
    monkeypatch.setattr(backup, "round_trip", synthetic_round_trip)
    rc, body = _run(home, as_json=as_json, early_warning=early_warning)
    assert calls == ["projection", "backup"]
    warnings = [EARLY_WARNING] if early_warning else []
    if projection_mismatch:
        warnings.append(PROJECTION_WARNING)
    if not backup_ok:
        warnings.append(BACKUP_WARNING)
    _assert_health(
        rc,
        body,
        as_json=as_json,
        warnings=warnings,
        projection_status=projection_status,
        backup_ok=backup_ok,
        backup_checked=True,
    )


@pytest.mark.parametrize("as_json", [True, False], ids=["json", "text"])
@pytest.mark.parametrize("early_warning", [False, True], ids=["healthy", "early-warning"])
def test_no_store_semantics_unchanged(synthetic_non_storage, monkeypatch, early_warning, as_json):
    """Actual missing-store path stays not_compared/unchecked/None, not green storage."""
    home, _record, _journal_path = synthetic_non_storage
    store_path = home / import_legacy.DEFAULT_STORE_FILENAME

    def unexpected_backup(_store_path):
        raise AssertionError("absent store must not trigger backup")

    monkeypatch.setattr(backup, "round_trip", unexpected_backup)
    rc, body = _run(home, as_json=as_json, early_warning=early_warning)
    assert not store_path.exists()
    _assert_health(
        rc,
        body,
        as_json=as_json,
        warnings=[EARLY_WARNING] if early_warning else [],
        projection_status=import_legacy.PROJECTION_NOT_COMPARED,
        backup_ok=None,
        backup_checked=False,
    )


@pytest.mark.parametrize("as_json", [True, False], ids=["json", "text"])
@pytest.mark.parametrize("mismatch", [False, True], ids=["healthy-control", "real-mismatch"])
def test_real_temporary_projection_and_backup_health(synthetic_non_storage, mismatch, as_json):
    """Real storage methods, fabricated temporary records; no corrupted-store claim.

    A differing ledger payload is a real projection mismatch, not damaged SQLite.
    round_trip really copies/restores matching rows but fails its projection gate.
    Non-storage keyring/readiness boundary injections are labelled in the fixture.
    """
    home, record, journal_path = synthetic_non_storage
    store_path = home / import_legacy.DEFAULT_STORE_FILENAME
    store = OperationalStore(store_path)
    store_record = {**record, "detail": {"reason": "different-ledger-payload"}} if mismatch else record
    import_legacy.import_legacy(store, [store_record])
    source_rows = store.read_ledger()
    journal_bytes = journal_path.read_bytes()
    projection_status = import_legacy.PROJECTION_MISMATCH if mismatch else import_legacy.PROJECTION_MATCH
    assert import_legacy.compare_legacy_projection(home) == projection_status
    round_trip = backup.round_trip(store_path)
    assert round_trip["rows_match"] is True
    assert round_trip["source_rows"] == round_trip["restored_rows"] == source_rows
    assert round_trip["projection_status"] == projection_status
    assert round_trip["ok"] is (not mismatch)

    rc, body = _run(home, as_json=as_json)
    print(
        json.dumps(
            {
                "evidence": "real temporary storage; synthetic non-storage readiness/keyring boundaries",
                "home": str(home),
                "cwd": str(Path.cwd()),
                "mismatch": mismatch,
                "round_trip": round_trip,
                "as_json": as_json,
                "doctor_rc": rc,
                "doctor_body": json.loads(body) if as_json else body,
            },
            sort_keys=True,
        )
    )
    assert store.read_ledger() == source_rows
    assert journal_path.read_bytes() == journal_bytes
    assert Path(round_trip["backup_path"]).is_file()
    assert import_legacy.compare_legacy_projection(home) == projection_status
    _assert_health(
        rc,
        body,
        as_json=as_json,
        warnings=[PROJECTION_WARNING, BACKUP_WARNING] if mismatch else [],
        projection_status=projection_status,
        backup_ok=not mismatch,
        backup_checked=True,
    )
    store.connect().close()
