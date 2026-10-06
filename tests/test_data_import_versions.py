"""B05/t_6d8d57a5: `data import kraken-ohlcvt` retains every imported version.

`write_cache` intentionally replaces the stable cache CSV and legacy manifest
for a market, so a second valid import of the same market changes the bytes at
the stable path and no managed path holds the old CSV anymore. This suite pins
the complementary behavior: each newly emitted canonical CSV plus its EXACT
legacy manifest bytes is also stored immutably, content-addressed by its own
sha256, under `<home>/datasets/imported/<cache_csv_stem>/<sha256>.csv` and
`<sha256>.manifest.json`, so a recorded digest stays retrievable after the
stable cache moves on.

Retention assertions derive the expected layout locally (see `_version_csv`)
so a candidate that lacks retention fails on missing bytes, not on an import
error. The production helpers `dataset_version_path` /
`dataset_version_manifest_path` are pinned separately.

Scope guard: this is a retention record for the imported canonical candle
dataset, not the caller-owned zip and not a full raw/derived data manager. The
manifest keeps its existing legacy shape (sha256, rows, venue, pair, tf). No
source/version/window/coverage metadata is invented here.

The suites are driven through the real CLI `main` with `argv[0]='krellbot'`
and two isolated zips holding `SUIUSD_60.csv`: 8 contiguous closed bars at
seconds `1700000000+i*3600`, first closing 10,10,12,14,8,8,8,8 and second
20,20,24,28,16,16,16,16.
"""

from __future__ import annotations

import csv as _csv
import io
import json
import os
import stat
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot import cli
from krellbot.application.research import ResearchRequest, ResearchService
from krellbot.data.cache import (
    cache_path,
    manifest_path,
    read_cache,
    sha256_bytes,
    write_cache,
)
from krellbot.pack.model import Candle

CLOSES_FIRST = ["10", "10", "12", "14", "8", "8", "8", "8"]
CLOSES_SECOND = ["20", "20", "24", "28", "16", "16", "16", "16"]
T0_S = 1_700_000_000
BAR_S = 3_600

VENUE = "kraken"
PAIR = "SUIUSD"
TF = "1h"

PACK_DICT = {
    "schema_version": 1,
    "id": "sma-cross-versions",
    "version": "1.0.0",
    "label": "SMA cross (import versions)",
    "author": "krellbot tests",
    "origin": "Backtest fixture for import version retention.",
    "timeframe": "1h",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", "crosses_above", "sma2"],
    "exit": ["close", "crosses_below", "sma2"],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
}


def _write_zip(path: Path, closes: list[str]) -> Path:
    """One OHLCVT member named SUIUSD_60.csv with 8 contiguous closed 1h bars."""
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["time", "open", "high", "low", "close", "volume", "count"])
    for i, close in enumerate(closes):
        px = Decimal(close)
        w.writerow([T0_S + i * BAR_S, close, str(px + Decimal("0.5")), str(px - Decimal("0.5")), close, "100", "5"])
    body = buf.getvalue().encode("utf-8")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("SUIUSD_60.csv", body)
    return path


def _write_pack(path: Path) -> Path:
    path.write_text(json.dumps(PACK_DICT), encoding="utf-8")
    return path


def _version_csv(home: Path, venue: str, pair: str, tf: str, digest: str) -> Path:
    """Expected retention path, derived locally from the required layout."""
    stem = cache_path(home, venue, pair, tf).stem
    return Path(home) / "datasets" / "imported" / stem / f"{digest}.csv"


def _version_manifest(home: Path, venue: str, pair: str, tf: str, digest: str) -> Path:
    return _version_csv(home, venue, pair, tf, digest).with_suffix(".manifest.json")


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    monkeypatch.setenv("KRELLBOT_HOME", str(kb))
    return kb


