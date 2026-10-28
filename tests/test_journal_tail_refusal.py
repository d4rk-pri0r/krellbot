"""Issue #318: `krellbot journal --tail` refuses zero and negative counts.

``records[-0:]`` is the whole journal and ``records[:-3]`` silently drops
the earliest records, so ``--tail 0`` and ``--tail -3`` must receive the
same typed refusal the parser already uses for non-numeric input: stderr
``invalid --tail: <value>`` and exit 2, printing no records.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from krellbot import journal

NOW = 1_700_000_000
RECORD_COUNT = 12

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_records(count: int) -> None:
    for i in range(count):
        journal.append(
            {
                "ts": NOW + i,
                "kind": "tick",
                "venue": "kraken",
                "pack": "p",
                "bar_ts": NOW,
                "detail": {"i": i},
            }
        )


def _lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def _isolate_secrets():
    from krellbot import sanitize

    sanitize.register_secret("FAKESECRET")
    yield


# ---- zero and negative tails: typed refusal, never a mis-sliced journal ----


def test_tail_zero_refused_instead_of_whole_journal(home, capsys):
    _write_records(RECORD_COUNT)

    from krellbot.cli import cmd_journal

    rc = cmd_journal(["--tail", "0"], now=NOW)
    captured = capsys.readouterr()

    assert rc == 2
    assert captured.err.strip() == "invalid --tail: 0"
    assert not captured.out.strip()


def test_tail_negative_refused_instead_of_dropping_earliest(home, capsys):
    _write_records(RECORD_COUNT)

    from krellbot.cli import cmd_journal

    rc = cmd_journal(["--tail", "-3"], now=NOW)
    captured = capsys.readouterr()

    assert rc == 2
    assert captured.err.strip() == "invalid --tail: -3"
    assert not captured.out.strip()


def test_tail_abc_refusal_unchanged(home, capsys):
    _write_records(RECORD_COUNT)

    from krellbot.cli import cmd_journal

    rc = cmd_journal(["--tail", "abc"], now=NOW)
    captured = capsys.readouterr()

    assert rc == 2
    assert captured.err.strip() == "invalid --tail: abc"
    assert not captured.out.strip()


# ---- real CLI subprocess: same refusals through main() dispatch ------------


def _run_cli_journal(home: Path, *flags: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(
        {
            "KRELLBOT_HOME": str(home),
            "KRELLBOT_LIVE": "0",
            "KRELLBOT_API_LIVE": "0",
            "KRELLBOT_ENABLE_LIVE": "0",
            "PYTHON_KEYRING_BACKEND": "tests.fakes.fake_keyring.FakeKeyring",
        }
    )
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from krellbot.cli import main; sys.exit(main(['krellbot'] + sys.argv[1:]))",
            "journal",
            *flags,
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=60,
        check=False,
    )


def test_cli_subprocess_tail_zero_refused(home):
    _write_records(RECORD_COUNT)

    proc = _run_cli_journal(home, "--tail", "0")

    assert proc.returncode == 2
    assert proc.stderr.strip() == "invalid --tail: 0"
    assert not proc.stdout.strip()


def test_cli_subprocess_tail_negative_refused(home):
    _write_records(RECORD_COUNT)

    proc = _run_cli_journal(home, "--tail", "-3")

    assert proc.returncode == 2
    assert proc.stderr.strip() == "invalid --tail: -3"
    assert not proc.stdout.strip()


def test_cli_subprocess_tail_three_returns_three_records(home):
    _write_records(RECORD_COUNT)

    proc = _run_cli_journal(home, "--tail", "3")

    assert proc.returncode == 0
    assert len(_lines(proc.stdout)) == 3


# ---- unchanged behavior controls -------------------------------------------


def test_tail_one_returns_single_record(home, capsys):
    _write_records(RECORD_COUNT)

    from krellbot.cli import cmd_journal

    rc = cmd_journal(["--tail", "1"], now=NOW)
    out = capsys.readouterr().out

    assert rc == 0
    records = _lines(out)
    assert len(records) == 1
    assert records[0]["detail"]["i"] == RECORD_COUNT - 1


def test_default_tail_five_unchanged(home, capsys):
    _write_records(RECORD_COUNT)

    from krellbot.cli import cmd_journal

    rc = cmd_journal([], now=NOW)
    out = capsys.readouterr().out

    assert rc == 0
    records = _lines(out)
    assert len(records) == 5
    assert [r["detail"]["i"] for r in records] == list(range(RECORD_COUNT - 5, RECORD_COUNT))


def test_tail_three_unchanged(home, capsys):
    _write_records(RECORD_COUNT)

    from krellbot.cli import cmd_journal

    rc = cmd_journal(["--tail", "3"], now=NOW)
    out = capsys.readouterr().out

    assert rc == 0
    records = _lines(out)
    assert len(records) == 3
    assert [r["detail"]["i"] for r in records] == [9, 10, 11]


def test_since_window_unchanged(home, capsys):
    _write_records(RECORD_COUNT)
    journal.append(
        {
            "ts": NOW - 48 * 3600,
            "kind": "tick",
            "venue": "kraken",
            "pack": "p",
            "bar_ts": NOW,
            "detail": {"i": "old"},
        }
    )

    from krellbot.cli import cmd_journal

    rc = cmd_journal(["--since", "24h"], now=NOW + RECORD_COUNT)
    out = capsys.readouterr().out

    assert rc == 0
    records = _lines(out)
    assert len(records) == RECORD_COUNT


def test_json_redaction_unchanged(home, capsys):
    journal.append(
        {
            "ts": NOW,
            "kind": "tick",
            "venue": "kraken",
            "pack": "p",
            "bar_ts": NOW,
            "detail": {
                "key": "FAKESECRET",
                "secret": "FAKESECRET",
                "license": "FAKESECRET",
                "balance": "FAKESECRET",
                "note": "ok",
            },
        }
    )

    from krellbot.cli import cmd_journal

    rc = cmd_journal(["--json", "--tail", "3"], now=NOW)
    out = capsys.readouterr().out

    assert rc == 0
    records = _lines(out)
    assert records, "at least one record expected"
    detail = records[-1]["detail"]
    assert "key" not in detail
    assert "secret" not in detail
    assert "license" not in detail
    assert "balance" not in detail
    assert detail.get("note") == "ok"
