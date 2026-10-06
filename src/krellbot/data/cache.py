"""CSV candle cache + JSON manifest.

One CSV per `(venue, pair, tf)` lives under `<KRELLBOT_HOME>/cache/`. The
manifest is a sibling `.manifest.json` with `{sha256, rows, venue, pair, tf}`.
The `sha256` is the hex digest of the CSV bytes, not of any in-memory form.

The stable pair is intentionally replaceable: a later import of the same
market atomically overwrites both files. So that a digest already recorded by
a consumer stays retrievable, every newly emitted pair is also copied into an
immutable content-addressed version store under
`<home>/datasets/imported/<cache_csv_stem>/<sha256>.csv` (plus the exact same
manifest bytes beside it). That store holds the imported canonical candle
dataset, not the caller's original archive and not a raw/derived provenance
record. This is managed immutability - refusing to overwrite conflicting bytes
- not OS-enforced tamperproof storage.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
from decimal import Decimal
from pathlib import Path

from krellbot import paths as kb_paths
from krellbot.pack.model import Candle

CSV_HEADER = "ts_ms,open,high,low,close,volume"

_IS_WINDOWS = sys.platform == "win32"
_DIGEST_RE = re.compile(r"\A[0-9a-f]{64}\Z")


def sha256_bytes(data: bytes) -> str:
    """Hex sha256 of `data`."""
    return hashlib.sha256(data).hexdigest()


def cache_path(home: Path, venue: str, pair: str, tf: str) -> Path:
    """Return `<home>/cache/<venue>__<pair>__<tf>.csv`."""
    safe_pair = pair.replace("/", "_")
    return Path(home) / "cache" / f"{venue}__{safe_pair}__{tf}.csv"


def manifest_path(home: Path, venue: str, pair: str, tf: str) -> Path:
    """Return the manifest sibling of `cache_path(home, venue, pair, tf)`."""
    return cache_path(home, venue, pair, tf).with_suffix(".manifest.json")


def dataset_version_path(home: Path, venue: str, pair: str, tf: str, digest: str) -> Path:
    """Return the immutable version CSV for `digest` of one cache market.

    `<home>/datasets/imported/<cache_csv_stem>/<digest>.csv`. The digest must
    be exactly 64 lowercase hex characters, so a caller cannot traverse out of
    the market directory.
    """
    stem = cache_path(home, venue, pair, tf).stem
    return Path(home) / "datasets" / "imported" / stem / f"{_require_digest(digest)}.csv"


def dataset_version_manifest_path(home: Path, venue: str, pair: str, tf: str, digest: str) -> Path:
    """Return the manifest sibling of `dataset_version_path(...)`."""
    return dataset_version_path(home, venue, pair, tf, digest).with_suffix(".manifest.json")


def _require_digest(digest: str) -> str:
    if not isinstance(digest, str) or not _DIGEST_RE.match(digest):
        raise ValueError(f"digest must be 64 lowercase hex characters, got {digest!r}")
    return digest


def write_cache(
    home: Path,
    venue: str,
    pair: str,
    tf: str,
    candles: list[Candle],
) -> tuple[Path, str]:
    """Write CSV + manifest. Returns (csv_path, sha256).

    The CSV is written with utf-8 + \\n newlines, no BOM. The sha256 is taken
    over the bytes that hit disk, not the bytes the caller had in memory.

    The immutable version pair is stored (or verified, when this content
    already exists) before the stable cache is touched, so a failed version
    store never leaves the stable cache ahead of the retained history.
    """
    csv_path = cache_path(home, venue, pair, tf)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    body = _render_csv(candles)
    digest = sha256_bytes(body)
    manifest = {
        "sha256": digest,
        "rows": len(candles),
        "venue": venue,
        "pair": pair,
        "tf": tf,
    }
    manifest_body = json.dumps(manifest, sort_keys=True).encode("utf-8")
    _store_dataset_version(home, venue, pair, tf, digest, body, manifest_body)
    kb_paths.atomic_write(csv_path, body, mode=0o600)
    kb_paths.atomic_write(
        manifest_path(home, venue, pair, tf),
        manifest_body,
        mode=0o600,
    )
    return csv_path, digest


def read_cache(
    home: Path,
    venue: str,
    pair: str,
    tf: str,
) -> tuple[list[Candle], str] | None:
    """Return `(candles, sha256)` if the cache exists, else `None`.

    The sha256 is read from the manifest so the backtest can record the
    exact bytes the cache currently holds.
    """
    csv_path = cache_path(home, venue, pair, tf)
    man_path = manifest_path(home, venue, pair, tf)
    if not csv_path.exists() or not man_path.exists():
        return None
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    body = csv_path.read_bytes()
    return _parse_csv(body), manifest["sha256"]


def _store_dataset_version(
    home: Path,
    venue: str,
    pair: str,
    tf: str,
    digest: str,
    csv_body: bytes,
    manifest_body: bytes,
) -> None:
    """Store one immutable (CSV, manifest) version, or verify it when present.

    Files are created exclusively (O_EXCL, mode 0600) and never rewritten, so
    repeated identical input reuses the existing bytes without touching them.
    If a version file already exists with different bytes, the conflict is
    raised to the caller and nothing on disk is modified - neither the prior
    immutable version nor the current stable pair. The pair is stored before
    `write_cache` replaces the stable cache, so a refused write cannot strand
    the stable cache ahead of the retained history.
    """
    csv_path = dataset_version_path(home, venue, pair, tf, digest)
    man_path = dataset_version_manifest_path(home, venue, pair, tf, digest)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not _IS_WINDOWS:
        os.chmod(csv_path.parent, 0o700)
    existing_csv = csv_path.read_bytes() if csv_path.exists() else None
    if existing_csv is None:
        _create_exclusive(csv_path, csv_body, digest)
    elif existing_csv != csv_body:
        raise ValueError(f"immutable dataset version {csv_path} has conflicting bytes; refusing to overwrite")
    existing_man = man_path.read_bytes() if man_path.exists() else None
    if existing_man is None:
        _create_exclusive(man_path, manifest_body, digest)
    elif existing_man != manifest_body:
        raise ValueError(f"immutable dataset version {man_path} has conflicting bytes; refusing to overwrite")


def _create_exclusive(path: Path, data: bytes, digest: str) -> None:
    """Create `path` with `data` exclusively, fsync it, and leave it in place.

    An existing file is never opened for writing. `FileExistsError` from a
    concurrent creator is treated as reuse: the stored bytes are compared, so
    the loser of a race either confirms identical content or reports a visible
    conflict instead of silently overwriting it.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(str(path), flags, 0o600)
    except FileExistsError:
        _verify_exclusive(path, data, digest)
        return
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    if not _IS_WINDOWS:
        os.chmod(path, 0o600)