def _import_zip(home: Path, zip_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[Path, str]:
    rc = cli.main(
        [
            "krellbot",
            "data",
            "import",
            "kraken-ohlcvt",
            str(zip_path),
            "--pair",
            PAIR,
            "--timeframe",
            TF,
        ]
    )
    assert rc == 0, capsys.readouterr().err
    return cache_path(home, VENUE, PAIR, TF), read_cache(home, VENUE, PAIR, TF)[1]


# ---------------------------------------------------------------------------
# A. Retention across a second same-market import.
# ---------------------------------------------------------------------------


def test_second_import_retains_first_version_bytes(home: Path, tmp_path: Path, capsys):
    """After a second import the first CSV+manifest are still retrievable.

    This is the retention assertion that is RED on old production: the stable
    cache held only the second import's bytes and no managed path kept the
    first import's CSV.
    """
    z1 = _write_zip(tmp_path / "first.zip", CLOSES_FIRST)
    z2 = _write_zip(tmp_path / "second.zip", CLOSES_SECOND)

    stable1, digest1 = _import_zip(home, z1, capsys)
    csv1 = stable1.read_bytes()
    man1 = manifest_path(home, VENUE, PAIR, TF).read_bytes()

    stable2, digest2 = _import_zip(home, z2, capsys)
    assert digest1 != digest2
    assert stable2 == stable1
    body2 = stable2.read_bytes()
    assert body2 != csv1

    v_csv = _version_csv(home, VENUE, PAIR, TF, digest1)
    v_man = _version_manifest(home, VENUE, PAIR, TF, digest1)
    assert v_csv == home / "datasets" / "imported" / "kraken__SUIUSD__1h" / f"{digest1}.csv", v_csv
    assert v_man.name == f"{digest1}.manifest.json"
    assert v_csv.exists(), f"first import CSV not retained at {v_csv}"
    assert v_csv.read_bytes() == csv1
    assert v_man.exists(), f"first import manifest not retained at {v_man}"
    assert v_man.read_bytes() == man1

    # The second version is stored too, and the stable cache holds exactly it.
    v2_csv = _version_csv(home, VENUE, PAIR, TF, digest2)
    v2_man = _version_manifest(home, VENUE, PAIR, TF, digest2)
    assert v2_csv.exists(), f"second import CSV not retained at {v2_csv}"
    assert v2_csv.read_bytes() == body2
    assert v2_man.read_bytes() == manifest_path(home, VENUE, PAIR, TF).read_bytes()

    assert sha256_bytes(body2) == digest2
    out = read_cache(home, VENUE, PAIR, TF)
    assert out is not None
    candles2, sha2 = out
    assert sha2 == digest2
    assert [str(c.close) for c in candles2] == CLOSES_SECOND


def test_stable_cache_replaced_by_second_import(home: Path, tmp_path: Path, capsys):
    """Stable replaceable-cache behavior stays intact: second import wins."""
    z1 = _write_zip(tmp_path / "first.zip", CLOSES_FIRST)
    z2 = _write_zip(tmp_path / "second.zip", CLOSES_SECOND)
    stable, digest1 = _import_zip(home, z1, capsys)
    csv1 = stable.read_bytes()
    stable, digest2 = _import_zip(home, z2, capsys)

    assert stable == cache_path(home, VENUE, PAIR, TF)
    assert stable.read_bytes() != csv1
    out = read_cache(home, VENUE, PAIR, TF)
    assert out is not None
    candles, sha = out
    assert sha == digest2
    assert [str(c.close) for c in candles] == CLOSES_SECOND


def test_identical_reimport_reuses_existing_version_untouched(home: Path, tmp_path: Path, capsys):
    """Repeating identical input reuses the version without rewriting it."""
    z = _write_zip(tmp_path / "same.zip", CLOSES_FIRST)
    stable, digest = _import_zip(home, z, capsys)
    v_csv = _version_csv(home, VENUE, PAIR, TF, digest)
    v_man = _version_manifest(home, VENUE, PAIR, TF, digest)
    assert v_csv.exists(), f"version CSV missing at {v_csv}"
    before_csv = v_csv.read_bytes()
    man_marked = v_man.stat()

    # Pin an unmistakable mtime so any rewrite is detectable.
    os.utime(v_csv, (1_000_000, 1_000_000))
    marked = v_csv.stat()
    assert marked.st_mtime_ns == 1_000_000_000_000_000

    stable2, digest2 = _import_zip(home, z, capsys)
    assert digest2 == digest
    assert v_csv.stat().st_mtime_ns == marked.st_mtime_ns
    assert v_csv.stat().st_ino == marked.st_ino
    assert v_csv.read_bytes() == before_csv
    assert v_man.stat().st_mtime_ns == man_marked.st_mtime_ns
    assert v_man.stat().st_ino == man_marked.st_ino
    assert stable2 == stable


def test_version_files_are_0600(home: Path, tmp_path: Path, capsys):
    """Immutable version files are owner-only on POSIX."""
    z = _write_zip(tmp_path / "first.zip", CLOSES_FIRST)
    _, digest = _import_zip(home, z, capsys)
    for p in (
        _version_csv(home, VENUE, PAIR, TF, digest),
        _version_manifest(home, VENUE, PAIR, TF, digest),
    ):
        assert p.exists(), p
        assert stat.S_IMODE(p.stat().st_mode) == 0o600, p


def test_version_store_holds_legacy_manifest_exactly(home: Path, tmp_path: Path, capsys):
    """The retained manifest keeps the legacy shape and byte-exact serialization."""
    z = _write_zip(tmp_path / "first.zip", CLOSES_FIRST)
    _, digest = _import_zip(home, z, capsys)
    man_bytes = _version_manifest(home, VENUE, PAIR, TF, digest).read_bytes()
    assert man_bytes == manifest_path(home, VENUE, PAIR, TF).read_bytes()
    man = json.loads(man_bytes.decode("utf-8"))
    assert man == {
        "sha256": digest,
        "rows": 8,
        "venue": VENUE,
        "pair": PAIR,
        "tf": TF,
    }


def test_version_dir_uses_cache_stem_with_pair_slash_convention(tmp_path: Path):
    """The version dir is the cache CSV stem, including slash-to-underscore."""
    p = _version_csv(tmp_path, "kraken", "SUI/USD", "1h", "a" * 64)
    assert p == tmp_path / "datasets" / "imported" / "kraken__SUI_USD__1h" / ("a" * 64 + ".csv")


# ---------------------------------------------------------------------------
# A2. The production helpers expose the same layout and validate digests.
# ---------------------------------------------------------------------------


def test_dataset_version_helpers_match_required_layout(tmp_path: Path):
    from krellbot.data.cache import dataset_version_manifest_path, dataset_version_path

    digest = "b" * 64
    for venue, pair, tf in (("kraken", "SUIUSD", "1h"), ("coinbase", "BTC/USD", "1d")):
        assert dataset_version_path(tmp_path, venue, pair, tf, digest) == _version_csv(
            tmp_path, venue, pair, tf, digest
        )
        assert dataset_version_manifest_path(tmp_path, venue, pair, tf, digest) == _version_manifest(
            tmp_path, venue, pair, tf, digest
        )
    assert dataset_version_path(tmp_path, "kraken", "SUIUSD", "1h", digest) == (
        tmp_path / "datasets" / "imported" / "kraken__SUIUSD__1h" / f"{digest}.csv"
    )


def test_dataset_version_helpers_reject_bad_digests(tmp_path: Path):
    """Digests must be exactly 64 lowercase hex chars; no traversal."""
    from krellbot.data.cache import dataset_version_manifest_path, dataset_version_path

    for bad in [
        "A" * 64,
        "z" * 64,
        "a" * 63,
        "a" * 65,
        "../" + "a" * 61,
        "a" * 62 + "..",
        "a" * 63 + "/",
        "",
        "a" * 62 + "gg",
        "a" * 63 + ".",
    ]:
        with pytest.raises(ValueError):
            dataset_version_path(tmp_path, "kraken", "SUIUSD", "1h", bad)
        with pytest.raises(ValueError):
            dataset_version_manifest_path(tmp_path, "kraken", "SUIUSD", "1h", bad)


# ---------------------------------------------------------------------------
# B. Enabled consumers keep working against the stable cache and the retained
#    first version.
# ---------------------------------------------------------------------------


def test_research_reads_stable_cache_after_second_import(home: Path, tmp_path: Path, capsys):
    z1 = _write_zip(tmp_path / "first.zip", CLOSES_FIRST)
    z2 = _write_zip(tmp_path / "second.zip", CLOSES_SECOND)
    pack = _write_pack(tmp_path / "pack.json")
    _import_zip(home, z1, capsys)
    _, digest2 = _import_zip(home, z2, capsys)
    body2 = cache_path(home, VENUE, PAIR, TF).read_bytes()
    assert sha256_bytes(body2) == digest2

    svc = ResearchService(home=home, fetch=None)
    result = svc.run(
        ResearchRequest(
            pack_path=pack,
            dataset_csv=cache_path(home, VENUE, PAIR, TF),
            venue=VENUE,
        )
    )
    assert result.ok is True, result.refusal
    assert result.legacy_receipt["data_manifest_sha256"] == digest2


def test_cli_backtest_without_data_reads_cache_no_network(home: Path, tmp_path: Path, capsys, monkeypatch):
    """CLI backtest without --data reads the cache; the fetch spy is not called."""
    z1 = _write_zip(tmp_path / "first.zip", CLOSES_FIRST)
    z2 = _write_zip(tmp_path / "second.zip", CLOSES_SECOND)
    pack = _write_pack(tmp_path / "pack.json")
    _import_zip(home, z1, capsys)
    _, digest2 = _import_zip(home, z2, capsys)
    capsys.readouterr()

    calls: list[tuple[str, str, str]] = []

    def _spy(venue, pair, tf, transport):
        calls.append((venue, pair, tf))
        raise AssertionError("fetch must not be called when the cache is present")

    monkeypatch.setattr(cli, "_default_fetch", _spy)
    monkeypatch.setattr(cli, "_default_transport", lambda: None)

    rc = cli.main(["krellbot", "backtest", str(pack), "--venue", "kraken", "--json"])
    assert rc == 0, capsys.readouterr().err
    assert calls == []
    receipt = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert receipt["data_manifest_sha256"] == digest2

    direct = ResearchService(home=home, fetch=None).run(
        ResearchRequest(
            pack_path=pack,
            dataset_csv=cache_path(home, VENUE, PAIR, TF),
            venue=VENUE,
        )
    )
    assert direct.ok is True
    assert json.dumps(receipt, sort_keys=True) == json.dumps(direct.legacy_receipt, sort_keys=True)


def test_cli_backtest_explicit_data_first_version_still_runs(home: Path, tmp_path: Path, capsys):
    """--data pointing at the retained FIRST version succeeds and hashes first bytes."""
    z1 = _write_zip(tmp_path / "first.zip", CLOSES_FIRST)
    z2 = _write_zip(tmp_path / "second.zip", CLOSES_SECOND)
    pack = _write_pack(tmp_path / "pack.json")
    _, digest1 = _import_zip(home, z1, capsys)
    csv1 = cache_path(home, VENUE, PAIR, TF).read_bytes()
    _, digest2 = _import_zip(home, z2, capsys)
    assert sha256_bytes(csv1) == digest1
    capsys.readouterr()

    first_csv = _version_csv(home, VENUE, PAIR, TF, digest1)
    assert first_csv.exists(), f"retained first version missing at {first_csv}"
    assert first_csv.read_bytes() == csv1

    rc = cli.main(
        ["krellbot", "backtest", str(pack), "--venue", "kraken", "--data", str(first_csv), "--json"]
    )
    assert rc == 0, capsys.readouterr().err
    receipt = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert receipt["data_manifest_sha256"] == digest1


# ---------------------------------------------------------------------------
# C. Direct write_cache behavior + typed refusals stay as they were.
# ---------------------------------------------------------------------------


def _candles(closes: list[str]) -> list[Candle]:
    out = []
    for i, close in enumerate(closes):
        px = Decimal(close)
        out.append(
            Candle(
                ts_ms=(T0_S + i * BAR_S) * 1000,
                open=px,
                high=px,
                low=px,
                close=px,
                volume=Decimal(100),
            )
        )
    return out


def test_write_cache_still_returns_stable_path_and_digest(tmp_path: Path):
    candles = _candles(CLOSES_FIRST)
    csv_path, digest = write_cache(tmp_path, VENUE, PAIR, TF, candles)
    assert csv_path == tmp_path / "cache" / "kraken__SUIUSD__1h.csv"
    assert sha256_bytes(csv_path.read_bytes()) == digest
    assert _version_csv(tmp_path, VENUE, PAIR, TF, digest).exists()
    out = read_cache(tmp_path, VENUE, PAIR, TF)
    assert out is not None
    loaded, sha = out
    assert len(loaded) == 8
    assert sha == digest


def test_write_cache_empty_list_still_writes_empty_body(tmp_path: Path):
    csv_path, digest = write_cache(tmp_path, VENUE, PAIR, TF, [])
    assert csv_path.exists()
    assert csv_path.read_bytes() == b"ts_ms,open,high,low,close,volume\n"
    out = read_cache(tmp_path, VENUE, PAIR, TF)
    assert out is not None
    loaded, sha = out
    assert loaded == []
    assert sha == digest


def test_write_cache_missing_home_reads_none(tmp_path: Path):
    assert read_cache(tmp_path / "nope", VENUE, PAIR, TF) is None


def test_missing_dataset_refuses_invalid_dataset(home: Path, tmp_path: Path):
    pack = _write_pack(tmp_path / "pack.json")
    svc = ResearchService(home=home, fetch=None)
    result = svc.run(
        ResearchRequest(
            pack_path=pack,
            dataset_csv=tmp_path / "absent.csv",
            venue=VENUE,
        )
    )
    assert result.ok is False
    assert result.refusal["code"] == "invalid_dataset"


def test_gapped_import_refuses_gapped_data(home: Path, tmp_path: Path, capsys):
    """A gapped import refuses research with the typed gapped_data refusal."""
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["time", "open", "high", "low", "close", "volume", "count"])
    for i, close in enumerate(CLOSES_FIRST):
        if i == 4:
            continue
        px = Decimal(close)
        w.writerow([T0_S + i * BAR_S, close, str(px + Decimal("0.5")), str(px - Decimal("0.5")), close, "100", "5"])
    zip_path = tmp_path / "gapped.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("SUIUSD_60.csv", buf.getvalue().encode("utf-8"))

    rc = cli.main(
        [
            "krellbot",
            "data",
            "import",
            "kraken-ohlcvt",
            str(zip_path),
            "--pair",
            PAIR,
            "--timeframe",
            TF,
        ]
    )
    assert rc == 0, capsys.readouterr().err

    pack = _write_pack(tmp_path / "pack.json")
    svc = ResearchService(home=home, fetch=None)
    result = svc.run(
        ResearchRequest(
            pack_path=pack,
            dataset_csv=cache_path(home, VENUE, PAIR, TF),
            venue=VENUE,
        )
    )
    assert result.ok is False
    assert result.refusal["code"] == "gapped_data"


