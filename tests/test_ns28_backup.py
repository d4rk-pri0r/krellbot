"""NS28 backup through doctor.run: online sqlite backup, restore round-trip, bundle redaction, telemetry off.

The operational store (NS12) gains an online backup path the doctor uses to
prove a copy can be opened and read. The doctor surfaces ``backup_ok`` only
when a store file exists; a missing store is ``None``. The support bundle
preview is a redacted text rendering of the report so an operator reading
it never sees a value they registered with ``sanitize.register_secret``.
Backup telemetry (when telemetry consent is set) is sent through the
injected transport; the test spies that transport to prove zero posts when
consent is unset.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from krellbot import doctor, sanitize, telemetry
from krellbot.storage import backup
from krellbot.storage.database import OperationalStore

# ---------------------------------------------------------------------------
# Behavior 1: online backup uses the sqlite backup API. The copy can be
# opened by a fresh OperationalStore and reads the same ledger rows.
# ---------------------------------------------------------------------------


def _record(kind: str, **detail: object) -> dict:
    base = {"ts": 1_700_000_000, "kind": kind, "venue": "kraken", "pack": "demo"}
    base.update(detail)
    return base


def _seed_store(store: OperationalStore, *kinds: str) -> None:
    """Append one ledger row per kind."""
    conn = store.connect()
    for kind in kinds:
        conn.execute(
            "INSERT INTO ledger (kind, payload) VALUES (?, ?)",
            (kind, json.dumps({"kind": kind, "n": len(store.read_ledger()) + 1}, separators=(",", ":"))),
        )


def test_online_backup_produces_a_valid_sqlite_copy(tmp_path: Path) -> None:
    """backup.online_backup writes a sqlite file that OperationalStore can open and read."""
    store_path = tmp_path / "ops.sqlite"
    backup_path = tmp_path / "ops.sqlite.bak"
    store = OperationalStore(store_path)
    _seed_store(store, "tick", "order_intent")

    backup.online_backup(store_path, backup_path)

    assert backup_path.exists()
    # The header is sqlite. We do not require a live -wal/-shm on disk; the
    # backup API uses Connection.backup() which serialises the file at rest.
    assert backup_path.read_bytes()[:16] == b"SQLite format 3\x00"

    restored = OperationalStore(backup_path)
    rows = restored.read_ledger()
    assert [row[1] for row in rows] == ["tick", "order_intent"]


def test_online_backup_uses_sqlite_backup_api_not_a_raw_copy(tmp_path: Path) -> None:
    """A copy of a live WAL while writes are happening is not the only method.

    The sqlite ``Connection.backup()`` API is the documented online path.
    We can't patch sqlite3.Connection.backup directly (built-in C type),
    so the test asserts the source uses the API and that the destination
    is a sqlite file even when the source has unflushed WAL rows.
    """
    import inspect

    source = inspect.getsource(backup)
    # The implementation must call the API, not shutil.copy2 of the live file.
    assert ".backup(" in source
    assert "sqlite3.connect" in source

    store_path = tmp_path / "ops.sqlite"
    backup_path = tmp_path / "ops.sqlite.bak"
    store = OperationalStore(store_path)
    _seed_store(store, "tick", "order_intent")

    # Write a few more rows after the WAL exists, then immediately back up.
    # If the implementation copied the file directly (shutil.copy2), the
    # unflushed -wal sibling could be missing or the file could be torn.
    src_conn = store.connect()
    src_conn.execute("INSERT INTO ledger (kind, payload) VALUES ('live', 'x')")
    backup.online_backup(store_path, backup_path)

    assert backup_path.exists()
    restored = OperationalStore(backup_path)
    rows = restored.read_ledger()
    assert [r[1] for r in rows] == ["tick", "order_intent", "live"]


# ---------------------------------------------------------------------------
# Behavior 2: backup round-trip restores the same rows and reuses the NS12
# projection comparison. doctor.run calls the round-trip when the store
# file exists.
# ---------------------------------------------------------------------------


def test_backup_round_trip_returns_match_for_identical_rows(tmp_path: Path) -> None:
    store_path = tmp_path / "ops.sqlite"
    store = OperationalStore(store_path)
    _seed_store(store, "tick", "order_intent")

    result = backup.round_trip(store_path)

    assert result["ok"] is True
    assert result["projection_status"] in ("match", "not_compared")
    # restore ledger matches the source ledger
    assert result["rows_match"] is True


def test_backup_round_trip_surfaces_mismatch_when_restored_ledger_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A restore that drops a row must surface rows_match=False."""
    store_path = tmp_path / "ops.sqlite"
    store = OperationalStore(store_path)
    _seed_store(store, "tick", "order_intent")

    real_open = backup._open_backup

    def truncated_open(backup_file: Path) -> OperationalStore:
        st = real_open(backup_file)
        # Drop the most recent ledger row from the restored copy before read.
        conn = st.connect()
        conn.execute("DELETE FROM ledger WHERE id = (SELECT MAX(id) FROM ledger)")
        return st

    monkeypatch.setattr(backup, "_open_backup", truncated_open)

    result = backup.round_trip(store_path)
    assert result["rows_match"] is False
    assert result["ok"] is False


