"""Issue 328: structurally admitted rows with non-decimal prices refuse, never crash.

`krellbot data import kraken-ohlcvt` on main b592ed39c291b95eb9a2aa993d5de8789730ab9d
aborts with a raw `decimal.InvalidOperation` traceback when a candle row that
passes structural admission (numeric first field, exactly 7 fields) carries a
non-decimal price or volume field such as `open=N/A` or `volume=--`. The
existing malformed-row contract already skips headers, non-numeric timestamps
and wrong-width rows; this suite pins the decimal admission contract on the
same shared `_row_to_candle` rule:

* a structurally admitted row whose open/high/low/close/volume conversion
  fails is refused through the existing typed path - the CLI prints
  `import refused: ...` and exits 1 - never an uncaught traceback, never a
  repaired or fabricated price;
* nothing is published on refusal: no cache bytes, no manifest, no dataset
  version, and any prior cache for the same market stays byte-identical;
* the refusal keeps checkpoint/resume coherence - a fresh process at the same
  home re-validates the committed 128-candle chunk against the source and
  refuses again identically instead of resurrecting the crash;
* healthy imports, structural skips and every decimal shape `Decimal` already
  accepts stay byte-identical (controls, green on main).

The bad-row witnesses are RED on main (raw traceback) and green on the fix.
This is issue 328 only: not B41 zero-requested-candles publication admission,
not issue #228/B20 Coinbase parsing. Live execution stays disabled; every CLI
witness runs in a fresh subprocess against a tmp `KRELLBOT_HOME` with no
network use.
"""

from __future__ import annotations

import csv as _csv
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.data.cache import read_cache
from krellbot.data.import_progress import ImportProgressError
from krellbot.data.kraken_public import (
    _row_is_candle,
    _row_to_candle,
    import_kraken_ohlcvt_cached,
    import_kraken_ohlcvt_zip,
)

VENUE = "kraken"
PAIR = "SUIUSD"
TF = "1h"
T0_S = 1_700_000_000
BAR_S = 3_600
CHUNK = 128

HEADER = ["time", "open", "high", "low", "close", "volume", "count"]

HEALTHY_BODY = "time,open,high,low,close,volume,count\n1700000000,1,2,1,1,10,1\n1700003600,2,3,2,2,10,1\n"
OPEN_NA_ROW = "1700007200,N/A,2,1,2,10,1\n"
VOLUME_DASH_ROW = "1700007200,1,2,1,2,--,1\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bar(ts_s: int, close: str) -> list[str]:
    px = Decimal(close)
    return [str(ts_s), close, str(px + Decimal("0.5")), str(px - Decimal("0.5")), close, "100", "5"]


def _bars(count: int, close_for=None) -> list[list[str]]:
    close_for = close_for or (lambda i: str(1 + (i % 9)))
    return [_bar(T0_S + i * BAR_S, close_for(i)) for i in range(count)]


def _candle_body(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(HEADER)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def _write_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in members.items():
            zf.writestr(name, body)
    return path


def _run_cli(home: Path, zip_path: Path, *, pair: str = PAIR, tf: str = TF, cwd: Path) -> subprocess.CompletedProcess:
    """Run the real `data import kraken-ohlcvt` CLI in a fresh subprocess."""
    env = dict(os.environ)
    env.update(
        {
            "KRELLBOT_HOME": str(home),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "KRELLBOT_LIVE": "0",
            "KRELLBOT_ENABLE_LIVE": "0",
            "KRELLBOT_API_LIVE": "0",
        }
    )
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "krellbot.cli",
            "data",
            "import",
            "kraken-ohlcvt",
            str(zip_path),
            "--pair",
            pair,
            "--timeframe",
            tf,
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        timeout=120,
        check=False,
    )


def _assert_typed_refusal(proc: subprocess.CompletedProcess, offending: str) -> None:
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, f"expected exit 1, got rc={proc.returncode} out={proc.stdout!r} err={proc.stderr!r}"
    assert proc.stderr.startswith("import refused:"), f"not the typed refusal path: {proc.stderr!r}"
    assert "Traceback" not in combined, f"raw traceback survived: {proc.stderr!r}"
    assert "InvalidOperation" not in combined, f"decimal crash leaked to the operator: {proc.stderr!r}"
    assert "wrote" not in proc.stdout, f"refusal printed a publication line: {proc.stdout!r}"
    assert offending in proc.stderr, f"refusal does not name the offending field {offending!r}: {proc.stderr!r}"


