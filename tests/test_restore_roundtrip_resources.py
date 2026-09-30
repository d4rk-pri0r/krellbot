"""The round-trip harness must release readers before wiping the source home."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest


def _load_harness():
    path = Path(__file__).resolve().parents[1] / "scripts" / "restore_roundtrip.py"
    spec = importlib.util.spec_from_file_location("restore_roundtrip_resources", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("valid_schema", [True, False])
def test_ledger_reader_closes_connection_before_return_or_error(tmp_path, monkeypatch, valid_schema):
    harness = _load_harness()
    db = tmp_path / "ops.sqlite"
    conn = sqlite3.connect(db)
    try:
        if valid_schema:
            conn.execute("CREATE TABLE ledger(id INTEGER, kind TEXT, payload TEXT)")
            conn.execute("INSERT INTO ledger VALUES(1, 'outbox', '{}')")
            conn.commit()
    finally:
        conn.close()

    original = sqlite3.connect
    opened = []

    def track_connection(*args, **kwargs):
        connection = original(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", track_connection)
    try:
        if valid_schema:
            assert harness._read_ledger_rows(tmp_path) == [(1, "outbox", "{}")]
        else:
            with pytest.raises(sqlite3.OperationalError, match="no such table"):
                harness._read_ledger_rows(tmp_path)
        assert len(opened) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            opened[0].execute("SELECT 1")
    finally:
        for connection in opened:
            connection.close()