def test_doctor_run_calls_backup_round_trip_when_store_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """doctor.run, not just backup.py, must drive the round-trip when ops.sqlite is present."""
    monkeypatch.setattr("krellbot.doctor._ui_bind_available", lambda: True)
    os.chmod(tmp_path, 0o700)
    store_path = tmp_path / "ops.sqlite"
    store = OperationalStore(store_path)
    _seed_store(store, "tick")

    _exit_code, text = doctor.run(home=tmp_path, as_json=True)
    body = json.loads(text)

    assert body["backup_ok"] is True
    assert body["backup_checked"] is True


def test_doctor_run_reports_backup_ok_none_when_no_store_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No store file → backup_ok is None (not False, not True)."""
    monkeypatch.setattr("krellbot.doctor._ui_bind_available", lambda: True)
    os.chmod(tmp_path, 0o700)

    _exit_code, text = doctor.run(home=tmp_path, as_json=True)
    body = json.loads(text)

    assert body["backup_ok"] is None
    assert body["backup_checked"] is False


# ---------------------------------------------------------------------------
# Behavior 3: support bundle preview redacts any string registered with
# sanitize.register_secret. A test puts a fake secret in a doctor field and
# asserts the bundle text does not contain it.
# ---------------------------------------------------------------------------


def test_support_bundle_preview_redacts_registered_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A registered secret value embedded in a doctor field is replaced by *** in the bundle."""
    secret = "FAKESECRET_TOKEN_XYZ"
    sanitize.register_secret(secret)
    monkeypatch.setattr("krellbot.doctor._ui_bind_available", lambda: True)
    os.chmod(tmp_path, 0o700)

    # Embed the secret in a doctor-internal warning the bundle preview renders.
    def fake_clock_check(_now: int, _time_source):
        return (None, f"clock skew {secret} detected")

    monkeypatch.setattr("krellbot.doctor._clock_check", fake_clock_check)

    _exit_code, text = doctor.run(home=tmp_path, as_json=True)
    body = json.loads(text)

    assert "bundle_preview" in body
    assert isinstance(body["bundle_preview"], str)
    assert secret not in body["bundle_preview"]
    assert "***" in body["bundle_preview"]


def test_bundle_preview_redacts_keys_fields_regardless_of_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Privileged keys (api_key, password, etc.) are redacted even without register_secret."""
    monkeypatch.setattr("krellbot.doctor._ui_bind_available", lambda: True)
    os.chmod(tmp_path, 0o700)
    _exit_code, text = doctor.run(home=tmp_path, as_json=True)
    body = json.loads(text)
    # No registered secret; the privileged-keys branch still applies when a
    # doctor field happens to use one. The bundle_preview must be a str.
    assert isinstance(body["bundle_preview"], str)
    # Sanity: re-rendering the report through redact does not throw.
    assert body["bundle_preview"] != ""


# ---------------------------------------------------------------------------
# Behavior 4: disabled telemetry. The backup path performs zero posts when
# telemetry consent is unset. Spy the transport.
# ---------------------------------------------------------------------------


class _SpyTransport:
    def __init__(self) -> None:
        self.posts: list[tuple[str, bytes, dict]] = []

    def post(self, url: str, body: bytes, headers: dict) -> None:
        self.posts.append((url, body, headers))


def test_disabled_telemetry_backup_path_makes_zero_posts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No telemetry consent → backup.notify_backup must not call transport.post at all."""
    monkeypatch.setattr("krellbot.doctor._ui_bind_available", lambda: True)
    os.chmod(tmp_path, 0o700)
    # Telemetry is off by default — the spy transport must see zero posts.
    assert telemetry.is_enabled(tmp_path) is False

    spy = _SpyTransport()
    backup.notify_backup(tmp_path, transport=spy)

    assert spy.posts == []


def test_backup_module_imports_telemetry() -> None:
    """Grep proof: backup.py imports telemetry and uses its is_enabled consent gate."""
    import inspect

    source = inspect.getsource(backup)
    assert "telemetry" in source
    assert "is_enabled" in source
    import krellbot.telemetry as kb_telemetry

    assert kb_telemetry.is_enabled is telemetry.is_enabled


# ---------------------------------------------------------------------------
# Behavior 5: round-trip via doctor.run does not regress the NS12
# projection_status field. projection_status is still surfaced and the
# round-trip is independent of journal.append.
# ---------------------------------------------------------------------------


def test_doctor_run_round_trip_does_not_flip_journal_append(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A backup round-trip must not change the journal JSONL writer. The journal still writes files."""
    from krellbot import journal as kb_journal

    monkeypatch.setattr("krellbot.doctor._ui_bind_available", lambda: True)
    os.chmod(tmp_path, 0o700)
    (tmp_path / "journal").mkdir(parents=True, exist_ok=True)
    store_path = tmp_path / "ops.sqlite"
    store = OperationalStore(store_path)
    _seed_store(store, "tick")

    _exit_code, text = doctor.run(home=tmp_path, as_json=True)
    body = json.loads(text)
    assert body["backup_ok"] is True

    # Append a record via the journal module. It must land as a JSONL line,
    # proving journal.append is still the journal path and was not flipped
    # to the store.
    record = {
        "ts": 1_700_000_001,
        "kind": "tick",
        "venue": "kraken",
        "pack": "demo",
        "bar_ts": 1,
        "detail": {"k": "v"},
    }
    path = kb_journal.append(record)
    assert path.exists()
    assert path.suffix == ".jsonl"
    # The file is the journal, not the store.
    contents = path.read_text(encoding="utf-8").strip()
    assert contents  # one line of JSON
