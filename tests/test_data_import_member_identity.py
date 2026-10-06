"""B06/t_badbc7ae: `data import kraken-ohlcvt` selects members by identity.

A zip member is an OHLCVT payload for the requested market only when its
complete basename stem equals `pair + '_' + exact interval minutes`
(case-insensitive) with a `.csv` suffix (case-insensitive, plus the legacy
`.zip`-named CSV fixture pinned by `tests/test_data_kraken.py`). The member's
parent directory cannot supply a missing pair or interval token, so
`folder60/SUIUSD_240.csv` is a 4h member regardless of the archive layout and
`SUIUSD_60/BTCUSD_60.csv` is a BTCUSD 1h member, not a SUIUSD one.

Old production matched by substring over the full archive path, so it happily
persisted candles from the wrong market and the wrong timeframe as a
successful import of the requested one (SUIUSDT_60.csv under a SUIUSD
request, SUIUSD_160.csv, folder60/SUIUSD_240.csv and SUIUSD_60/BTCUSD_60.csv
under a SUIUSD/1h request). These cases are wrong persisted candles, not
fixture or API errors, and they are what the tests below pin.

The suites drive the real CLI `main` with `argv[0]='krellbot'` and an isolated
`KRELLBOT_HOME`. Unmatched members must never be opened, which is proven with
a near-collision member whose payload is not parseable as candles: a candidate
that opens it cannot produce the pinned result.

Scope guard: this fixes import member identity only. It is not an availability
pass over Kraken's published archives, adds no download or source policy, no
alias expansion, no gap filling and no dedup change. Missing-data behavior
beyond the exact absent-match case pinned here is out of scope.
"""

from __future__ import annotations

import csv as _csv
import io
import json
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot import cli
from krellbot.data.cache import (
    cache_path,
    dataset_version_path,
    manifest_path,
    read_cache,
    sha256_bytes,
)
from krellbot.data.kraken_public import import_kraken_ohlcvt_zip

VENUE = "kraken"
PAIR = "SUIUSD"
TF = "1h"
T0_S = 1_700_000_000
BAR_S = 3_600

HEADER = ["time", "open", "high", "low", "close", "volume", "count"]


