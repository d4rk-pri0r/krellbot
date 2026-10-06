"""BUILD-B06-CUT-RESUME-01 (t_261a35ba): an interrupted OHLCVT import resumes.

`data import kraken-ohlcvt` used to parse the whole archive into memory and
only then publish the cache, so a hard process exit mid-parse left no durable
progress: a new process at the same `KRELLBOT_HOME` converted every row again.
This suite pins a bounded, local, same-source restart: the enabled CLI keeps a
durable checkpoint under `<home>/import-progress/kraken-ohlcvt/` keyed by the
resolved archive path, commits accepted candles in 128-candle chunks plus
matching-member boundaries, refuses any pending checkpoint whose source bytes
/ pair / timeframe / member descriptors / schema / bounds no longer match, and
removes the checkpoint only after the unchanged `write_cache` publication
succeeded.

Primary witness (section A) is RED on old production through the real CLI in
fresh child processes: a child observes `parse_timestamp`, dies with
`os._exit(91)` right after the 129th conversion, and a second process at the
SAME home must reuse the committed 128 candles instead of re-converting all
260 rows. Old production has no checkpoint database at all, so the assertion
fails on a missing file, not on a harness or import error.

Scope guard: this is a local archive-import restart leaf only. It is not
whole-B06/NS16 acceptance, adds no download/provider/alias policy, no gap
filling, no dedup change, and claims neither compressed random access,
constant-memory sorting, whole-archive hashing time bounds, nor any
hostile-tamperproof filesystem guarantee. Live execution stays disabled.
"""

from __future__ import annotations

import csv as _csv
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import textwrap
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
CHUNK = 128
TOTAL_ROWS = 260

HEADER = ["time", "open", "high", "low", "close", "volume", "count"]

# One probe interpreter, driven by environment variables so the same probe
# source works for every cut point without re-formatting Python source text.
# Modes:
#   cut-with:N - count conversions, os._exit(91) on the Nth (before returning)
#   plain      - count conversions, run to completion, print converted=<n>
#   guard:PATH - like plain, but os._exit(3) if a timestamp listed in the file
#                at PATH is ever converted (committed rows never reconverted)
PROBE_SOURCE = '''
import os, sys

sys.path.insert(0, os.environ["KB_PROBE_SRC"])
import krellbot.data.kraken_public as kp

mode = os.environ["KB_PROBE_MODE"]
guard = None
if mode.startswith("guard:"):
    import json

    with open(mode.split(":", 1)[1], encoding="utf-8") as fh:
        guard = set(json.load(fh))

calls = 0
real = kp.parse_timestamp


def probe(value):
    global calls
    calls += 1
    if mode.startswith("cut-with:") and calls == int(mode.split(":", 1)[1]):
        sys.stdout.write("converted=%d\\n" % calls)
        sys.stdout.flush()
        os._exit(91)
    if guard is not None and str(value) in guard:
        sys.stdout.write("RECONVERTED=%s\\n" % value)
        sys.stdout.flush()
        os._exit(3)
    return real(value)


kp.parse_timestamp = probe

from krellbot import cli

rc = cli.main(
    [
        "krellbot",
        "data",
        "import",
        "kraken-ohlcvt",
        os.environ["KB_PROBE_ZIP"],
        "--pair",
        os.environ["KB_PROBE_PAIR"],
        "--timeframe",
        os.environ["KB_PROBE_TF"],
    ]
)
sys.stdout.write("converted=%d\\nrc=%d\\n" % (calls, rc))
sys.stdout.flush()
os._exit(rc)
'''


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    monkeypatch.setenv("KRELLBOT_HOME", str(kb))
    monkeypatch.setenv("HOME", str(kb))
    monkeypatch.setenv("USERPROFILE", str(kb))
    monkeypatch.setattr("pathlib.Path.home", lambda: kb)
    return kb


def _bar(ts_s: int, close: str) -> list[str]:
    px = Decimal(close)
    return [str(ts_s), close, str(px + Decimal("0.5")), str(px - Decimal("0.5")), close, "100", "5"]


