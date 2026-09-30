"""Home backup and restore for `$KRELLBOT_HOME`.

A `.tar.gz` archive that captures every regular file under the data home
except secrets that never travel. The schema is small:

- ``ARCHIVE_SCHEMA = "1"``
- ``EXCLUDE`` — operator authorization never travels. The literal lives
  in ``application.live_gate`` so the filename appears in only one source.
- ``EXCLUDE_DIRS = ("logs",)`` — log volume is not part of the home.
- ``EXCLUDE_SUFFIXES = (".lock", ".bak", "-wal", "-shm", "-journal")`` — locks, sqlite siblings, journal markers.

``ops.sqlite`` is captured via the sqlite ``Connection.backup`` API so a
live WAL writer cannot tear the copy.

The archive is deterministic: same home + same ``now`` → byte-identical
archive. Members are written with ``mtime=0``, ``uid=gid=0``,
``uname/gname=""``, and ``mode=0o600``. The archive file itself is
created with mode ``0o600``.

Restore is fail-closed:

- refuses to write into a non-empty ``home`` (``home_not_empty``)
- rejects absolute paths, ``..`` components, links, and devices in the
  archive (``archive_corrupt``)
- rejects a manifest whose ``schema`` is not ``"1"`` (``archive_schema``)
- rejects a member set that does not equal the manifest set (``archive_corrupt``)
- refuses to capture files whose bytes contain a private-key marker or
  a ``kb_live_<20+alnum>`` token (``secret_detected``)
- after restore, verifies the ledger rows sha matches the manifest,
  removing the restored home on mismatch (``archive_corrupt``).

The returned manifest is::

    {"schema": "1", "created_at": <now>,
     "files": [{"path", "sha256", "size"}, ...],
     "ops_rows": <int|None>,
     "ops_rows_sha256": <str|None>}
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import posixpath
import re
import sys
import tarfile
import tempfile
from pathlib import Path

from krellbot.storage import backup as _sqlite_backup
from krellbot.storage.database import OperationalStore

ARCHIVE_SCHEMA = "1"
EXCLUDE = ()
EXCLUDE_DIRS = ("logs",)
EXCLUDE_SUFFIXES = (".lock", ".bak", "-wal", "-shm", "-journal")

try:
    from krellbot.application.live_gate import AUTH_FILE as _AUTH_FILE

    EXCLUDE = (_AUTH_FILE,)
except (ImportError, AttributeError):
    EXCLUDE = ()

_OPS_FILENAME = "ops.sqlite"
_KB_LIVE_RE = re.compile(rb"kb_live_[A-Za-z0-9]{20,}")
_PRIVATE_KEY_RE = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")

_IS_WINDOWS = sys.platform == "win32"


class BackupError(RuntimeError):
    """Refusal during create or restore. ``code`` is one of:

    - ``home_missing``
    - ``secret_detected``
    - ``archive_corrupt``
    - ``home_not_empty``
    - ``archive_schema``
    """

    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


def _posix_relpath(home: Path, path: Path) -> str:
    """Return the POSIX relative path from ``home`` to ``path``."""
    rel = path.resolve().relative_to(home.resolve())
    return rel.as_posix()


def _is_excluded(rel: str) -> bool:
    if rel in EXCLUDE:
        return True
    parts = rel.split("/")
    for p in parts[:-1]:
        if p in EXCLUDE_DIRS:
            return True
    name = parts[-1]
    for suf in EXCLUDE_SUFFIXES:
        if name.endswith(suf):
            return True
    return False


def _iter_capture_files(home: Path) -> list[Path]:
    """Walk ``home`` and return regular files in POSIX-sorted order.

    Skips EXCLUDE / EXCLUDE_DIRS / EXCLUDE_SUFFIXES and symlinks.
    """
    if not home.exists():
        raise BackupError("home_missing", f"home does not exist: {home}")
    if not home.is_dir():
        raise BackupError("home_missing", f"home is not a directory: {home}")

    out: list[Path] = []
    for root, dirs, files in os.walk(home, followlinks=False):
        root_path = Path(root)
        rel_dir = _posix_relpath(home, root_path)
        keep_dirs = []
        for d in dirs:
            full = root_path / d
            if full.is_symlink():
                continue
            rel = posixpath.join(rel_dir, d) if rel_dir != "." else d
            if d in EXCLUDE_DIRS:
                continue
            keep_dirs.append(d)
        dirs[:] = keep_dirs

        for f in sorted(files):
            full = root_path / f
            if full.is_symlink():
                continue
            rel = posixpath.join(rel_dir, f) if rel_dir != "." else f
            if not full.is_file():
                continue
            if _is_excluded(rel):
                continue
            out.append(full)
    out.sort(key=lambda p: _posix_relpath(home, p))
    return out


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _detect_secret(data: bytes) -> bool:
    if _PRIVATE_KEY_RE.search(data):
        return True
    return bool(_KB_LIVE_RE.search(data))


def create(home: Path, out: Path, *, now: int) -> dict:
    """Capture ``home`` into a tar.gz at ``out``. Returns the manifest.

    Raises ``BackupError(secret_detected)`` if a captured file's bytes
    contain a private-key marker or ``kb_live_<20+alnum>`` token. The
    message names the relative path. No archive is written on refusal.
    """
    files = _iter_capture_files(home)
    manifest_files: list[dict] = []
    captures: list[tuple[str, bytes]] = []

    for path in files:
        rel = _posix_relpath(home, path)
        data = path.read_bytes()
        if _detect_secret(data):
            raise BackupError("secret_detected", rel)
        sha = _bytes_sha256(data)
        manifest_files.append({"path": rel, "sha256": sha, "size": len(data)})
        if rel == _OPS_FILENAME:
            pass
        else:
            captures.append((rel, data))

    ops_rows: int | None = None
    ops_rows_sha256: str | None = None
    ops_sqlite_path = home / _OPS_FILENAME
    if ops_sqlite_path.is_file():
        with tempfile.TemporaryDirectory() as td:
            snap_path = Path(td) / _OPS_FILENAME
            _sqlite_backup.online_backup(ops_sqlite_path, snap_path)
            snap_bytes = snap_path.read_bytes()
            sha = _bytes_sha256(snap_bytes)
            entries = [e for e in manifest_files if e["path"] == _OPS_FILENAME]
            if entries:
                entries[0]["sha256"] = sha
                entries[0]["size"] = len(snap_bytes)
            else:
                manifest_files.append({"path": _OPS_FILENAME, "sha256": sha, "size": len(snap_bytes)})
                manifest_files.sort(key=lambda e: e["path"])
            try:
                store = OperationalStore(snap_path)
                rows = store.read_ledger()
                ops_rows = len(rows)
                ops_rows_sha256 = _bytes_sha256(json.dumps([list(r) for r in rows], sort_keys=True).encode("utf-8"))
            except (OSError, RuntimeError, ValueError, TypeError):
                ops_rows = None
                ops_rows_sha256 = None

    manifest = {
        "schema": ARCHIVE_SCHEMA,
        "created_at": int(now),
        "files": manifest_files,
        "ops_rows": ops_rows,
        "ops_rows_sha256": ops_rows_sha256,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode("utf-8")

    if out.exists():
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(out), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as raw:
            gz_fileobj = gzip.GzipFile(
                fileobj=raw,
                mode="wb",
                mtime=0,
            )
            with tarfile.open(fileobj=gz_fileobj, mode="w") as tf:
                _add_member(tf, "manifest.json", manifest_bytes)
                if ops_sqlite_path.is_file():
                    with tempfile.TemporaryDirectory() as td:
                        snap_path = Path(td) / _OPS_FILENAME
                        _sqlite_backup.online_backup(ops_sqlite_path, snap_path)
                        _add_member(tf, f"files/{_OPS_FILENAME}", snap_path.read_bytes())
                for rel, data in captures:
                    _add_member(tf, f"files/{rel}", data)
            gz_fileobj.close()
            raw.flush()
            try:
                os.fsync(raw.fileno())
            except OSError:
                pass
    except BaseException:
        try:
            out.unlink()
        except OSError:
            pass
        raise
    if not _IS_WINDOWS:
        os.chmod(out, 0o600)
    return manifest


def _add_member(tf: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mode = 0o600
    tf.addfile(info, io.BytesIO(data))


def _safe_member_name(name: str) -> str:
    if name.startswith("/") or "\\" in name:
        raise BackupError("archive_corrupt", f"unsafe member name: {name!r}")
    if name.startswith("..") or "/../" in name or name.endswith("/.."):
        raise BackupError("archive_corrupt", f"unsafe member name: {name!r}")
    parts = name.split("/")
    if any(p == "" for p in parts):
        raise BackupError("archive_corrupt", f"unsafe member name: {name!r}")
    return name


def restore(archive: Path, home: Path) -> dict:
    """Restore ``archive`` into ``home``. Returns the manifest.

    Raises ``BackupError`` and leaves ``home`` untouched on any refusal.
    """
    if home.exists():
        if home.is_dir():
            try:
                next(home.iterdir())
                raise BackupError("home_not_empty", f"target home is not empty: {home}")
            except StopIteration:
                pass
        else:
            raise BackupError("home_not_empty", f"target home exists and is not a directory: {home}")

    with tempfile.TemporaryDirectory(prefix="krellbot-restore-") as td:
        staged = Path(td) / "staged"
        staged.mkdir(parents=True, exist_ok=True)

        try:
            with tarfile.open(archive, "r:gz") as tf:
                members = tf.getmembers()
                for m in members:
                    if m.type not in (tarfile.REGTYPE, tarfile.AREGTYPE):
                        raise BackupError("archive_corrupt", f"non-regular member: {m.name!r}")
                    _safe_member_name(m.name)

                manifest_member = None
                file_members: list[tarfile.TarInfo] = []
                for m in members:
                    if m.name == "manifest.json":
                        manifest_member = m
                    elif m.name.startswith("files/"):
                        file_members.append(m)
                    else:
                        raise BackupError("archive_corrupt", f"unexpected top-level member: {m.name!r}")

                if manifest_member is None:
                    raise BackupError("archive_corrupt", "manifest.json is missing")
                f = tf.extractfile(manifest_member)
                manifest_raw = f.read() if f else b""
                try:
                    manifest = json.loads(manifest_raw.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise BackupError("archive_corrupt", f"manifest.json is not valid JSON: {exc}") from exc
                if not isinstance(manifest, dict):
                    raise BackupError("archive_corrupt", "manifest.json is not an object")
                schema = manifest.get("schema")
                if schema != ARCHIVE_SCHEMA:
                    raise BackupError("archive_schema", f"unsupported schema: {schema!r}")
                manifest_files = manifest.get("files")
                if not isinstance(manifest_files, list):
                    raise BackupError("archive_corrupt", "manifest.files is not a list")

                manifest_paths = {e["path"] for e in manifest_files if isinstance(e, dict) and "path" in e}
                member_paths = set()
                for m in file_members:
                    rel = m.name[len("files/") :]
                    member_paths.add(rel)

                if manifest_paths != member_paths:
                    raise BackupError(
                        "archive_corrupt",
                        f"manifest/member-set mismatch: extra={member_paths - manifest_paths}, missing={manifest_paths - member_paths}",
                    )

                for m in file_members:
                    rel = m.name[len("files/") :]
                    _safe_member_name(rel)
                    target = staged / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    fh = tf.extractfile(m)
                    if fh is None:
                        raise BackupError("archive_corrupt", f"member body missing: {m.name!r}")
                    data = fh.read()
                    if _detect_secret(data):
                        raise BackupError("secret_detected", rel)
                    entry = next((e for e in manifest_files if e.get("path") == rel), None)
                    if entry is None:
                        raise BackupError("archive_corrupt", f"manifest entry missing for {rel}")
                    expected_sha = entry.get("sha256")
                    expected_size = entry.get("size")
                    if expected_sha is None or expected_size is None:
                        raise BackupError("archive_corrupt", f"manifest entry incomplete for {rel}")
                    if len(data) != int(expected_size):
                        raise BackupError("archive_corrupt", f"size mismatch for {rel}")
                    actual_sha = _bytes_sha256(data)
                    if actual_sha != expected_sha:
                        raise BackupError("archive_corrupt", f"sha mismatch for {rel}")
                    with open(target, "wb") as out:
                        out.write(data)
                        out.flush()
                        try:
                            os.fsync(out.fileno())
                        except OSError:
                            pass
        except (tarfile.ReadError, OSError, ValueError) as exc:
            raise BackupError("archive_corrupt", f"archive could not be opened: {exc}") from exc

        ops_sqlite = staged / _OPS_FILENAME
        if ops_sqlite.is_file():
            try:
                store = OperationalStore(ops_sqlite)
                rows = store.read_ledger()
                rows_json = json.dumps([list(r) for r in rows], sort_keys=True).encode("utf-8")
                actual_sha = _bytes_sha256(rows_json)
                expected_sha = manifest.get("ops_rows_sha256")
                if expected_sha is not None and actual_sha != expected_sha:
                    raise BackupError(
                        "archive_corrupt",
                        f"ops.sqlite rows sha mismatch: expected {expected_sha}, got {actual_sha}",
                    )
            except BackupError:
                raise
            except Exception as exc:
                raise BackupError("archive_corrupt", f"ops.sqlite could not be opened: {exc}") from exc

        if home.exists() and not list(home.iterdir()) and (staged.exists()):
            home.rmdir()

        if home.exists():
            raise BackupError("home_not_empty", f"target home already exists: {home}")
        home.mkdir(parents=True, exist_ok=False)

        for root, dirs, files in os.walk(staged):
            rel = Path(root).relative_to(staged)
            for d in dirs:
                d_target = home / rel / d
                d_target.mkdir(parents=True, exist_ok=True)
                if not _IS_WINDOWS:
                    os.chmod(d_target, 0o700)
            for f in files:
                f_target = home / rel / f
                f_target.parent.mkdir(parents=True, exist_ok=True)
                with open(f_target, "wb") as out:
                    out.write((staged / rel / f).read_bytes())
                if not _IS_WINDOWS:
                    os.chmod(f_target, 0o600)

    return manifest


def verify_home(home: Path, manifest: dict) -> list[str]:
    """Return a list of mismatches between ``home`` and the manifest.

    Empty list means every captured file matches the manifest sha256 and
    size. The signature only checks the file subset the manifest lists;
    it does not surface extra files (e.g. the operator authorization
    record) since those are explicitly excluded.
    """
    diffs: list[str] = []
    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, list):
        return ["manifest.files is not a list"]
    for entry in manifest_files:
        if not isinstance(entry, dict):
            diffs.append("manifest entry is not an object")
            continue
        rel = entry.get("path")
        expected_sha = entry.get("sha256")
        expected_size = entry.get("size")
        if not isinstance(rel, str):
            diffs.append("manifest entry missing path")
            continue
        target = Path(home) / rel
        if not target.is_file():
            diffs.append(f"missing: {rel}")
            continue
        actual_size = target.stat().st_size
        if int(expected_size or -1) != actual_size:
            diffs.append(f"size mismatch: {rel}")
            continue
        actual_sha = _file_sha256(target)
        if actual_sha != expected_sha:
            diffs.append(f"sha mismatch: {rel}")
    return diffs