def _candle_body(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(HEADER)
    for row in rows:
        w.writerow(row)
    return buf.getvalue().encode("utf-8")


def _bar(ts_s: int, close: str) -> list[str]:
    px = Decimal(close)
    return [str(ts_s), close, str(px + Decimal("0.5")), str(px - Decimal("0.5")), close, "100", "5"]


def _write_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in members.items():
            zf.writestr(name, body)
    return path


def _import(home: Path, zip_path: Path, pair: str, tf: str, capsys) -> int:
    return cli.main(
        [
            "krellbot",
            "data",
            "import",
            "kraken-ohlcvt",
            str(zip_path),
            "--pair",
            pair,
            "--timeframe",
            tf,
        ]
    )


def _closes(home: Path, pair: str = PAIR, tf: str = TF) -> list[Decimal]:
    out = read_cache(home, VENUE, pair, tf)
    assert out is not None, f"no cache for {pair}/{tf}"
    candles, _sha = out
    return [c.close for c in candles]


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    monkeypatch.setenv("KRELLBOT_HOME", str(kb))
    monkeypatch.setenv("HOME", str(kb))
    monkeypatch.setenv("USERPROFILE", str(kb))
    monkeypatch.setattr("pathlib.Path.home", lambda: kb)
    return kb


# ---------------------------------------------------------------------------
# A. Quote-currency conflation: SUIUSDT is not SUIUSD.
# ---------------------------------------------------------------------------


def test_suiusdt_member_is_not_imported_as_suiusd(home: Path, tmp_path: Path, capsys):
    """RED on old production: SUIUSDT_60.csv is a successful SUIUSD import.

    The substring test `pair.lower() in name.lower()` admits SUIUSDT_60.csv
    under a SUIUSD request, so the cache ends up holding the SUIUSDT close 99
    next to the SUIUSD close 1. Only the exact SUIUSD_60.csv member belongs to
    the requested market.
    """
    zip_path = _write_zip(
        tmp_path / "kraken.zip",
        {
            "SUIUSD_60.csv": _candle_body([_bar(T0_S, "1")]),
            "SUIUSDT_60.csv": _candle_body([_bar(T0_S + BAR_S, "99")]),
        },
    )
    rc = _import(home, zip_path, PAIR, TF, capsys)
    assert rc == 0, capsys.readouterr().err
    assert _closes(home) == [Decimal(1)]

    manifest = json.loads(manifest_path(home, VENUE, PAIR, TF).read_text(encoding="utf-8"))
    assert manifest["venue"] == VENUE
    assert manifest["pair"] == PAIR
    assert manifest["tf"] == TF
    assert manifest["rows"] == 1
    body = cache_path(home, VENUE, PAIR, TF).read_bytes()
    assert manifest["sha256"] == sha256_bytes(body)

    # B05 retention: the exact imported canonical CSV bytes are retrievable.
    retained = dataset_version_path(home, VENUE, PAIR, TF, manifest["sha256"])
    assert retained.exists()
    assert retained.read_bytes() == body


def test_reverse_quote_member_is_not_imported_as_suiusdt(home: Path, tmp_path: Path, capsys):
    """The reverse direction: requesting SUIUSDT must not take SUIUSD candles."""
    zip_path = _write_zip(
        tmp_path / "kraken.zip",
        {
            "SUIUSD_60.csv": _candle_body([_bar(T0_S, "1")]),
            "SUIUSDT_60.csv": _candle_body([_bar(T0_S + BAR_S, "99")]),
        },
    )
    rc = _import(home, zip_path, "SUIUSDT", TF, capsys)
    assert rc == 0, capsys.readouterr().err
    assert _closes(home, pair="SUIUSDT") == [Decimal(99)]


# ---------------------------------------------------------------------------
# B. Interval identity: substring minutes are not the requested timeframe.
# ---------------------------------------------------------------------------


def test_interval_substring_members_are_excluded(home: Path, tmp_path: Path, capsys):
    """RED on old production: 160 contains 60 and 60/240 in the path match too.

    Old production tested `minutes in name`, so SUIUSD_160.csv matched a 1h
    request; and because the directory part of the member name also carried the
    token, folder60/SUIUSD_240.csv and SUIUSD_60/BTCUSD_60.csv were imported as
    SUIUSD/1h candles. Only the complete basename SUIUSD_60.csv is a SUIUSD 1h
    member.
    """
    zip_path = _write_zip(
        tmp_path / "kraken.zip",
        {
            "SUIUSD_60.csv": _candle_body([_bar(T0_S, "1")]),
            "SUIUSD_160.csv": _candle_body([_bar(T0_S + BAR_S, "99")]),
            "folder60/SUIUSD_240.csv": _candle_body([_bar(T0_S + 2 * BAR_S, "88")]),
            "SUIUSD_60/BTCUSD_60.csv": _candle_body([_bar(T0_S + 3 * BAR_S, "77")]),
        },
    )
    rc = _import(home, zip_path, PAIR, TF, capsys)
    assert rc == 0, capsys.readouterr().err
    assert _closes(home) == [Decimal(1)]


def test_sibling_interval_member_selected_by_requested_timeframe(home: Path, tmp_path: Path, capsys):
    """240 is imported for 4h and not for 1h, from the same archive."""
    zip_path = _write_zip(
        tmp_path / "kraken.zip",
        {
            "SUIUSD_60.csv": _candle_body([_bar(T0_S, "1")]),
            "SUIUSD_240.csv": _candle_body([_bar(T0_S + BAR_S, "88")]),
        },
    )
    rc = _import(home, zip_path, PAIR, "4h", capsys)
    assert rc == 0, capsys.readouterr().err
    assert _closes(home, tf="4h") == [Decimal(88)]

    rc = _import(home, zip_path, PAIR, TF, capsys)
    assert rc == 0, capsys.readouterr().err
    assert _closes(home, tf=TF) == [Decimal(1)]


def test_daily_1440_member_matches_only_the_1d_request(home: Path, tmp_path: Path, capsys):
    """1440 is the 1d token; 144 must not match it as a substring."""
    zip_path = _write_zip(
        tmp_path / "kraken.zip",
        {
            "SUIUSD_1440.csv": _candle_body([_bar(T0_S, "5")]),
            "SUIUSD_144.csv": _candle_body([_bar(T0_S + BAR_S, "99")]),
        },
    )
    rc = _import(home, zip_path, PAIR, "1d", capsys)
    assert rc == 0, capsys.readouterr().err
    assert _closes(home, tf="1d") == [Decimal(5)]

    # No SUIUSD/1h member exists, so a 1h request writes no candles for it.
    rc = _import(home, zip_path, PAIR, TF, capsys)
    assert rc == 0, capsys.readouterr().err
    out = read_cache(home, VENUE, PAIR, TF)
    assert out is not None
    assert out[0] == []


def test_unmatched_members_are_never_opened(home: Path, tmp_path: Path, capsys):
    """A near-collision member with malformed payloads stays unopened.

    SUIUSDT_60.csv, SUIUSD_160.csv and folder60/SUIUSD_240.csv do not belong to
    the SUIUSD/1h identity. Their bodies here carry rows that raise when parsed
    (numeric timestamp, seven fields, non-numeric price), so a matcher that
    opens any of them cannot complete the import; the candidate ignores them
    before opening and imports only the exact-match control member.
    """
    malformed = "time,open,high,low,close,volume,count\n1700007200,not-a-price,2,1,1,10,1\n"
    zip_path = _write_zip(
        tmp_path / "kraken.zip",
        {
            "SUIUSD_60.csv": _candle_body([_bar(T0_S, "1")]),
            "SUIUSDT_60.csv": malformed,
            "SUIUSD_160.csv": malformed,
            "folder60/SUIUSD_240.csv": malformed,
        },
    )
    rc = _import(home, zip_path, PAIR, TF, capsys)
    assert rc == 0, capsys.readouterr().err
    assert _closes(home) == [Decimal(1)]


# ---------------------------------------------------------------------------
# C. Preserved semantics: case-insensitive exact stem, .zip-named CSV, sorted
#    multi-member merge, unsupported timeframe, absent match.
# ---------------------------------------------------------------------------


def test_exact_match_semantics_preserved(home: Path, tmp_path: Path, capsys):
    """Valid control: lowercase request, case-mixed .CSV and legacy .zip member.

    `sUiUsD_60.CSV` and `SUIUSD_60.zip` (a CSV payload under a .zip name, as
    pinned by `tests/test_data_kraken.py`) both remain exact matches for a
    lowercase `suiusd/1h` request, sorted ascending with exact timestamps, and
    B05 version retention keeps the merged canonical bytes.
    """
    body_a = _candle_body([_bar(T0_S, "1")])
    body_b = "time,open,high,low,close,volume,count\n1700003600,2,2.5,1.5,2,100,5\n"
    zip_path = _write_zip(
        tmp_path / "kraken.zip",
        {
            "nested/sUiUsD_60.CSV": body_b,
            "SUIUSD_60.zip": body_a,
        },
    )
    rc = _import(home, zip_path, "suiusd", TF, capsys)
    assert rc == 0, capsys.readouterr().err
    out = read_cache(home, VENUE, "suiusd", TF)
    assert out is not None
    candles, sha = out
    assert [c.close for c in candles] == [Decimal(1), Decimal(2)]
    assert [c.ts_ms for c in candles] == [T0_S * 1000, (T0_S + BAR_S) * 1000]
    body = cache_path(home, VENUE, "suiusd", TF).read_bytes()
    assert sha == sha256_bytes(body)
    assert dataset_version_path(home, VENUE, "suiusd", TF, sha).read_bytes() == body


def test_unsupported_timeframe_is_refused(home: Path, tmp_path: Path, capsys):
    """Unsupported tf stays refused: rc 1 at the CLI, ValueError underneath.

    The CLI rejects the timeframe before any member is read; the importer
    keeps its public ValueError for the same input.
    """
    zip_path = _write_zip(tmp_path / "kraken.zip", {"SUIUSD_60.csv": _candle_body([_bar(T0_S, "1")])})
    argv = [
        "krellbot",
        "data",
        "import",
        "kraken-ohlcvt",
        str(zip_path),
        "--pair",
        PAIR,
        "--timeframe",
        "2h",
    ]
    rc = cli.main(argv)
    assert rc == 1
    assert "Unsupported timeframe" in capsys.readouterr().err
    assert read_cache(home, VENUE, PAIR, TF) is None
    with pytest.raises(ValueError):
        import_kraken_ohlcvt_zip(zip_path, pair=PAIR, tf="2h")


def test_absent_match_imports_no_cross_market_candles(home: Path, tmp_path: Path, capsys):
    """No exact member means no candles; other markets stay other markets.

    With no SUIUSD_60.csv in the archive the import succeeds with zero rows
    (the existing no-matching-member behavior, unchanged by this leaf) and
    nothing from another market leaks into SUIUSD/1h. This pins the exact
    absent-match boundary only. It is not a claim that the CLI's missing-data
    behavior is fully qualified.
    """
    zip_path = _write_zip(
        tmp_path / "kraken.zip",
        {
            "BTCUSD_60.csv": _candle_body([_bar(T0_S, "100")]),
            "SUIUSD_240.csv": _candle_body([_bar(T0_S + BAR_S, "88")]),
        },
    )
    rc = _import(home, zip_path, PAIR, TF, capsys)
    assert rc == 0, capsys.readouterr().err
    out = read_cache(home, VENUE, PAIR, TF)
    assert out is not None
    assert out[0] == []
    assert read_cache(home, VENUE, "BTCUSD", TF) is None


def test_directory_entry_name_does_not_satisfy_the_identity(home: Path, tmp_path: Path, capsys):
    """A member whose stem is only the pair or only the interval is not a match.

    `SUIUSD.csv` (no interval token) and `_60.csv` (no pair token) never belong
    to the SUIUSD/1h identity even though their names contain both substrings
    somewhere across the path.
    """
    zip_path = _write_zip(
        tmp_path / "kraken.zip",
        {
            "SUIUSD_60.csv": _candle_body([_bar(T0_S, "1")]),
            "60/SUIUSD.csv": _candle_body([_bar(T0_S + BAR_S, "99")]),
            "SUIUSD/_60.csv": _candle_body([_bar(T0_S + 2 * BAR_S, "88")]),
        },
    )
    rc = _import(home, zip_path, PAIR, TF, capsys)
    assert rc == 0, capsys.readouterr().err
    assert _closes(home) == [Decimal(1)]