def _candle_body(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(HEADER)
    for row in rows:
        w.writerow(row)
    return buf.getvalue().encode("utf-8")


def _bars(count: int, close_for=None) -> list[list[str]]:
    close_for = close_for or (lambda i: str(1 + (i % 9)))
    return [_bar(T0_S + i * BAR_S, close_for(i)) for i in range(count)]


def _write_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in members.items():
            zf.writestr(name, body)
    return path


def _import(home: Path, zip_path: Path, pair: str = PAIR, tf: str = TF) -> int:
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


def _progress_dir(home: Path) -> Path:
    return Path(home) / "import-progress" / "kraken-ohlcvt"


def _slot_db(home: Path, zip_path: Path) -> Path:
    resolved = Path(zip_path).resolve()
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
    return _progress_dir(home) / f"{digest}.sqlite3"


def _slot_lock(home: Path, zip_path: Path) -> Path:
    db = _slot_db(home, zip_path)
    return db.with_name(db.name + ".lock")


def _closes(home: Path, pair: str = PAIR, tf: str = TF) -> list[Decimal]:
    out = read_cache(home, VENUE, pair, tf)
    assert out is not None, f"no cache for {pair}/{tf}"
    return [c.close for c in out[0]]


def _snapshot(root: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = p.read_bytes()
    return out


def _tree_snapshot(home: Path) -> dict[str, dict[str, bytes]]:
    return {
        "progress": _snapshot(_progress_dir(home)),
        "cache": _snapshot(Path(home) / "cache"),
        "datasets": _snapshot(Path(home) / "datasets"),
    }


def _run_probe(tmp_path: Path, home: Path, zip_path: Path, *, mode: str, pair: str = PAIR, tf: str = TF):
    probe = tmp_path / "probe_child.py"
    probe.write_text(PROBE_SOURCE, encoding="utf-8")
    env = dict(os.environ)
    env.update(
        {
            "KRELLBOT_HOME": str(home),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "KRELLBOT_LIVE": "0",
            "KB_PROBE_SRC": str(Path(cli.__file__).resolve().parents[1]),
            "KB_PROBE_MODE": mode,
            "KB_PROBE_ZIP": str(zip_path),
            "KB_PROBE_PAIR": pair,
            "KB_PROBE_TF": tf,
        }
    )
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(probe)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(tmp_path),
        timeout=300,
    )


def _kv(proc: subprocess.CompletedProcess) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            out.setdefault(key.strip(), value.strip())
    return out


def _pending_state(tmp_path: Path, home: Path, zip_path: Path, cut: int) -> Path:
    """Leave a pending checkpoint by cutting the import at conversion `cut`."""
    proc = _run_probe(tmp_path, home, zip_path, mode=f"cut-with:{cut}")
    assert proc.returncode == 91, f"cut failed: rc={proc.returncode} stderr={proc.stderr!r}"
    db = _slot_db(home, zip_path)
    assert db.is_file(), f"no checkpoint at {db}"
    return db


def _db_meta(db: Path, key: str) -> str:
    import sqlite3

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()[0]
    finally:
        con.close()


def _db_candles(db: Path) -> int:
    import sqlite3

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# A. Primary witness: hard cut mid-parse, fresh process must resume.
# ---------------------------------------------------------------------------


def test_hard_cut_mid_parse_resumes_in_a_fresh_process(home: Path, tmp_path: Path, capsys):
    """RED on old production: no durable checkpoint exists, so the retry reparses.

    A 260-row nested SUIUSD_60.csv (plus an unmatched SUIUSDT_60.csv member) is
    imported through the real CLI. The child counts `parse_timestamp`
    conversions and dies with `os._exit(91)` right after the 129th - one
    128-candle chunk boundary plus one uncommitted candle. On the candidate the
    committed chunk is durable; on old production nothing is, and the primary
    assertion below fails on the missing checkpoint file.

    The fresh-process retry must then convert at most the remaining 132 rows
    (the 129th candle may replay) and the final cache must hold exactly the 260
    expected sorted candles with no resume-introduced duplicates, the manifest
    digest matching the published bytes, and a cleaned-up checkpoint.
    """
    zip_path = _write_zip(
        tmp_path / "cut.zip",
        {
            "OHLCVT/SUIUSD_60.csv": _candle_body(_bars(TOTAL_ROWS)),
            "OHLCVT/SUIUSDT_60.csv": _candle_body([_bar(T0_S + 9 * BAR_S, "99")]),
        },
    )

    # Seed a prior, different SUIUSD dataset: during the cut it must not change.
    prior_zip = _write_zip(tmp_path / "prior.zip", {"SUIUSD_60.csv": _candle_body(_bars(8, lambda i: "7"))})
    assert _import(home, prior_zip) == 0
    capsys.readouterr()
    prior_stable = cache_path(home, VENUE, PAIR, TF).read_bytes()
    prior_manifest = manifest_path(home, VENUE, PAIR, TF).read_bytes()
    prior_version = dataset_version_path(home, VENUE, PAIR, TF, sha256_bytes(prior_stable)).read_bytes()

    first = _run_probe(tmp_path, home, zip_path, mode="cut-with:129")
    assert first.returncode == 91, f"child did not die at the cut: rc={first.returncode} err={first.stderr!r}"
    assert _kv(first)["converted"] == "129"

    # The cut published nothing and left the prior canonical bytes untouched.
    assert cache_path(home, VENUE, PAIR, TF).read_bytes() == prior_stable
    assert manifest_path(home, VENUE, PAIR, TF).read_bytes() == prior_manifest
    assert dataset_version_path(home, VENUE, PAIR, TF, sha256_bytes(prior_stable)).read_bytes() == prior_version

    # PRIMARY ASSERTION - RED on old production: a durable checkpoint exists
    # holding exactly the committed 128 candles, still in the parsing phase.
    db = _slot_db(home, zip_path)
    assert db.is_file(), f"no durable checkpoint at {db}"
    assert _db_candles(db) == CHUNK, f"expected exactly the committed {CHUNK} candles"
    assert json.loads(_db_meta(db, "cursor_json"))["phase"] == "parsing"

    # Fresh process at the SAME home resumes: at most 132 conversions remain.
    retry = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert retry.returncode == 0, f"retry failed: {retry.stderr!r}"
    remaining = int(_kv(retry)["converted"])
    assert remaining <= TOTAL_ROWS - CHUNK, f"retry reconverted {remaining} rows; at most {TOTAL_ROWS - CHUNK} may remain"

    expected = [Decimal(str(1 + (i % 9))) for i in range(TOTAL_ROWS)]
    assert _closes(home) == expected, "resume changed the candle series"
    candles = read_cache(home, VENUE, PAIR, TF)[0]
    stamps = [c.ts_ms for c in candles]
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == TOTAL_ROWS, "resume-introduced duplicate timestamps"
    manifest = json.loads(manifest_path(home, VENUE, PAIR, TF).read_text())
    assert manifest["rows"] == TOTAL_ROWS
    assert manifest["sha256"] == sha256_bytes(cache_path(home, VENUE, PAIR, TF).read_bytes())
    # Completed operation: the checkpoint is cleaned up after publication.
    assert not db.exists()
    # The prior dataset's retained version bytes are still present untouched.
    assert dataset_version_path(home, VENUE, PAIR, TF, sha256_bytes(prior_stable)).read_bytes() == prior_version


def test_committed_chunk_is_never_reconverted(home: Path, tmp_path: Path):
    """None of the first 128 committed timestamps is parsed again by the retry.

    The retry probe refuses to convert any timestamp from the committed prefix
    and exits 3 if it is asked for one. A retry that reconverted committed rows
    dies with rc 3 instead of finishing the import.
    """
    rows = _bars(TOTAL_ROWS)
    zip_path = _write_zip(tmp_path / "cut.zip", {"SUIUSD_60.csv": _candle_body(rows)})

    cut = _run_probe(tmp_path, home, zip_path, mode="cut-with:129")
    assert cut.returncode == 91
    assert _db_candles(_slot_db(home, zip_path)) == CHUNK

    guard_file = tmp_path / "committed.json"
    guard_file.write_text(json.dumps(sorted(rows[i][0] for i in range(CHUNK))), encoding="utf-8")
    retry = _run_probe(tmp_path, home, zip_path, mode=f"guard:{guard_file}")
    assert retry.returncode == 0, f"committed chunk was reconverted: {retry.stdout!r} {retry.stderr!r}"
    assert "RECONVERTED" not in retry.stdout
    assert _closes(home) == [Decimal(str(1 + (i % 9))) for i in range(TOTAL_ROWS)]


def test_stateless_import_function_stays_side_effect_free(home: Path, tmp_path: Path):
    """`import_kraken_ohlcvt_zip` without a collaborator stays side-effect free.

    The public stateless parser keeps returning the same sorted list and writes
    nothing under the home (no checkpoint, no cache) when called directly.
    """
    zip_path = _write_zip(tmp_path / "plain.zip", {"SUIUSD_60.csv": _candle_body(_bars(3))})
    candles = import_kraken_ohlcvt_zip(zip_path, pair=PAIR, tf=TF)
    assert [c.close for c in candles] == [Decimal(1), Decimal(2), Decimal(3)]
    assert not _progress_dir(home).exists()
    assert read_cache(home, VENUE, PAIR, TF) is None


# ---------------------------------------------------------------------------
# B. Controls: uninterrupted equality, boundary cut, predecessor semantics.
# ---------------------------------------------------------------------------


def test_resumed_home_matches_uninterrupted_control(home: Path, tmp_path: Path):
    """A resumed import and an uninterrupted separate-home control agree byte for byte.

    Two exact matching members (the second with reverse timestamps), a header,
    skipped records and ignored malformed near-collision members. The cut lands
    after the first member's boundary commit; the retry finishes the import.
    Final cache, manifest and retained version bytes are identical to the
    control home.
    """
    rows_a = _bars(200, lambda i: str(1 + (i % 5)))
    rows_b = [_bar(T0_S + (300 - i) * BAR_S, str(50 + (i % 3))) for i in range(61)]
    members = {
        "a/SUIUSD_60.csv": _candle_body(rows_a),
        "b/SUIUSD_60.csv": _candle_body(rows_b),
        "noise/SUIUSDT_60.csv": "time,open,high,low,close,volume,count\nnot,parseable,at,all\n",
        "noise/SUIUSD_160.csv": _candle_body([_bar(T0_S, "99")]),
    }
    zip_cut = _write_zip(tmp_path / "cut.zip", members)
    zip_clean = _write_zip(tmp_path / "clean.zip", members)

    control_home = tmp_path / "control-kb"
    control = _run_probe(tmp_path, control_home, zip_clean, mode="plain")
    assert control.returncode == 0, control.stderr
    control_closes = _closes(control_home)
    assert len(control_closes) == 200 + 61

    # Cut on the FIRST conversion of the second member: member a (200 candles)
    # is fully committed at its matching-member boundary.
    cut = _run_probe(tmp_path, home, zip_cut, mode="cut-with:201")
    assert cut.returncode == 91, cut.stderr
    db = _slot_db(home, zip_cut)
    assert _db_candles(db) == 200, "member boundary must commit the completed member"
    assert json.loads(_db_meta(db, "cursor_json"))["phase"] == "parsing"

    retry = _run_probe(tmp_path, home, zip_cut, mode="plain")
    assert retry.returncode == 0, retry.stderr
    assert int(_kv(retry)["converted"]) <= 61, "resume must skip the committed first member"

    assert _closes(home) == control_closes
    assert cache_path(home, VENUE, PAIR, TF).read_bytes() == cache_path(control_home, VENUE, PAIR, TF).read_bytes()
    assert manifest_path(home, VENUE, PAIR, TF).read_bytes() == manifest_path(control_home, VENUE, PAIR, TF).read_bytes()
    digest = json.loads(manifest_path(control_home, VENUE, PAIR, TF).read_text())["sha256"]
    assert (
        dataset_version_path(home, VENUE, PAIR, TF, digest).read_bytes()
        == dataset_version_path(control_home, VENUE, PAIR, TF, digest).read_bytes()
    )

    expected_ts = sorted(
        [(T0_S + i * BAR_S) * 1000 for i in range(200)] + [(T0_S + (300 - i) * BAR_S) * 1000 for i in range(61)]
    )
    assert [c.ts_ms for c in read_cache(home, VENUE, PAIR, TF)[0]] == expected_ts


def test_cut_before_first_chunk_keeps_zero_committed_candles(home: Path, tmp_path: Path):
    """An early cut commits nothing and never partially publishes."""
    zip_path = _write_zip(tmp_path / "early.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})

    cut = _run_probe(tmp_path, home, zip_path, mode="cut-with:40")
    assert cut.returncode == 91
    db = _slot_db(home, zip_path)
    assert db.is_file()
    assert _db_candles(db) == 0
    assert read_cache(home, VENUE, PAIR, TF) is None

    retry = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert retry.returncode == 0, retry.stderr
    assert int(_kv(retry)["converted"]) == 200
    assert len(_closes(home)) == 200


def test_predecessor_member_semantics_survive_the_resume_path(home: Path, tmp_path: Path):
    """Nested/case/.zip-named CSV members, headers and skipped rows parse the same.

    The archive mixes a nested mixed-case `.CSV` member, a legacy `.zip`-named
    CSV member, header + blank + wrong-width + non-numeric rows and ignored
    near-collision members. The cut lands on the first candle of the second
    member, so the first member's boundary commit is durable; the retry must
    reproduce exactly the stateless parser's candles for the same archive.
    """
    legacy_body = (
        "time,open,high,low,close,volume,count\n"
        "\n"
        "1700000000,1,1.5,0.5,1,10,1\n"
        "garbage,not,numeric,header,skipped,x,y\n"
        "1700003600,2,2.5,1.5,2,10,1\n"
        "1700007200,3,3.5,2.5,3,10,1,extra\n"
    )
    nested_body = "1700072000,7,7.5,6.5,7,10,1\n1700036000,4,4.5,3.5,4,10,1\n"
    members = {
        "deep/nest/sUiUsD_60.CSV": nested_body,
        "SUIUSD_60.zip": legacy_body,
        "SUIUSDT_60.csv": "time,open,high,low,close,volume,count\n1700000000,99,99,99,99,1,1\n",
        "folder60/SUIUSD_240.csv": "time,open,high,low,close,volume,count\n1700000000,88,88,88,88,1,1\n",
    }
    zip_path = _write_zip(tmp_path / "mixed.zip", members)

    expected = import_kraken_ohlcvt_zip(zip_path, pair=PAIR, tf=TF)
    assert [str(c.close) for c in expected] == ["1", "2", "4", "7"]
    assert [c.ts_ms for c in expected] == [
        1_700_000_000_000,
        1_700_003_600_000,
        1_700_036_000_000,
        1_700_072_000_000,
    ]

    # Member 0 (nested, 2 candles) commits at its boundary; the cut lands on
    # member 1's first conversion.
    cut = _run_probe(tmp_path, home, zip_path, mode="cut-with:3")
    assert cut.returncode == 91
    db = _slot_db(home, zip_path)
    assert _db_candles(db) == 2

    retry = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert retry.returncode == 0, retry.stderr
    assert int(_kv(retry)["converted"]) == 2, "resume must skip the committed first member"

    got = read_cache(home, VENUE, PAIR, TF)[0]
    assert [(c.ts_ms, str(c.open), str(c.high), str(c.low), str(c.close), str(c.volume)) for c in got] == [
        (c.ts_ms, str(c.open), str(c.high), str(c.low), str(c.close), str(c.volume)) for c in expected
    ]


# ---------------------------------------------------------------------------
# C. Refusals: incompatible pending progress is visible and byte-preserving.
# ---------------------------------------------------------------------------


def test_replaced_archive_bytes_at_same_path_refuse(home: Path, tmp_path: Path):
    """Same resolved path with different archive bytes is a substantive refusal."""
    zip_path = _write_zip(tmp_path / "same-path.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})
    db = _pending_state(tmp_path, home, zip_path, cut=100)

    # Replace the archive IN PLACE: same resolved path, different bytes.
    _write_zip(zip_path, {"SUIUSD_60.csv": _candle_body(_bars(200, lambda i: "3"))})

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert proc.returncode != 0, "changed archive bytes at the same slot must refuse"
    assert "refus" in (proc.stdout + proc.stderr).lower()
    after = _tree_snapshot(home)
    assert before["cache"] == after["cache"]
    assert before["datasets"] == after["datasets"]
    lock_rel = str(_slot_lock(home, zip_path).relative_to(_progress_dir(home)))
    assert {k: v for k, v in before["progress"].items() if k != lock_rel} == {
        k: v for k, v in after["progress"].items() if k != lock_rel
    }
    assert before["progress"][lock_rel] == after["progress"][lock_rel]
    assert db.is_file(), "the incompatible pending checkpoint is never reset or replaced"


def test_changed_pair_selection_refuses_in_fresh_process(home: Path, tmp_path: Path):
    """A pending SUIUSD checkpoint refuses a SUIUSDT request at the same source."""
    zip_path = _write_zip(
        tmp_path / "pair.zip",
        {
            "SUIUSD_60.csv": _candle_body(_bars(200)),
            "SUIUSDT_60.csv": _candle_body([_bar(T0_S, "99")]),
        },
    )
    _pending_state(tmp_path, home, zip_path, cut=100)

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain", pair="SUIUSDT")
    assert proc.returncode != 0, "changed pair selection must fail"
    assert "refus" in (proc.stdout + proc.stderr).lower()
    after = _tree_snapshot(home)
    assert before["progress"] == after["progress"]
    assert before["cache"] == after["cache"]
    assert before["datasets"] == after["datasets"]

    # The compatible request still succeeds afterwards.
    retry = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert retry.returncode == 0, retry.stderr
    assert len(_closes(home)) == 200


def test_changed_pair_case_selection_refuses(home: Path, tmp_path: Path):
    """The exact requested pair string is the identity; `suiusd` != `SUIUSD`."""
    zip_path = _write_zip(tmp_path / "case.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})
    _pending_state(tmp_path, home, zip_path, cut=100)

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain", pair="suiusd")
    assert proc.returncode != 0, "case-changed selection must fail"
    assert "refus" in (proc.stdout + proc.stderr).lower()
    after = _tree_snapshot(home)
    assert before["progress"] == after["progress"]
    assert before["cache"] == after["cache"]


def test_changed_timeframe_refuses(home: Path, tmp_path: Path):
    """A pending 1h checkpoint refuses a 4h request at the same source."""
    zip_path = _write_zip(
        tmp_path / "tf.zip",
        {
            "SUIUSD_60.csv": _candle_body(_bars(200)),
            "SUIUSD_240.csv": _candle_body([_bar(T0_S, "88")]),
        },
    )
    _pending_state(tmp_path, home, zip_path, cut=100)

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain", tf="4h")
    assert proc.returncode != 0, "changed timeframe must fail"
    assert "refus" in (proc.stdout + proc.stderr).lower()
    after = _tree_snapshot(home)
    assert before["progress"] == after["progress"]
    assert before["cache"] == after["cache"]
    assert before["datasets"] == after["datasets"]


def test_changed_member_descriptors_refuse(home: Path, tmp_path: Path):
    """Stored member descriptors that no longer match the archive refuse."""
    zip_path = _write_zip(tmp_path / "members.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})
    db = _pending_state(tmp_path, home, zip_path, cut=100)

    import sqlite3

    con = sqlite3.connect(db)
    con.execute("UPDATE meta SET value = '[]' WHERE key = 'members_json'")
    con.commit()
    con.close()

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert proc.returncode != 0, "changed member descriptors must fail"
    assert "refus" in (proc.stdout + proc.stderr).lower()
    after = _tree_snapshot(home)
    assert before["progress"] == after["progress"]
    assert before["cache"] == after["cache"]
    assert before["datasets"] == after["datasets"]


def test_changed_schema_version_refuses(home: Path, tmp_path: Path):
    """A checkpoint written by a different schema version refuses visibly."""
    zip_path = _write_zip(tmp_path / "schema.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})
    db = _pending_state(tmp_path, home, zip_path, cut=100)

    import sqlite3

    con = sqlite3.connect(db)
    con.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
    con.commit()
    con.close()

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert proc.returncode != 0, "foreign schema version must fail"
    assert "refus" in (proc.stdout + proc.stderr).lower()
    after = _tree_snapshot(home)
    assert before["progress"] == after["progress"]


def test_corrupt_checkpoint_refuses_and_is_preserved(home: Path, tmp_path: Path):
    """An unreadable progress database refuses instead of silently restarting."""
    zip_path = _write_zip(tmp_path / "corrupt.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})
    db = _pending_state(tmp_path, home, zip_path, cut=100)

    db.write_bytes(b"this is not a sqlite database at all\n")

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert proc.returncode != 0, "a corrupt checkpoint must refuse"
    assert "refus" in (proc.stdout + proc.stderr).lower()
    assert db.read_bytes() == b"this is not a sqlite database at all\n"
    after = _tree_snapshot(home)
    assert before["cache"] == after["cache"]
    assert before["datasets"] == after["datasets"]


def test_inconsistent_cursor_count_refuses(home: Path, tmp_path: Path):
    """A cursor whose candle count disagrees with the stored candles refuses."""
    zip_path = _write_zip(tmp_path / "cursor.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})
    db = _pending_state(tmp_path, home, zip_path, cut=130)

    import sqlite3

    con = sqlite3.connect(db)
    cursor = json.loads(con.execute("SELECT value FROM meta WHERE key='cursor_json'").fetchone()[0])
    cursor["candles_count"] = cursor["candles_count"] + 5
    con.execute("UPDATE meta SET value = ? WHERE key = 'cursor_json'", (json.dumps(cursor),))
    con.commit()
    con.close()

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert proc.returncode != 0, "inconsistent cursor must fail"
    after = _tree_snapshot(home)
    assert before["progress"] == after["progress"]


def test_valid_keys_corrupt_cursor_cannot_silently_drop_candles(home: Path, tmp_path: Path):
    """A cursor with every valid key but a forged position must refuse, not skip.

    Independent consistency finding: a 128-candle checkpoint holding
    `records_seen` 129 / `next_row_index` 139 accepted a cursor with
    `next_row_index` bumped to 149. The resumed import then skipped ten source
    candles, published 250 of 260 rows and exited 0. The cursor must be
    validated against the source positions that were actually recorded, so the
    import refuses without touching any byte and never silently truncates.
    """
    zip_path = _write_zip(
        tmp_path / "dropped.zip",
        {"OHLCVT/SUIUSD_60.csv": _candle_body(_bars(TOTAL_ROWS))},
    )
    db = _pending_state(tmp_path, home, zip_path, cut=129)

    import sqlite3

    con = sqlite3.connect(db)
    cursor = json.loads(con.execute("SELECT value FROM meta WHERE key='cursor_json'").fetchone()[0])
    assert cursor["candles_count"] == CHUNK and cursor["records_seen"] == 129
    cursor["next_row_index"] += 10
    con.execute("UPDATE meta SET value = ? WHERE key = 'cursor_json'", (json.dumps(cursor),))
    con.commit()
    con.close()

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert proc.returncode != 0, "inconsistent cursor was accepted and silently published truncated data"
    after = _tree_snapshot(home)
    assert before == after, "the refusal must preserve every existing byte"

    # The pending checkpoint still refuses deterministically; nothing restarted.
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert proc.returncode != 0
    assert _tree_snapshot(home) == before


def test_incompatible_wal_progress_refusal_never_mutates_existing_bytes(home: Path, tmp_path: Path):
    """Refusing an unsupported journal mode must not first rewrite the checkpoint.

    Independent consistency finding: a pending checkpoint switched to WAL with
    a foreign schema version was refused with rc 1, but only after a writable
    open had normalized the journal mode back to DELETE - mutating the DB (and
    its journal) before the refusal. Inspection must be read-only, so the DB
    and journal bytes are exactly as they were left.
    """
    zip_path = _write_zip(tmp_path / "wal.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})
    db = _pending_state(tmp_path, home, zip_path, cut=100)

    import sqlite3

    con = sqlite3.connect(db)
    try:
        assert con.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        con.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
    finally:
        con.close()

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert proc.returncode != 0
    assert "refus" in (proc.stdout + proc.stderr).lower()
    after = _tree_snapshot(home)
    assert after == before, "checkpoint opened writable and journal mode was changed before refusing"


def test_candles_count_above_committed_positions_refuses(home: Path, tmp_path: Path):
    """A valid-key cursor claiming a source position no candle was stored at refuses.

    Records must be accounted by source position: an existing checkpoint whose
    cursor points past its recorded candle positions cannot be trusted, and a
    resume must not quietly convert a different record window than the one the
    checkpoint actually committed.
    """
    zip_path = _write_zip(tmp_path / "positions.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})
    db = _pending_state(tmp_path, home, zip_path, cut=129)

    import sqlite3

    con = sqlite3.connect(db)
    cursor = json.loads(con.execute("SELECT value FROM meta WHERE key='cursor_json'").fetchone()[0])
    cursor["candles_count"] = CHUNK + 1
    cursor["records_seen"] = 130
    con.execute("UPDATE meta SET value = ? WHERE key = 'cursor_json'", (json.dumps(cursor),))
    con.commit()
    con.close()

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert proc.returncode != 0, "count claims a source position no stored candle was recorded at"
    assert _tree_snapshot(home) == before


def _run_member_rows(start: int, count: int, close_for) -> list[list[str]]:
    """`count` bars with globally increasing stamps, continuing from `start`."""
    return [_bar(T0_S + (start + i) * BAR_S, close_for(start + i)) for i in range(count)]


def _second_member_state(tmp_path: Path, home: Path) -> tuple[Path, Path]:
    """Two exact matching members (110 + 150 candles), pending inside member 2.

    Returns `(zip_path, db)` with the checkpoint holding 238 candles: the
    completed 110-candle first member plus one committed 128-candle chunk of
    the second. Timestamps increase across the members, so the final series is
    exactly closes 1..260. The prior seeded dataset stays published while the
    parse runs.
    """
    members = {
        "a/SUIUSD_60.csv": _candle_body(_run_member_rows(0, 110, lambda i: str(i + 1))),
        "b/SUIUSD_60.csv": _candle_body(_run_member_rows(110, 150, lambda i: str(i + 1))),
    }
    zip_path = _write_zip(tmp_path / "members.zip", members)
    seed = _write_zip(tmp_path / "seed.zip", {"SUIUSD_60.csv": _candle_body(_bars(1, lambda i: "77"))})
    assert _import(home, seed) == 0
    db = _pending_state(tmp_path, home, zip_path, cut=240)
    assert json.loads(_db_meta(db, "cursor_json")) == {
        "next_member_index": 1,
        "next_row_index": 129,
        "records_seen": 240,
        "candles_count": 238,
        "phase": "parsing",
    }
    assert _db_candles(db) == 238
    return zip_path, db


@pytest.mark.parametrize("corrupt", [False, True], ids=["valid-second-member-control", "second-member-cursor-plus-ten"])
def test_second_member_cursor_accounting(home: Path, tmp_path: Path, corrupt: bool):
    """A forged cursor inside a LATER member must refuse, never skip source rows.

    Independent consistency finding (HIGH): with the cursor inside the second
    selected member, a valid-key cursor whose `next_row_index` was bumped
    129 -> 139 was accepted. The resume then skipped ten source candles,
    published 250 of 260 rows, exited 0 and deleted the checkpoint. The
    prefix/position accounting must cover every selected member occurrence,
    not only member 0.
    """
    zip_path, db = _second_member_state(tmp_path, home)

    import sqlite3

    con = sqlite3.connect(db)
    cursor = json.loads(con.execute("SELECT value FROM meta WHERE key='cursor_json'").fetchone()[0])
    if corrupt:
        cursor["next_row_index"] += 10
        con.execute("UPDATE meta SET value = ? WHERE key = 'cursor_json'", (json.dumps(cursor),))
        con.commit()
    con.close()

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    if corrupt:
        assert proc.returncode != 0, "second-member corrupt cursor silently drops source candles"
        assert _tree_snapshot(home) == before, "refusal must preserve every existing byte"
        # The pending checkpoint is still there and still refuses deterministically.
        again = _run_probe(tmp_path, home, zip_path, mode="plain")
        assert again.returncode != 0
        assert _tree_snapshot(home) == before
    else:
        assert proc.returncode == 0, proc.stderr
        assert int(_kv(proc)["converted"]) == 22, "resume reconverted committed candles"
        assert _closes(home) == [Decimal(str(i)) for i in range(1, 261)]
        assert not db.exists(), "completed import did not clean up its checkpoint"


def test_completed_member_record_accounting_refuses_unaccounted_records(home: Path, tmp_path: Path):
    """`records_seen` must equal the source records actually consumed, in every member.

    A cursor inside the second member whose `records_seen` is off by one keeps
    every structural invariant of the old checks (counts match the stored
    candles, nothing sits at or past the cursor) yet claims source work the
    selected members never accounted.
    """
    zip_path, db = _second_member_state(tmp_path, home)

    import sqlite3

    con = sqlite3.connect(db)
    cursor = json.loads(con.execute("SELECT value FROM meta WHERE key='cursor_json'").fetchone()[0])
    cursor["records_seen"] += 1
    con.execute("UPDATE meta SET value = ? WHERE key = 'cursor_json'", (json.dumps(cursor),))
    con.commit()
    con.close()

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert proc.returncode != 0, "unaccounted source records were accepted"
    assert _tree_snapshot(home) == before


def test_cursor_past_the_end_of_the_current_member_refuses(home: Path, tmp_path: Path):
    """A cursor deeper than the member's actual records is outside the source.

    `next_row_index` is pushed to 999 (past the second member's 151 records)
    and `records_seen` is reconciled with it, so only the source-prefix check
    can catch the position.
    """
    zip_path, db = _second_member_state(tmp_path, home)

    import sqlite3

    con = sqlite3.connect(db)
    cursor = json.loads(con.execute("SELECT value FROM meta WHERE key='cursor_json'").fetchone()[0])
    cursor["next_row_index"] = 999
    cursor["records_seen"] = 111 + 999
    con.execute("UPDATE meta SET value = ? WHERE key = 'cursor_json'", (json.dumps(cursor),))
    con.commit()
    con.close()

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert proc.returncode != 0, "cursor outside the selected source was accepted"
    assert _tree_snapshot(home) == before


def test_stored_candle_at_a_skipped_source_position_refuses(home: Path, tmp_path: Path):
    """A candle stored at a row the source skips (the header) is an invalid position.

    The forged row keeps every count consistent (`candles_count` is bumped to
    match) and sits before the cursor, so only the accepted-occurrence
    position comparison rejects it.
    """
    zip_path, db = _second_member_state(tmp_path, home)

    import sqlite3

    con = sqlite3.connect(db)
    cursor = json.loads(con.execute("SELECT value FROM meta WHERE key='cursor_json'").fetchone()[0])
    con.execute(
        "INSERT INTO candles (member_index, row_index, ts_ms, open, high, low, close, volume) "
        "VALUES (1, 0, 0, '0', '0', '0', '0', '0')"
    )
    cursor["candles_count"] += 1
    con.execute("UPDATE meta SET value = ? WHERE key = 'cursor_json'", (json.dumps(cursor),))
    con.commit()
    con.close()

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert proc.returncode != 0, "candle at a source position that is never accepted was trusted"
    assert _tree_snapshot(home) == before


def test_member_boundary_checkpoint_accounts_the_completed_member(home: Path, tmp_path: Path):
    """A boundary cursor (member 1 done, member 2 at row 0) is validated too.

    The cut lands on the first conversion of the second member, after the
    first member's boundary commit: cursor `{next_member_index: 1,
    next_row_index: 0, records_seen: 111, candles_count: 110}`. Forging
    `records_seen` there must refuse, while the untouched control resumes by
    converting exactly the 150 remaining rows.
    """
    members = {
        "a/SUIUSD_60.csv": _candle_body(_run_member_rows(0, 110, lambda i: str(i + 1))),
        "b/SUIUSD_60.csv": _candle_body(_run_member_rows(110, 150, lambda i: str(i + 1))),
    }
    zip_path = _write_zip(tmp_path / "boundary.zip", members)
    db = _pending_state(tmp_path, home, zip_path, cut=111)
    assert json.loads(_db_meta(db, "cursor_json")) == {
        "next_member_index": 1,
        "next_row_index": 0,
        "records_seen": 111,
        "candles_count": 110,
        "phase": "parsing",
    }

    import sqlite3

    con = sqlite3.connect(db)
    cursor = json.loads(con.execute("SELECT value FROM meta WHERE key='cursor_json'").fetchone()[0])
    cursor["records_seen"] += 1
    con.execute("UPDATE meta SET value = ? WHERE key = 'cursor_json'", (json.dumps(cursor),))
    con.commit()
    con.close()

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert proc.returncode != 0, "boundary cursor with unaccounted records was accepted"
    assert _tree_snapshot(home) == before

    # Untouched control at the same boundary state finishes from member 2 alone.
    con = sqlite3.connect(db)
    cursor["records_seen"] -= 1
    con.execute("UPDATE meta SET value = ? WHERE key = 'cursor_json'", (json.dumps(cursor),))
    con.commit()
    con.close()
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert proc.returncode == 0, proc.stderr
    assert int(_kv(proc)["converted"]) == 150, "boundary resume reconverted the completed member"
    assert _closes(home) == [Decimal(str(i)) for i in range(1, 261)]
    assert not db.exists()


def test_checkpoints_for_different_sources_are_separate(home: Path, tmp_path: Path):
    """Two different archive paths are two separate imports, not one deduplicated slot."""
    za = _write_zip(tmp_path / "a.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})
    zb = _write_zip(tmp_path / "b.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})

    _pending_state(tmp_path, home, za, cut=100)
    assert _slot_db(home, za).is_file()
    assert not _slot_db(home, zb).exists()

    assert _import(home, zb) == 0
    assert len(_closes(home)) == 200
    assert not _slot_db(home, zb).exists()
    assert _slot_db(home, za).is_file(), "the unrelated pending import is not reset or replaced"


# ---------------------------------------------------------------------------
# D. Bounds, publication cuts, lock contention, durability posture.
# ---------------------------------------------------------------------------


def _cached():
    from krellbot.data.kraken_public import import_kraken_ohlcvt_cached

    return import_kraken_ohlcvt_cached


def test_row_bound_refuses_at_exact_boundary(tmp_path: Path):
    """Crossing the declared record bound refuses; exactly at the bound succeeds.

    Every selected CSV record counts toward the bound, including the header
    row. The `exact` archive holds 12 selected records (header + 11 bars) and
    passes with `max_records=12`; the `over` archive holds 13 and refuses when
    the 13th would be consumed - no truncation, no zero-fill, no publication.
    """
    from krellbot.data.import_progress import ImportProgressError

    exact = _write_zip(tmp_path / "exact.zip", {"SUIUSD_60.csv": _candle_body(_bars(11))})
    over = _write_zip(tmp_path / "over.zip", {"SUIUSD_60.csv": _candle_body(_bars(12))})

    csv_path, digest, row_count = _cached()(exact, pair=PAIR, tf=TF, home=tmp_path / "kb-exact", max_records=12)
    assert row_count == 11
    assert sha256_bytes(Path(csv_path).read_bytes()) == digest

    over_home = tmp_path / "kb-over"
    with pytest.raises(ImportProgressError):
        _cached()(over, pair=PAIR, tf=TF, home=over_home, max_records=12)
    # No partial canonical publication and no silent truncation for the refusal.
    assert read_cache(over_home, VENUE, PAIR, TF) is None
    datasets = over_home / "datasets"
    assert not datasets.exists() or list(datasets.rglob("*.csv")) == []

    # The refused import's checkpoint stays usable: the same bounds refuse
    # again deterministically instead of silently restarting or corrupting.
    with pytest.raises(ImportProgressError):
        _cached()(over, pair=PAIR, tf=TF, home=over_home, max_records=10)


def test_byte_bound_refuses_before_database_creation(home: Path, tmp_path: Path):
    """The selected uncompressed size bound refuses before a checkpoint exists."""
    from krellbot.data.import_progress import ImportProgressError

    big = _candle_body(_bars(50))
    zip_path = _write_zip(tmp_path / "big.zip", {"SUIUSD_60.csv": big})

    with pytest.raises(ImportProgressError):
        _cached()(zip_path, pair=PAIR, tf=TF, home=home, max_uncompressed_bytes=len(big) - 1)
    assert list(_progress_dir(home).glob("*.sqlite3")) == []
    assert read_cache(home, VENUE, PAIR, TF) is None


def test_incompatible_bounds_on_resume_refuse(home: Path, tmp_path: Path):
    """A pending checkpoint refuses a resume with different declared bounds."""
    from krellbot.data.import_progress import ImportProgressError

    zip_path = _write_zip(tmp_path / "bounds.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})
    db = _pending_state(tmp_path, home, zip_path, cut=100)

    before = db.read_bytes()
    with pytest.raises(ImportProgressError):
        _cached()(zip_path, pair=PAIR, tf=TF, home=home, max_records=5)
    with pytest.raises(ImportProgressError):
        _cached()(zip_path, pair=PAIR, tf=TF, home=home, max_uncompressed_bytes=1024)
    assert db.read_bytes() == before
    # The original bounds still resume to completion.
    csv_path, digest, rows = _cached()(zip_path, pair=PAIR, tf=TF, home=home)
    assert rows == 200
    assert sha256_bytes(Path(csv_path).read_bytes()) == digest


def test_chunk_buffer_bound_is_128(home: Path, tmp_path: Path):
    """Commits are bounded at 128 newly accepted candles per transaction."""
    zip_path = _write_zip(tmp_path / "chunks.zip", {"SUIUSD_60.csv": _candle_body(_bars(300))})
    db = _pending_state(tmp_path, home, zip_path, cut=257)

    assert _db_candles(db) == 2 * CHUNK, f"expected the two full committed chunks, got {_db_candles(db)}"
    assert int(_db_meta(db, "checkpoint_every")) == CHUNK


def test_parsed_checkpoint_survives_publication_error_and_retry_reuses_it(home: Path, tmp_path: Path):
    """A cut between the parsed checkpoint and `write_cache` retries without reparse."""
    zip_path = _write_zip(tmp_path / "pubcut.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})

    import krellbot.data.kraken_public as kp

    calls = {"parse": 0, "publish": 0}
    real_parse = kp.parse_timestamp

    def counting(value):
        calls["parse"] += 1
        return real_parse(value)

    real_cache = kp.write_cache

    def failing(*args, **kwargs):
        calls["publish"] += 1
        raise OSError("publication cut injected")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(kp, "parse_timestamp", counting)
        mp.setattr(kp, "write_cache", failing)
        with pytest.raises(OSError):
            _cached()(zip_path, pair=PAIR, tf=TF, home=home)
    assert calls["parse"] == 200
    assert calls["publish"] == 1

    db = _slot_db(home, zip_path)
    assert db.is_file(), "parsed checkpoint must be retained when publication fails"
    assert json.loads(_db_meta(db, "cursor_json"))["phase"] == "parsed"
    assert _db_candles(db) == 200
    assert read_cache(home, VENUE, PAIR, TF) is None

    calls2 = {"parse": 0}

    def counting2(value):
        calls2["parse"] += 1
        return real_parse(value)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(kp, "parse_timestamp", counting2)
        csv_path, digest, rows = _cached()(zip_path, pair=PAIR, tf=TF, home=home)
    assert calls2["parse"] == 0, "retry after a publication cut must not reparse"
    assert rows == 200
    assert sha256_bytes(Path(csv_path).read_bytes()) == digest
    assert len(_closes(home)) == 200
    assert not db.exists()
    assert real_cache is kp.write_cache


def test_write_cache_conflict_still_raises_and_keeps_checkpoint(home: Path, tmp_path: Path):
    """The existing immutable-version conflict still propagates, checkpoint retained.

    A conflict needs the second import to reproduce an already-retained digest,
    so `z2` renders the exact same canonical candles as `z1` (same rows in
    reverse order - sorting makes the bytes identical). A merely different
    price series would get a new digest and publish without any conflict. The
    control home proves the fixture really targets the tampered digest.
    """
    rows = _bars(20, lambda i: "1")
    z1 = _write_zip(tmp_path / "first.zip", {"SUIUSD_60.csv": _candle_body(rows)})
    assert _import(home, z1) == 0
    stable = cache_path(home, VENUE, PAIR, TF)
    digest1 = json.loads(manifest_path(home, VENUE, PAIR, TF).read_text())["sha256"]
    v_csv = dataset_version_path(home, VENUE, PAIR, TF, digest1)
    v_csv.write_bytes(b"tampered\n")

    z2 = _write_zip(tmp_path / "second.zip", {"SUIUSD_60.csv": _candle_body(list(reversed(rows)))})
    control_home = tmp_path / "digest-control-kb"
    _c, control_digest, _r = _cached()(z2, pair=PAIR, tf=TF, home=control_home)
    assert control_digest == digest1, "fixture must reproduce the existing digest, not mint a new one"

    with pytest.raises((ValueError, OSError)):
        _import(home, z2)
    assert v_csv.read_bytes() == b"tampered\n"
    assert stable.read_bytes().startswith(b"ts_ms,")
    assert _slot_db(home, z2).is_file(), "the parsed checkpoint of the refused import stays resumable"


def test_same_source_digest_conflict_keeps_parsed_checkpoint(home: Path, tmp_path: Path):
    """Re-importing a published source whose retained bytes were tampered refuses.

    The checkpoint is already `parsed`, so the retry must not reparse (zero
    conversions), the unchanged `write_cache` conflict must propagate with its
    own words, and every existing byte - including the parsed checkpoint -
    must survive the refusal untouched.
    """
    import sqlite3

    zip_path = _write_zip(tmp_path / "conflict.zip", {"SUIUSD_60.csv": _candle_body(_bars(40))})
    assert _run_probe(tmp_path, home, zip_path, mode="plain").returncode == 0
    _candles, digest = read_cache(home, VENUE, PAIR, TF)
    dataset_version_path(home, VENUE, PAIR, TF, digest).write_bytes(b"tampered\n")

    before = _tree_snapshot(home)
    proc = _run_probe(tmp_path, home, zip_path, mode="plain")
    assert proc.returncode != 0, "retained-byte conflict must refuse, not overwrite"
    assert "conflicting bytes" in proc.stderr, proc.stderr
    for rel, body in before["cache"].items():
        assert (Path(home) / "cache" / rel).read_bytes() == body
    for rel, body in before["datasets"].items():
        assert (Path(home) / "datasets" / rel).read_bytes() == body

    con = sqlite3.connect(f"file:{_slot_db(home, zip_path)}?mode=ro", uri=True)
    try:
        cursor = json.loads(con.execute("SELECT value FROM meta WHERE key='cursor_json'").fetchone()[0])
    finally:
        con.close()
    assert cursor["phase"] == "parsed"


def test_same_source_lock_contention_refuses_and_recovers_after_death(home: Path, tmp_path: Path, capsys):
    """A second same-source importer refuses visibly; process death frees the lock."""
    zip_path = _write_zip(tmp_path / "lock.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})

    lock_path = _slot_lock(home, zip_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    holder_src = tmp_path / "holder.py"
    holder_src.write_text(
        textwrap.dedent(
            """
            import fcntl, sys, time

            fd = open(sys.argv[1], "a+b")
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            sys.stdout.write("held\\n")
            sys.stdout.flush()
            while True:
                time.sleep(1)
            """
        ),
        encoding="utf-8",
    )
    holder = subprocess.Popen(
        [sys.executable, str(holder_src), str(lock_path)],
        stdout=subprocess.PIPE,
        text=True,
        cwd=str(tmp_path),
    )
    try:
        assert holder.stdout.readline().strip() == "held"

        before = _tree_snapshot(home)
        rc = _import(home, zip_path)
        captured = capsys.readouterr()
        assert rc == 1, "same-source lock contention must refuse"
        assert "refus" in captured.err.lower(), captured.err
        after = _tree_snapshot(home)
        assert before["progress"] == after["progress"]
        assert before["cache"] == after["cache"]
        assert before["datasets"] == after["datasets"]
    finally:
        holder.kill()
        holder.wait(timeout=30)

    # Process death released the OS advisory lock: the import now succeeds.
    capsys.readouterr()
    assert _import(home, zip_path) == 0
    assert len(_closes(home)) == 200
    assert not _slot_db(home, zip_path).exists()


def test_progress_files_are_owner_only(home: Path, tmp_path: Path):
    """Progress directories and files are owner-only on POSIX."""
    zip_path = _write_zip(tmp_path / "perm.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})
    _pending_state(tmp_path, home, zip_path, cut=100)

    root = _progress_dir(home)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(root.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(_slot_db(home, zip_path).stat().st_mode) == 0o600
    assert stat.S_IMODE(_slot_lock(home, zip_path).stat().st_mode) == 0o600


def test_no_wal_sidecar_lifecycle(home: Path, tmp_path: Path):
    """The checkpoint uses rollback-journal transactions, not a WAL sidecar."""
    zip_path = _write_zip(tmp_path / "journal.zip", {"SUIUSD_60.csv": _candle_body(_bars(200))})
    _pending_state(tmp_path, home, zip_path, cut=100)

    db = _slot_db(home, zip_path)
    assert not db.with_name(db.name + "-wal").exists()
    assert not db.with_name(db.name + "-shm").exists()

    import sqlite3

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        sync = con.execute("PRAGMA synchronous").fetchone()[0]
    finally:
        con.close()
    assert str(mode).lower() == "delete"
    assert int(sync) == 2  # FULL


def test_checkpoint_meta_records_the_declared_identity(home: Path, tmp_path: Path):
    """meta holds the source path, whole-archive digest, exact pair/tf, members, bounds."""
    import sqlite3

    body = _candle_body(_bars(200))
    zip_path = _write_zip(
        tmp_path / "meta.zip",
        {
            "OHLCVT/SUIUSD_60.csv": body,
            "OHLCVT/SUIUSDT_60.csv": _candle_body([_bar(T0_S, "99")]),
        },
    )
    _pending_state(tmp_path, home, zip_path, cut=100)

    db = _slot_db(home, zip_path)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        meta = {k: v for k, v in con.execute("SELECT key, value FROM meta")}
        candles_schema = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='candles'"
        ).fetchone()[0]
    finally:
        con.close()

    assert set(meta) == {
        "schema_version",
        "source_path",
        "source_sha256",
        "pair",
        "tf",
        "members_json",
        "max_records",
        "max_uncompressed_bytes",
        "checkpoint_every",
        "cursor_json",
    }
    assert meta["schema_version"] == "1"
    assert meta["source_path"] == str(zip_path.resolve())
    assert meta["pair"] == PAIR
    assert meta["tf"] == TF
    assert meta["max_records"] == "1000000"
    assert meta["max_uncompressed_bytes"] == "536870912"
    assert meta["checkpoint_every"] == "128"

    digest = hashlib.sha256()
    with open(zip_path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    assert meta["source_sha256"] == digest.hexdigest()

    members = json.loads(meta["members_json"])
    assert len(members) == 1
    assert members[0]["name"] == "OHLCVT/SUIUSD_60.csv"
    assert isinstance(members[0]["ordinal"], int) and members[0]["ordinal"] >= 0
    assert isinstance(members[0]["crc"], int)
    assert members[0]["size"] == len(body)

    cursor = json.loads(meta["cursor_json"])
    assert set(cursor) == {"next_member_index", "next_row_index", "records_seen", "candles_count", "phase"}
    assert cursor["phase"] == "parsing"
    assert cursor["candles_count"] == _db_candles(db)
    assert "PRIMARY KEY (member_index, row_index)" in " ".join(candles_schema.split())
