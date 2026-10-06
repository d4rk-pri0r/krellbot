"""Kraken public OHLC: JSON parser + OHLCVT zip import.

The HTTP function `fetch_kraken_ohlc` is a thin wrapper tests never call.
Tests pass a pre-fetched JSON object to `parse_kraken_ohlc` directly, and a
fake zip path to `import_kraken_ohlcvt_zip`.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.request
import zipfile
from decimal import Decimal
from pathlib import Path

from krellbot.pack.model import Candle

from .candles import drop_forming, parse_timestamp
from .cache import write_cache
from .import_progress import (
    CHECKPOINT_EVERY,
    DEFAULT_MAX_RECORDS,
    DEFAULT_MAX_UNCOMPRESSED_BYTES,
    ImportCheckpoint,
    ImportProgressError,
    SourceLock,
    ensure_slot_dir,
    file_sha256,
    slot_paths,
    source_fingerprint,
)

OHLC_URL = "https://api.kraken.com/0/public/OHLC"
OHLC_TF_MINUTES: dict[str, int] = {"1h": 60, "4h": 240, "1d": 1440}
OHLC_CAP = 720


def fetch_kraken_ohlc(pair: str, tf: str) -> list[Candle]:
    """Fetch one window of Kraken OHLC. Returns up to 720 closed candles.

    Network is only used here; tests must call `parse_kraken_ohlc` directly.
    The 'last' integer in the response is ignored; the most recent array in
    the pair key is the forming bar and is dropped after fetching.
    """
    if tf not in OHLC_TF_MINUTES:
        raise ValueError(f"kraken: unsupported timeframe {tf!r}")
    interval = OHLC_TF_MINUTES[tf]
    url = f"{OHLC_URL}?pair={pair}&interval={interval}"
    req = urllib.request.Request(url, headers={"user-agent": "krellbot/0.1"})
    from krellbot.tls import urlopen

    with urlopen(req, timeout=20) as resp:
        body = resp.read()
    payload = json.loads(body.decode("utf-8"))
    candles = parse_kraken_ohlc(payload, pair=pair, tf=tf)
    return candles[-OHLC_CAP:]


def parse_kraken_ohlc(payload: dict, pair: str, now_ms: int | None = None, tf: str = "1h") -> list[Candle]:
    """Turn a Kraken `/public/OHLC` response into a sorted list of Candle.

    The pair key in `payload["result"]` may not equal the requested altname
    (e.g. `SUIUSD` arrives as `XSUIZUSD`). The only array-valued key in
    `payload["result"]` is the candles for the pair; use it. When `now_ms`
    is given, drop any bar whose `ts_ms + tf_ms` exceeds it (the forming
    bar). Without `now_ms`, return everything sorted.
    """
    result = payload.get("result")
    if not isinstance(result, dict):
        raise TypeError("kraken: response.result is not an object")
    pair_key = _find_pair_key(result, pair)
    rows = result[pair_key]
    if not isinstance(rows, list):
        raise TypeError("kraken: pair key is not an array")
    candles: list[Candle] = []
    for row in rows:
        if not (isinstance(row, list) and len(row) == 8):
            raise ValueError(
                f"kraken: row must have 8 fields, got {len(row) if isinstance(row, list) else type(row).__name__}"
            )
        ts_str, open_s, high_s, low_s, close_s, _vwap, vol_s, _count = row
        candles.append(
            Candle(
                ts_ms=parse_timestamp(ts_str),
                open=Decimal(str(open_s)),
                high=Decimal(str(high_s)),
                low=Decimal(str(low_s)),
                close=Decimal(str(close_s)),
                volume=Decimal(str(vol_s)),
            )
        )
    candles.sort(key=lambda c: c.ts_ms)
    if now_ms is not None:
        candles = drop_forming(candles, tf, now_ms)
    return candles


def _find_pair_key(result: dict, requested_pair: str) -> str:
    """Find the single array-valued key inside `result`.

    Kraken uses an internal name like `XSUIZUSD` for the altname `SUIUSD`.
    The only array-valued key in the response belongs to the pair we asked
    for. Do not match by name.
    """
    array_keys = [k for k, v in result.items() if isinstance(v, list) and k != "last"]
    if len(array_keys) != 1:
        raise ValueError(
            f"kraken: expected exactly one pair key, got {len(array_keys)} ({array_keys!r}); "
            f"requested={requested_pair!r}"
        )
    return array_keys[0]


def import_kraken_ohlcvt_zip(path: str | Path, pair: str, tf: str) -> list[Candle]:
    """Stream a Kraken OHLCVT zip, parse matching members, return sorted candles.

    A member is used only when its complete basename stem (case-insensitive)
    is exactly `pair + '_' + interval minutes`, with a `.csv` suffix
    (case-insensitive). The `.zip` suffix stays accepted for the legacy
    fixture that stores a CSV payload under a zip name; nested zip payloads
    are never unpacked. Directory entries are skipped, and the parent
    directory cannot supply a missing pair or interval token: matching looks
    at the basename only, never the full archive path. No alias, prefix or
    substring matching - `SUIUSDT_60.csv` is not `SUIUSD_60.csv` and
    `SUIUSD_160.csv` is not a 60-minute member.

    CSV rows are read lazily through the ZipExtFile handle - never loaded
    fully into memory before filtering. The first field of every row must be
    numeric; otherwise the row is skipped (handles a header row without
    crashing). This function stays side-effect free: it writes nothing under
    any home. The durable, restartable route for the enabled CLI is
    `import_kraken_ohlcvt_cached`, which reuses the same shared stream and the
    same `_row_to_candle` acceptance rule.
    """
    candles: list[Candle] = []
    for _member_index, _name, row in _iter_selected_rows(str(path), pair, _minutes_for(tf)):
        candle = _row_to_candle(row)
        if candle is not None:
            candles.append(candle)
    candles.sort(key=lambda c: c.ts_ms)
    return candles


def import_kraken_ohlcvt_cached(
    path: str | Path,
    pair: str,
    tf: str,
    home: Path | str,
    *,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> tuple[Path, str, int]:
    """Import one Kraken OHLCVT zip into the cache with durable local progress.

    This is the enabled `data import kraken-ohlcvt` route. It parses the same
    members with the same rules as `import_kraken_ohlcvt_zip`, but keeps a
    bounded checkpoint under `<home>/import-progress/kraken-ohlcvt/` so a hard
    process exit mid-parse resumes from the last committed 128-candle chunk
    instead of converting the whole archive again.

    The same-source lock is held from identity validation through parsing, the
    unchanged `write_cache` publication and the checkpoint cleanup. A pending
    checkpoint whose source bytes, exact pair string, timeframe, member
    descriptors, schema version or declared bounds no longer match this
    request raises `ImportProgressError` before modifying anything, as do
    contention, an unreadable/inconsistent checkpoint, a crossed record bound
    and an archive that changed in place while it was being read. The final
    sorted list is still built in memory, capped at `max_records`.

    Returns `(csv_path, sha256, row_count)`.
    """
    minutes = _minutes_for(tf)
    resolved = Path(path).resolve()

    def refuse(reason: str) -> ImportProgressError:
        return ImportProgressError(reason)

    if max_records < 1 or max_uncompressed_bytes < 1:
        raise refuse("import bounds must be positive")

    ensure_slot_dir(home)
    db_path, lock_path = slot_paths(home, resolved)
    lock = SourceLock(lock_path)
    lock.acquire()
    checkpoint: ImportCheckpoint | None = None
    try:
        before_hash = source_fingerprint(resolved)
        source_sha256 = file_sha256(resolved)
        if source_fingerprint(resolved) != before_hash:
            raise refuse(f"archive {resolved} changed while it was being hashed")

        with zipfile.ZipFile(str(resolved), "r") as zf:
            infos = zf.infolist()
            selected = [
                (ordinal, info.filename)
                for ordinal, info in enumerate(infos)
                if _member_matches(info.filename, pair, minutes)
            ]
            members_json = json.dumps(
                [
                    {"ordinal": ordinal, "name": name, "crc": infos[ordinal].CRC, "size": infos[ordinal].file_size}
                    for ordinal, name in selected
                ]
            )
            total_uncompressed = sum(infos[ordinal].file_size for ordinal, _name in selected)
            if total_uncompressed > max_uncompressed_bytes:
                raise refuse(
                    f"selected members total {total_uncompressed} uncompressed bytes, "
                    f"over the declared bound {max_uncompressed_bytes}"
                )

            identity = {
                "source_path": str(resolved),
                "source_sha256": source_sha256,
                "pair": pair,
                "tf": tf,
                "members_json": members_json,
            }
            bounds = {
                "max_records": max_records,
                "max_uncompressed_bytes": max_uncompressed_bytes,
                "checkpoint_every": CHECKPOINT_EVERY,
            }
            checkpoint = ImportCheckpoint.open_or_create(
                db_path,
                identity=identity,
                bounds=bounds,
                source_accounting=_source_accounting(zf, infos, selected),
            )

            if checkpoint.phase != "parsed":
                before_parse = source_fingerprint(resolved)
                for member_index, (ordinal, name) in enumerate(selected):
                    if member_index < checkpoint.next_member_index:
                        continue
                    start_row = checkpoint.next_row_index if member_index == checkpoint.next_member_index else 0
                    with zf.open(infos[ordinal], "r") as fh:
                        wrapper = io.TextIOWrapper(fh, encoding="utf-8", newline="")
                        reader = csv.reader(wrapper)
                        for row_index, row in enumerate(reader):
                            if row_index < start_row:
                                continue
                            if checkpoint.records_seen >= max_records:
                                raise refuse(
                                    f"import crossed the declared bound of {max_records} selected records"
                                )
                            candle = _row_to_candle(row)
                            record = (
                                None
                                if candle is None
                                else (
                                    candle.ts_ms,
                                    str(candle.open),
                                    str(candle.high),
                                    str(candle.low),
                                    str(candle.close),
                                    str(candle.volume),
                                )
                            )
                            checkpoint.note_record(member_index, row_index, record)
                    checkpoint.commit(next_member_index=member_index + 1, next_row_index=0)
                if source_fingerprint(resolved) != before_parse:
                    raise refuse(f"archive {resolved} changed while it was being parsed")
                checkpoint.commit(
                    next_member_index=len(selected), next_row_index=0, phase="parsed"
                )

            rows = checkpoint.load_candles()
            candles: list[Candle] = [
                Candle(
                    ts_ms=ts_ms,
                    open=Decimal(open_s),
                    high=Decimal(high_s),
                    low=Decimal(low_s),
                    close=Decimal(close_s),
                    volume=Decimal(volume_s),
                )
                for ts_ms, open_s, high_s, low_s, close_s, volume_s in rows
            ]
            candles.sort(key=lambda c: c.ts_ms)
        csv_path, digest = write_cache(Path(home), "kraken", pair, tf, candles)
        checkpoint.discard()
        return csv_path, digest, len(candles)
    finally:
        if checkpoint is not None:
            checkpoint.close()
        lock.release()


def _minutes_for(tf: str) -> str:
    if tf not in OHLC_TF_MINUTES:
        raise ValueError(f"kraken zip: unsupported timeframe {tf!r}")
    return str(OHLC_TF_MINUTES[tf])


def _row_is_candle(row: list[str] | None) -> bool:
    """The acceptance half of `_row_to_candle` without converting anything.

    True exactly when the shared rule would accept the row: non-empty, a
    numeric first field (headers and non-numeric rows are skipped) and
    exactly 7 fields. This never calls `parse_timestamp` or builds a Decimal,
    so validating a committed prefix against the source does not reconvert
    any already-stored candle.
    """
    if not row:
        return False
    if not _is_numeric(row[0].strip()):
        return False
    return len(row) == 7


def _source_accounting(zf: zipfile.ZipFile, infos, selected):
    """Build the read-only source-prefix validator for one pending checkpoint.

    The returned callable runs while the checkpoint is still open read-only,
    before any writable access or cache publication. It streams the selected
    members in archive order - completed members fully, the current member up
    to its cursor row - and refuses any cursor or stored candle position the
    source does not account for, in every selected member occurrence and in
    both the parsing and parsed phases. Reopening and decompressing the
    compressed prefix is allowed; reconverting committed candles is not done.
    """

    def account(con, cursor) -> None:
        completed = int(cursor["next_member_index"])
        next_row = int(cursor["next_row_index"])
        member_count = len(selected)
        prefix_members = completed + (1 if completed < member_count else 0)
        records = 0
        accepted: dict[int, list[int]] = {}
        for member_index in range(prefix_members):
            ordinal, name = selected[member_index]
            limit = None if member_index < completed else next_row
            positions: list[int] = []
            seen = 0
            with zf.open(infos[ordinal], "r") as fh:
                wrapper = io.TextIOWrapper(fh, encoding="utf-8", newline="")
                for row_index, row in enumerate(csv.reader(wrapper)):
                    if limit is not None and row_index >= limit:
                        break
                    seen += 1
                    if _row_is_candle(row):
                        positions.append(row_index)
            if limit is not None and seen < limit:
                raise ImportProgressError(
                    f"checkpoint cursor is outside the selected source: member {member_index} "
                    f"({name}) holds {seen} records but the cursor points at {limit}; refusing to resume"
                )
            accepted[member_index] = positions
            records += seen
        if records != int(cursor["records_seen"]):
            raise ImportProgressError(
                f"checkpoint records_seen {cursor['records_seen']} does not account the "
                f"{records} selected source records before its cursor; refusing to resume"
            )
        stored: dict[int, list[int]] = {}
        for member_index, row_index in con.execute("SELECT member_index, row_index FROM candles"):
            stored.setdefault(int(member_index), []).append(int(row_index))
        for member_index in range(prefix_members):
            if sorted(stored.pop(member_index, [])) != accepted[member_index]:
                raise ImportProgressError(
                    f"checkpoint candle positions in member {member_index} do not match the "
                    "candle occurrences the selected source actually holds before its cursor; "
                    "refusing to resume"
                )
        if stored:
            raise ImportProgressError(
                f"checkpoint holds candles in members {sorted(stored)} outside its cursor prefix; "
                "refusing to resume"
            )

    return account


def _row_to_candle(row: list[str] | None) -> Candle | None:
    """Apply the historical row rule: one accepted candle or `None` to skip.

    The first field must be numeric (headers and non-numeric rows are skipped),
    the row must have exactly 7 fields (wrong-width rows are skipped), and the
    accepted prices/volume are exact decimal text.
    """
    if not row:
        return None
    first = row[0].strip()
    if not _is_numeric(first):
        return None
    if len(row) != 7:
        return None
    time_s, open_s, high_s, low_s, close_s, vol_s, _count = row
    return Candle(
        ts_ms=parse_timestamp(time_s.strip()),
        open=Decimal(open_s.strip()),
        high=Decimal(high_s.strip()),
        low=Decimal(low_s.strip()),
        close=Decimal(close_s.strip()),
        volume=Decimal(vol_s.strip()),
    )


def _iter_selected_rows(path: str | Path, pair: str, minutes: str):
    """Yield `(selected_member_index, member_name, row)` for matching members.

    Members are visited in archive order and their CSV records are read
    lazily through the ZipExtFile handle. Rows are yielded raw; acceptance is
    decided by the single shared `_row_to_candle` rule.
    """
    with zipfile.ZipFile(str(path), "r") as zf:
        selected_index = 0
        for name in zf.namelist():
            if not _member_matches(name, pair, minutes):
                continue
            with zf.open(name, "r") as fh:
                wrapper = io.TextIOWrapper(fh, encoding="utf-8", newline="")
                for row in csv.reader(wrapper):
                    yield selected_index, name, row
            selected_index += 1


# `.csv` is the documented member name; `.zip` is kept only for the legacy
# fixture that stores a CSV payload under a zip name.
_MEMBER_SUFFIXES = (".csv", ".zip")


def _member_matches(name: str, pair: str, minutes: str) -> bool:
    """True when member `name` is the `pair`/`minutes` OHLCVT CSV by basename.

    Only the basename (after the last `/`) is considered, so a directory
    component never satisfies the identity. The stem must equal
    `pair + '_' + minutes` exactly, case-insensitively; the requested pair and
    interval tokens must be complete, so near-collisions such as `SUIUSDT`,
    `160` for `60`, or a stem holding only one of the two tokens never match.
    """
    if name.endswith("/"):
        return False
    basename = name.rsplit("/", 1)[-1].lower()
    for suffix in _MEMBER_SUFFIXES:
        if basename.endswith(suffix):
            stem = basename[: -len(suffix)]
            return stem == f"{pair.lower()}_{minutes}"
    return False


def _is_numeric(s: str) -> bool:
    if not s:
        return False
    if s[0] in "+-":
        s = s[1:]
    return s.isdigit()
