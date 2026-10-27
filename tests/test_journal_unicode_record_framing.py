"""Issue 295: journal CLI history must keep records containing U+2028/U+2029/U+0085.

`krellbot.journal.append` writes each record as one JSON object terminated
by a single byte-LF. U+2028 (LINE SEPARATOR), U+2029 (PARAGRAPH SEPARATOR)
and U+0085 (NEL) are valid *inside* JSON string fields, but the CLI reader
used str.splitlines(), which treats them as line breaks and silently drops
every affected record from `krellbot journal --since/--tail/--json` while
still exiting 0. The reader must frame records on the writer's real byte-LF
boundaries only.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from krellbot import journal
from krellbot.cli import _read_journal_records, cmd_journal

SEPARATORS = ["\u2028", "\u2029", "\u0085"]


@pytest.fixture(autouse=True)
def _isolate_secrets():
    from krellbot import sanitize

    sanitize.register_secret("FAKESECRET")
    yield


def _append(ts: int, detail: dict) -> None:
    """Append through the real public writer (redaction, framing, fsync)."""
    journal.append(
        {
            "ts": ts,
            "kind": "tick",
            "venue": "kraken",
            "pack": "p",
            "bar_ts": ts,
            "detail": detail,
        }
    )


def _write_month_record(home, year: int, month: int, payload: dict) -> None:
    (home / "journal").mkdir(parents=True, exist_ok=True)
    path = home / "journal" / f"{year:04d}-{month:02d}.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")


def _emit(capsys) -> list[dict]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


# --- Reader: records with record-internal separators stay whole --------------


@pytest.mark.parametrize("sep", SEPARATORS, ids=["U+2028", "U+2029", "U+0085"])
def test_reader_keeps_records_containing_unicode_separators(home, sep):
    detail = {"note": f"plain ASCII before{sep}and healthy ASCII after", "pair": "SUIUSD"}
    _append(1_700_000_000, detail)
    _append(1_700_000_001, {"note": "ordinary ascii record"})

    records = _read_journal_records(home)
    assert len(records) == 2, "record with unicode separator was dropped"
    assert records[0]["detail"] == detail
    assert records[0]["detail"]["note"] == f"plain ASCII before{sep}and healthy ASCII after"
    assert records[1]["detail"] == {"note": "ordinary ascii record"}


def test_reader_keeps_records_with_all_three_separators_and_neighbors(home):
    detail = {
        "a": f"start{SEPARATORS[0]}mid1{SEPARATORS[1]}mid2{SEPARATORS[2]}end",
        "b": f"{SEPARATORS[0]}leading",
        "c": f"trailing{SEPARATORS[2]}",
    }
    _append(1_700_000_000, detail)
    records = _read_journal_records(home)
    assert len(records) == 1
    assert records[0]["detail"] == detail


def test_reader_orders_records_by_file_then_position(home):
    _append(1_700_000_000, {"note": "first"})
    _append(1_700_000_001, {"note": f"second{SEPARATORS[0]}with separator"})
    _append(1_700_000_002, {"note": "third"})
    records = _read_journal_records(home)
    assert [r["detail"]["note"] for r in records] == [
        "first",
        f"second{SEPARATORS[0]}with separator",
        "third",
    ]


# --- CLI: --tail / --since / --json on the public history handler -----------


@pytest.mark.parametrize("sep", SEPARATORS, ids=["U+2028", "U+2029", "U+0085"])
def test_cli_tail_shows_records_with_unicode_separators(home, capsys, sep):
    _append(1_700_000_000, {"note": f"before{sep}after"})
    _append(1_700_000_001, {"note": "plain"})

    rc = cmd_journal(["--tail", "5"], now=1_700_000_100)
    assert rc == 0
    emitted = _emit(capsys)
    assert len(emitted) == 2, "record with unicode separator missing from --tail"
    assert any(r["detail"]["note"] == f"before{sep}after" for r in emitted)


@pytest.mark.parametrize("sep", SEPARATORS, ids=["U+2028", "U+2029", "U+0085"])
def test_cli_json_shows_records_with_unicode_separators(home, capsys, sep):
    _append(1_700_000_000, {"note": f"alpha{sep}omega", "pair": "SUIUSD"})
    _append(1_700_000_001, {"note": "plain"})

    rc = cmd_journal(["--json"], now=1_700_000_100)
    assert rc == 0
    emitted = _emit(capsys)
    assert len(emitted) == 2
    target = next(r for r in emitted if "alpha" in r["detail"]["note"])
    assert target["detail"]["note"] == f"alpha{sep}omega"


def test_cli_json_still_redacts_secret_fields(home, capsys):
    _append(1_700_000_000, {"note": f"x{SEPARATORS[0]}y", "secret": "s3cret", "nested": {"key": "k"}})

    rc = cmd_journal(["--json"], now=1_700_000_100)
    assert rc == 0
    emitted = _emit(capsys)
    assert len(emitted) == 1
    rec = emitted[0]
    assert "secret" not in rec["detail"]
    assert "key" not in rec["detail"]["nested"]
    assert rec["detail"]["note"] == f"x{SEPARATORS[0]}y"


def test_cli_since_window_semantics_unchanged(home, capsys):
    now = 1_700_000_000
    _append(now - 3 * 3600, {"note": f"recent{SEPARATORS[0]}with separator"})
    _append(now - 48 * 3600, {"note": "old plain"})
    _append(now - 48 * 3600 - 1, {"note": f"older{SEPARATORS[1]}also separator"})

    rc = cmd_journal(["--since", "24h"], now=now)
    assert rc == 0
    emitted = _emit(capsys)
    assert [r["detail"]["note"] for r in emitted] == [f"recent{SEPARATORS[0]}with separator"]


def test_cli_since_excludes_old_separator_record(home, capsys):
    now = 1_700_000_000
    _append(now, {"note": "fresh plain"})
    _append(now - 15 * 86400, {"note": f"old{SEPARATORS[2]}separator"})
    rc = cmd_journal(["--since", "14d"], now=now)
    assert rc == 0
    emitted = _emit(capsys)
    assert [r["detail"]["note"] for r in emitted] == ["fresh plain"]


def test_cli_tail_n_semantics_unchanged(home, capsys):
    for i in range(4):
        _append(1_700_000_000 + i, {"note": f"plain-{i}"})
    _append(1_700_000_010, {"note": f"special{SEPARATORS[0]}record"})

    rc = cmd_journal(["--tail", "2"], now=1_700_000_100)
    assert rc == 0
    emitted = _emit(capsys)
    assert [r["detail"]["note"] for r in emitted] == ["plain-3", f"special{SEPARATORS[0]}record"]


def test_cli_unknown_since_still_exits_2(home, capsys):
    rc = cmd_journal(["--since", "48h"], now=1_700_000_000)
    assert rc == 2


def test_cli_no_journal_still_prints_placeholder(home, capsys):
    rc = cmd_journal([], now=1_700_000_000)
    assert rc == 0
    assert capsys.readouterr().out.strip() == "no journal"


# --- Genuinely invalid records are still refused ----------------------------


def test_reader_skips_malformed_json_line(home):
    _append(1_700_000_000, {"note": f"good{SEPARATORS[0]}record"})
    month = home / "journal" / "2023-11.jsonl"
    raw = month.read_text(encoding="utf-8")
    month.write_text(raw + '{"ts": 1700000001, "kind": broken\n', encoding="utf-8")
    _append(1_700_000_002, {"note": "also good"})

    records = _read_journal_records(home)
    assert len(records) == 2
    assert records[0]["detail"]["note"] == f"good{SEPARATORS[0]}record"
    assert records[1]["detail"]["note"] == "also good"


def test_reader_keeps_valid_non_object_json_lines(home):
    """Valid non-dict JSON lines are parsed and kept, as before (only
    genuinely malformed lines are refused)."""
    month = home / "journal"
    month.mkdir(parents=True, exist_ok=True)
    (month / "2023-11.jsonl").write_text(
        '[1, 2, 3]\n{"ts": 1, "note": "fine"}\n"bare string"\n42\n',
        encoding="utf-8",
    )
    records = _read_journal_records(home)
    assert records == [[1, 2, 3], {"ts": 1, "note": "fine"}, "bare string", 42]


def test_cli_skips_malformed_line_and_exits_zero(home, capsys):
    _append(1_700_000_000, {"note": f"good{SEPARATORS[1]}record"})
    month = home / "journal" / "2023-11.jsonl"
    raw = month.read_text(encoding="utf-8")
    month.write_text(raw + "not json at all\n", encoding="utf-8")
    rc = cmd_journal(["--json"], now=1_700_000_100)
    assert rc == 0
    emitted = _emit(capsys)
    assert len(emitted) == 1
    assert emitted[0]["detail"]["note"] == f"good{SEPARATORS[1]}record"


# --- Reading never mutates the journal --------------------------------------


@pytest.mark.parametrize("sep", SEPARATORS, ids=["U+2028", "U+2029", "U+0085"])
def test_reading_does_not_change_journal_bytes(home, capsys, sep):
    _append(1_700_000_000, {"note": f"before{sep}after"})
    _append(1_700_000_001, {"note": "plain"})
    month = home / "journal" / "2023-11.jsonl"
    before_hash = hashlib.sha256(month.read_bytes()).hexdigest()
    before_bytes = month.read_bytes()

    assert _read_journal_records(home)
    rc = cmd_journal(["--json"], now=1_700_000_100)
    assert rc == 0
    assert _emit(capsys)

    assert month.read_bytes() == before_bytes
    assert hashlib.sha256(month.read_bytes()).hexdigest() == before_hash


def test_writer_output_framing_is_byte_lf(home):
    """The public writer frames records with byte-LF only; no CR is added."""
    _append(1_700_000_000, {"note": f"a{SEPARATORS[0]}b"})
    raw = (home / "journal" / "2023-11.jsonl").read_bytes()
    assert raw.count(b"\n") == 1 and raw.endswith(b"\n")
    assert b"\r" not in raw
    assert SEPARATORS[0].encode("utf-8") in raw


def test_crlf_file_framed_on_lf_only(home):
    """A legacy CRLF file keeps one-record-per-LF framing (CR stays in payload)."""
    month = home / "journal"
    month.mkdir(parents=True, exist_ok=True)
    payload = '{"ts": 1, "detail": {"note": "line one\\r\\nline two"}}'
    (month / "2023-11.jsonl").write_bytes(payload.encode("utf-8") + b"\r\n")

    records = _read_journal_records(home)
    assert len(records) == 1
    assert records[0]["detail"]["note"] == "line one\r\nline two"


def test_reader_handles_missing_directory(home):
    assert _read_journal_records(home) == []


def test_reader_ignores_non_jsonl_files(home):
    month = home / "journal"
    month.mkdir(parents=True, exist_ok=True)
    (month / "2023-11.json").write_text('{"ts": 1}\n', encoding="utf-8")
    (month / "2023-11.jsonl").write_text('{"ts": 2}\n', encoding="utf-8")
    assert [r["ts"] for r in _read_journal_records(home)] == [2]