def _progress_dir(home: Path) -> Path:
    return Path(home) / "import-progress" / "kraken-ohlcvt"


def _slot_db(home: Path, zip_path: Path) -> Path:
    resolved = Path(zip_path).resolve()
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
    return _progress_dir(home) / f"{digest}.sqlite3"


def _db_candles(db: Path) -> int:
    import sqlite3

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
    finally:
        con.close()


def _db_meta(db: Path, key: str) -> str:
    import sqlite3

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()[0]
    finally:
        con.close()


def _snapshot(root: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = p.read_bytes()
    return out


# ---------------------------------------------------------------------------
# A. CLI witnesses: the parent's exact scenarios in fresh subprocesses.
# ---------------------------------------------------------------------------


def test_healthy_two_candle_control_writes_two_rows(tmp_path: Path):
    """Control (green on main): a healthy 2-candle zip writes rows=2, exit 0."""
    home = tmp_path / "kb"
    zip_path = _write_zip(tmp_path / "healthy.zip", {"SUIUSD_60.csv": HEALTHY_BODY.encode("utf-8")})

    proc = _run_cli(home, zip_path, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "rows=2" in proc.stdout
    assert "Traceback" not in proc.stderr
    published = read_cache(home, VENUE, PAIR, TF)
    assert published is not None
    candles, digest = published
    assert [c.ts_ms for c in candles] == [1_700_000_000_000, 1_700_003_600_000]
    assert [c.close for c in candles] == [Decimal(1), Decimal(2)]
    assert digest


def test_open_na_row_is_refused_without_traceback(tmp_path: Path):
    """RED on main: `open=N/A` crashed with a raw InvalidOperation traceback.

    The structurally admitted row must instead take the existing typed refusal
    path: `import refused: ...`, exit 1, nothing published.
    """
    home = tmp_path / "kb"
    body = HEALTHY_BODY + OPEN_NA_ROW
    zip_path = _write_zip(tmp_path / "open_na.zip", {"SUIUSD_60.csv": body.encode("utf-8")})

    proc = _run_cli(home, zip_path, cwd=tmp_path)
    _assert_typed_refusal(proc, "N/A")
    assert read_cache(home, VENUE, PAIR, TF) is None, "a refused import must not publish a cache"


def test_volume_dash_row_is_refused_without_traceback(tmp_path: Path):
    """RED on main: `volume=--` crashed with a raw InvalidOperation traceback."""
    home = tmp_path / "kb"
    body = HEALTHY_BODY + VOLUME_DASH_ROW
    zip_path = _write_zip(tmp_path / "volume_dash.zip", {"SUIUSD_60.csv": body.encode("utf-8")})

    proc = _run_cli(home, zip_path, cwd=tmp_path)
    _assert_typed_refusal(proc, "--")
    assert read_cache(home, VENUE, PAIR, TF) is None, "a refused import must not publish a cache"


# ---------------------------------------------------------------------------
# B. Unit contract of the shared `_row_to_candle` rule.
# ---------------------------------------------------------------------------


def test_row_to_candle_unit_admission_contract():
    """Healthy rows convert exactly; structural skips return None; bad decimals refuse.

    RED on main for the non-decimal fields: `Decimal('N/A')` raises
    InvalidOperation there instead of the typed ImportProgressError.
    """
    healthy = ["1700000000", "1.5", "2.5", "0.5", "2", "10", "1"]
    candle = _row_to_candle(healthy)
    assert candle is not None
    assert candle.ts_ms == 1_700_000_000_000
    assert candle.open == Decimal("1.5")
    assert candle.high == Decimal("2.5")
    assert candle.low == Decimal("0.5")
    assert candle.close == Decimal(2)
    assert candle.volume == Decimal(10)

    assert _row_to_candle(None) is None
    assert _row_to_candle([]) is None
    assert _row_to_candle(["time", "open", "high", "low", "close", "volume", "count"]) is None
    assert _row_to_candle(["1700000000", "1", "2", "1", "1", "10", "1", "extra"]) is None

    for field_index, bad in (
        (1, "N/A"),
        (2, "abc"),
        (3, ""),
        (4, "1,5"),
        (5, "--"),
    ):
        row = list(healthy)
        row[field_index] = bad
        with pytest.raises(ImportProgressError, match="non-decimal") as excinfo:
            _row_to_candle(row)
        assert bad in str(excinfo.value), f"refusal must name the offending value {bad!r}"


def test_row_is_candle_stays_structural_for_checkpoint_accounting():
    """`_row_is_candle` keeps the structural acceptance the checkpoint accounts.

    Acceptance stays exactly structural (non-empty, numeric first field, 7
    fields) and still never converts anything: a structurally admitted
    non-decimal row is accepted here and refused later by `_row_to_candle`, so
    the resume accounting of committed prefixes keeps matching the stored
    candle positions. Green on main and after the fix.
    """
    assert _row_is_candle(["1700000000", "N/A", "2", "1", "2", "--", "1"]) is True
    assert _row_is_candle(["1700000000", "1", "2", "1", "1", "10", "1"]) is True
    assert _row_is_candle(None) is False
    assert _row_is_candle([]) is False
    assert _row_is_candle(["time", "open", "high", "low", "close", "volume", "count"]) is False
    assert _row_is_candle(["1700000000", "1", "2", "1", "1", "10"]) is False
    assert _row_is_candle(["1700000000", "1", "2", "1", "1", "10", "1", "extra"]) is False


def test_stateless_zip_import_refuses_typed_on_bad_decimal(tmp_path: Path):
    """The stateless route shares the rule: typed refusal, not a decimal crash.

    RED on main: `import_kraken_ohlcvt_zip` propagates InvalidOperation.
    """
    body = HEALTHY_BODY + OPEN_NA_ROW
    zip_path = _write_zip(tmp_path / "stateless.zip", {"SUIUSD_60.csv": body.encode("utf-8")})
    with pytest.raises(ImportProgressError, match="N/A"):
        import_kraken_ohlcvt_zip(zip_path, pair=PAIR, tf=TF)


def test_cached_direct_call_refuses_typed_and_keeps_pending_checkpoint(tmp_path: Path):
    """Direct cached call: ImportProgressError out, pending checkpoint intact, no cache.

    RED on main: the direct call raises InvalidOperation instead.
    """
    home = tmp_path / "kb"
    body = HEALTHY_BODY + VOLUME_DASH_ROW
    zip_path = _write_zip(tmp_path / "cached.zip", {"SUIUSD_60.csv": body.encode("utf-8")})

    with pytest.raises(ImportProgressError, match="--"):
        import_kraken_ohlcvt_cached(zip_path, pair=PAIR, tf=TF, home=home)

    db = _slot_db(home, zip_path)
    assert db.is_file(), "the refusal must leave the pending checkpoint, not reset it"
    assert _db_candles(db) == 0, "the bad row sits before the first chunk boundary"
    assert read_cache(home, VENUE, PAIR, TF) is None


# ---------------------------------------------------------------------------
# C. Controls unchanged: structural skips and healthy decimal shapes.
# ---------------------------------------------------------------------------


def test_structural_skips_still_skip(tmp_path: Path):
    """Green on main: header, non-numeric timestamp, blank and wrong-width rows skip.

    The import still succeeds with exactly the two healthy candles, through
    both the stateless parser and the enabled CLI route.
    """
    body = (
        "time,open,high,low,close,volume,count\n"
        "\n"
        "1700000000,1,2,1,1,10,1\n"
        "garbage,not,numeric,skipped,x,y,z\n"
        "1700003600,2,3,2,2,10,1\n"
        "1700007200,3,4,2,3,10,1,extra\n"
    )
    zip_path = _write_zip(tmp_path / "skips.zip", {"SUIUSD_60.csv": body.encode("utf-8")})

    expected = import_kraken_ohlcvt_zip(zip_path, pair=PAIR, tf=TF)
    assert [(c.ts_ms, c.close) for c in expected] == [
        (1_700_000_000_000, Decimal(1)),
        (1_700_003_600_000, Decimal(2)),
    ]

    home = tmp_path / "kb"
    proc = _run_cli(home, zip_path, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "rows=2" in proc.stdout
    published = read_cache(home, VENUE, PAIR, TF)
    assert published is not None
    assert [(c.ts_ms, c.close) for c in published[0]] == [(c.ts_ms, c.close) for c in expected]


def test_healthy_decimal_shapes_still_import(tmp_path: Path):
    """Green on main: every decimal text Decimal already accepts keeps importing.

    Scientific notation, signs, leading zeros and padded whitespace were
    accepted on main and must stay accepted byte-identically; the admission
    fix may not swap Decimal for a narrower digit check.
    """
    body = "time,open,high,low,close,volume,count\n1700000000,1.5E+2,2,-0.5,+2.25,1e3,1\n1700003600, 3 ,4,2,3,10,1\n"
    zip_path = _write_zip(tmp_path / "shapes.zip", {"SUIUSD_60.csv": body.encode("utf-8")})

    home = tmp_path / "kb"
    proc = _run_cli(home, zip_path, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "rows=2" in proc.stdout

    published = read_cache(home, VENUE, PAIR, TF)
    assert published is not None
    first, second = published[0]
    assert (first.open, first.high, first.low, first.close, first.volume) == (
        Decimal("1.5E+2"),
        Decimal(2),
        Decimal("-0.5"),
        Decimal("2.25"),
        Decimal("1e3"),
    )
    assert (second.open, second.close) == (Decimal(3), Decimal(3))


# ---------------------------------------------------------------------------
# D. No publication on refusal; checkpoint/resume coherence after a refusal.
# ---------------------------------------------------------------------------


def test_refusal_publishes_nothing_and_preserves_prior_cache(tmp_path: Path):
    """RED on main: a refused import leaves every published byte untouched.

    A prior healthy SUIUSD/1h dataset exists; the refused import of the
    corrupt archive must not write or move any cache, manifest or dataset
    version byte, and must not clobber the prior candles.
    """
    home = tmp_path / "kb"
    prior_zip = _write_zip(tmp_path / "prior.zip", {"SUIUSD_60.csv": _candle_body(_bars(4, lambda i: "7"))})
    assert _run_cli(home, prior_zip, cwd=tmp_path).returncode == 0
    prior = read_cache(home, VENUE, PAIR, TF)
    assert prior is not None
    prior_cache_bytes = _snapshot(Path(home) / "cache")
    prior_dataset_bytes = _snapshot(Path(home) / "datasets")

    bad_zip = _write_zip(
        tmp_path / "bad.zip",
        {"SUIUSD_60.csv": (_candle_body(_bars(2)) + OPEN_NA_ROW.encode("utf-8"))},
    )
    proc = _run_cli(home, bad_zip, cwd=tmp_path)
    _assert_typed_refusal(proc, "N/A")

    assert _snapshot(Path(home) / "cache") == prior_cache_bytes, "refusal rewrote cache bytes"
    assert _snapshot(Path(home) / "datasets") == prior_dataset_bytes, "refusal rewrote dataset version bytes"
    after = read_cache(home, VENUE, PAIR, TF)
    assert after is not None
    assert [c.close for c in after[0]] == [Decimal(7)] * 4, "the prior dataset must survive the refusal"


def test_resume_after_refusal_still_refuses_cleanly(tmp_path: Path):
    """RED on main: a resumed import never resurrects the decimal crash.

    200 healthy candles commit one 128-candle chunk, then `open=N/A` refuses.
    A second fresh process at the same home must re-validate the committed
    chunk against the source (checkpoint/resume coherence) and refuse again
    identically - same typed refusal, same committed 128 candles, still no
    publication - never a raw InvalidOperation traceback.
    """
    home = tmp_path / "kb"
    rows = _bars(200) + [[str(T0_S + 200 * BAR_S), "N/A", "2", "1", "2", "10", "1"]]
    zip_path = _write_zip(tmp_path / "resume.zip", {"SUIUSD_60.csv": _candle_body(rows)})

    first = _run_cli(home, zip_path, cwd=tmp_path)
    _assert_typed_refusal(first, "N/A")

    db = _slot_db(home, zip_path)
    assert db.is_file(), "the refused import must leave its pending checkpoint"
    assert _db_candles(db) == CHUNK, "the committed 128-candle chunk must be durable"
    assert json.loads(_db_meta(db, "cursor_json"))["phase"] == "parsing"
    assert read_cache(home, VENUE, PAIR, TF) is None

    second = _run_cli(home, zip_path, cwd=tmp_path)
    _assert_typed_refusal(second, "N/A")
    assert _db_candles(db) == CHUNK, "the retry must not commit the refused row's prefix twice"
    assert json.loads(_db_meta(db, "cursor_json"))["phase"] == "parsing"
    assert read_cache(home, VENUE, PAIR, TF) is None, "no partial publication after the retry"

    healthy_zip = _write_zip(tmp_path / "clean.zip", {"SUIUSD_60.csv": _candle_body(_bars(2))})
    clean_home = tmp_path / "clean-kb"
    assert _run_cli(clean_home, healthy_zip, cwd=tmp_path).returncode == 0
    assert read_cache(clean_home, VENUE, PAIR, TF) is not None, "unrelated healthy imports still publish"