def _verify_exclusive(path: Path, data: bytes, digest: str) -> None:
    try:
        stored = path.read_bytes()
    except OSError as exc:
        raise OSError(f"immutable dataset version {path} became unreadable after concurrent create") from exc
    if stored != data:
        raise ValueError(
            f"immutable dataset version {path} has conflicting bytes for digest {digest}; refusing to overwrite"
        )


def _render_csv(candles: list[Candle]) -> bytes:
    """Render candles to CSV bytes. Newline-terminated, no trailing newline gymnastics."""
    out = io.StringIO()
    out.write(CSV_HEADER + "\n")
    for c in candles:
        out.write(f"{c.ts_ms},{c.open},{c.high},{c.low},{c.close},{c.volume}\n")
    return out.getvalue().encode("utf-8")


def _parse_csv(body: bytes) -> list[Candle]:
    """Parse CSV bytes (with or without header) into candles. Skips bad rows."""
    text = body.decode("utf-8")
    out: list[Candle] = []
    seen_header = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if not seen_header and line.startswith("ts_ms,"):
            seen_header = True
            continue
        parts = line.split(",")
        if len(parts) != 6:
            continue
        try:
            out.append(
                Candle(
                    ts_ms=int(parts[0]),
                    open=Decimal(parts[1]),
                    high=Decimal(parts[2]),
                    low=Decimal(parts[3]),
                    close=Decimal(parts[4]),
                    volume=Decimal(parts[5]),
                )
            )
        except (ValueError, IndexError):
            continue
    return out