def test_conflicting_immutable_csv_refuses_and_preserves(home: Path, tmp_path: Path, capsys):
    """A pre-existing immutable CSV with different bytes visibly refuses.

    The existing version and the current stable pair are left untouched.
    """
    z1 = _write_zip(tmp_path / "first.zip", CLOSES_FIRST)
    stable, digest1 = _import_zip(home, z1, capsys)
    v_csv = _version_csv(home, VENUE, PAIR, TF, digest1)
    v_man = _version_manifest(home, VENUE, PAIR, TF, digest1)
    assert v_csv.exists(), f"version CSV missing at {v_csv}"
    stable_before = stable.read_bytes()
    man_before = manifest_path(home, VENUE, PAIR, TF).read_bytes()
    v_man_bytes = v_man.read_bytes()

    # Corrupt the stored CSV so a re-import of the SAME bytes conflicts.
    v_csv.write_bytes(b"tampered\n")

    z_same = _write_zip(tmp_path / "same.zip", CLOSES_FIRST)
    with pytest.raises((ValueError, OSError)):
        _import_zip(home, z_same, capsys)

    assert v_csv.read_bytes() == b"tampered\n"
    assert v_man.read_bytes() == v_man_bytes
    assert stable.read_bytes() == stable_before
    assert manifest_path(home, VENUE, PAIR, TF).read_bytes() == man_before


