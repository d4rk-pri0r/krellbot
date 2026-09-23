"""Append-only, redacted journal under $KRELLBOT_HOME/journal/."""

import json
import os
from pathlib import Path

import pytest

from krellbot import paths as paths_mod
from krellbot import sanitize as sanitize_mod


@pytest.fixture(autouse=True)
def _isolate_secrets():
    sanitize_mod.register_secret("FAKESECRET")
    yield


def _read_journal(home: Path, ts: int) -> Path:
    import datetime as _dt

    utc = _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc)
    return home / "journal" / f"{utc:%Y-%m}.jsonl"


def test_journal_redacts_secret_values(tmp_path):
    from krellbot import journal

    os.environ["KRELLBOT_HOME"] = str(tmp_path)
    paths_mod.ensure_layout()

    ts = 1700000000
    journal.append(
        {
            "ts": ts,
            "kind": "tick",
            "venue": "kraken",
            "pack": "p",
            "bar_ts": ts,
            "detail": {"secret": "FAKESECRET", "note": "saw FAKESECRET in log"},
        }
    )

    journal_file = _read_journal(tmp_path, ts)
    assert journal_file.exists()
    line = journal_file.read_text(encoding="utf-8").strip().splitlines()[-1]
    assert "***" in line
    assert "FAKESECRET" not in line


def test_journal_missing_key_raises_value_error(tmp_path):
    from krellbot import journal

    os.environ["KRELLBOT_HOME"] = str(tmp_path)
    paths_mod.ensure_layout()

    base = {"ts": 1700000000, "kind": "tick", "venue": "kraken", "pack": "p", "bar_ts": 1700000000, "detail": {}}
    for key in ("ts", "kind", "venue", "pack", "bar_ts", "detail"):
        bad = dict(base)
        bad.pop(key)
        with pytest.raises(ValueError) as ei:
            journal.append(bad)
        assert key in str(ei.value)


def test_journal_one_json_per_line(tmp_path):
    from krellbot import journal

    os.environ["KRELLBOT_HOME"] = str(tmp_path)
    paths_mod.ensure_layout()

    for i in range(3):
        journal.append(
            {
                "ts": 1700000000 + i,
                "kind": "tick",
                "venue": "kraken",
                "pack": "p",
                "bar_ts": 1700000000,
                "detail": {"i": i},
            }
        )

    journal_file = _read_journal(tmp_path, 1700000000)
    lines = [line for line in journal_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 3
    for line in lines:
        json.loads(line)