def test_conflicting_immutable_manifest_refuses_and_preserves(home: Path, tmp_path: Path, capsys):
    z1 = _write_zip(tmp_path / "first.zip", CLOSES_FIRST)
    stable, digest1 = _import_zip(home, z1, capsys)
    v_csv = _version_csv(home, VENUE, PAIR, TF, digest1)
    v_man = _version_manifest(home, VENUE, PAIR, TF, digest1)
    assert v_csv.exists(), f"version CSV missing at {v_csv}"
    stable_before = stable.read_bytes()
    man_before = manifest_path(home, VENUE, PAIR, TF).read_bytes()
    v_csv_bytes = v_csv.read_bytes()

    v_man.write_bytes(b'{"sha256": "wrong"}')

    z_same = _write_zip(tmp_path / "same.zip", CLOSES_FIRST)
    with pytest.raises((ValueError, OSError)):
        _import_zip(home, z_same, capsys)

    assert v_man.read_bytes() == b'{"sha256": "wrong"}'
    assert v_csv.read_bytes() == v_csv_bytes
    assert stable.read_bytes() == stable_before
    assert manifest_path(home, VENUE, PAIR, TF).read_bytes() == man_before


def test_new_valid_write_after_conflict_is_a_control(tmp_path: Path):
    """A normal valid write on a clean home still works (control case)."""
    candles = _candles(CLOSES_SECOND)
    csv_path, digest = write_cache(tmp_path, VENUE, PAIR, TF, candles)
    assert csv_path.exists()
    assert sha256_bytes(csv_path.read_bytes()) == digest
    assert _version_csv(tmp_path, VENUE, PAIR, TF, digest).exists()
