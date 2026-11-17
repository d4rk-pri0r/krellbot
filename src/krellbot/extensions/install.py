"""Atomic stage-then-rename helper for `community.install`.

`community.install` calls `atomic_install` after fetching the pack body.
The body is first written to a separate temp directory, then validated:

  * bodies over `MAX_BODY_BYTES` are refused;
  * tar bodies with an entry name that escapes the staging directory
    (`..`, leading `/`, or backslash) are refused (Zip Slip);
  * tar bodies with a symlink whose target resolves outside the staging
    directory are refused;
  * non-tar bodies must parse as a strict UTF-8 JSON object whose embedded
    `id` equals the requested pack id, so an index entry cannot serve
    different-pack content under a trusted name; the nonstandard JSON
    constants `NaN`, `Infinity` and `-Infinity` are refused.

Any refusal raises `kb_community.InstallPayloadError` *before* any
`os.replace` to the destination, so a previous install file (if any) is
left unchanged. The requested pack id is validated first: it must be a
single path segment, because it names both the staged file and the
installed file. On success the staged file is renamed into
`<home>/packs/community/<pack_id>.json` via a single `os.replace`, which
is atomic on POSIX.
"""

from __future__ import annotations

import json
import os
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

MAX_BODY_BYTES = 1_000_000


def _open_tar(body: bytes) -> tarfile.TarFile | None:
    """Return a `TarFile` for `body` if it is a parseable tar, else None.

    A failure to parse is reported as None so the caller can distinguish
    "not an archive, treat as raw bytes" from "malformed archive,
    refuse".
    """
    try:
        return tarfile.open(fileobj=BytesIO(body))
    except (tarfile.TarError, OSError, ValueError):
        return None


def _validate_tar(body: bytes, install_dir: Path) -> None:
    """Refuse tar entries that traverse or escape `install_dir`.

    Raises `kb_community.InstallPayloadError` on any traversal or escape.
    Both absolute and relative escapes are caught: a name containing
    `..`, leading `/`, or `\\` is treated as traversal; a symlink whose
    resolved target is outside `install_dir` is treated as escape.
    """
    from krellbot import community as kb_community

    with _open_tar(body) as tar:
        if tar is None:
            raise kb_community.InstallPayloadError("community pack body is not a parseable tar archive")
        try:
            members = tar.getmembers()
        except tarfile.TarError as exc:
            raise kb_community.InstallPayloadError(
                f"community pack body tar is malformed: {type(exc).__name__}"
            ) from exc

    install_dir_resolved = install_dir.resolve()
    install_dir_norm = os.path.normpath(str(install_dir_resolved))
    for member in members:
        name = member.name
        # Archive traversal (Zip Slip): a `..` component, a leading `/`,
        # or a backslash separator lets a tar entry escape the extract
        # directory when the installer joins it to the base path.
        normalized = name.replace("\\", "/")
        parts = normalized.split("/")
        if ".." in parts or name.startswith("/") or "\\" in name:
            raise kb_community.InstallPayloadError(f"community pack body refuses archive traversal: {name!r}")

        # Symlink that escapes the install directory. Both symbolic and
        # hard links are checked: a hard link can also write outside
        # the staging dir if its target resolves elsewhere.
        if member.issym() or member.islnk():
            linkname = member.linkname or ""
            target = os.path.normpath(os.path.join(str(install_dir), linkname))
            if target != install_dir_norm and not target.startswith(install_dir_norm + os.sep):
                raise kb_community.InstallPayloadError(
                    f"community pack body refuses symlink escape: {name!r} -> {linkname!r}"
                )


def _validate_raw_json_identity(body: bytes, pack_id: str) -> None:
    """Refuse a non-tar body that is not a strict UTF-8 JSON object whose
    `id` is exactly `pack_id`.

    Runs before any staging or destination mutation, so a bad body leaves a
    previous install untouched and creates nothing. Tar bodies never reach
    this check: they are archive payloads, qualified by `_validate_tar`, and
    must not be re-interpreted as JSON.
    """
    from krellbot import community as kb_community

    def _reject_constant(name: str) -> None:
        # `json.loads` accepts NaN/Infinity/-Infinity by default, which are
        # not part of the JSON standard and poison downstream Decimal math.
        # `parse_constant` fires for every occurrence, nested included.
        raise kb_community.InstallPayloadError(f"community pack body uses nonstandard JSON constant: {name}")

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise kb_community.InstallPayloadError(f"community pack body is not valid UTF-8: {exc}") from exc

    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise kb_community.InstallPayloadError(f"community pack body is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise kb_community.InstallPayloadError(f"community pack body must be a JSON object, got {type(data).__name__}")

    embedded_id = data.get("id")
    if embedded_id != pack_id:
        raise kb_community.InstallPayloadError(
            f"community pack body id {embedded_id!r} does not match requested pack id {pack_id!r}"
        )


def _safe_pack_id(pack_id: str) -> str:
    """Return a single path-segment pack id, or raise InstallPayloadError.

    Uses ``os.path.basename`` (CodeQL-recognized sanitizer) so directory
    components never reach a path expression. The id names both the
    staged file and the installed file.
    """
    import os.path

    from krellbot import community as kb_community

    if type(pack_id) is not str or not pack_id:
        raise kb_community.InstallPayloadError("community pack id is not a single path segment: ''")
    # CodeQL-recognized sanitizer: basename strips directory components.
    name = os.path.basename(pack_id)
    # Both separators are refused regardless of host OS: a backslash id is
    # a literal name on POSIX but a path separator on Windows, and a
    # drive-relative id ("C:pack") has no separator at all yet still
    # names a location outside the staging/install directories there.
    windows_drive = len(name) >= 2 and name[1] == ":" and name[0].isalpha()
    if (
        not name
        or name != pack_id
        or os.path.basename(name) != name
        or "\x00" in pack_id
        or "/" in pack_id
        or "\\" in pack_id
        or windows_drive
        or name in {".", ".."}
    ):
        raise kb_community.InstallPayloadError(f"community pack id is not a single path segment: {pack_id!r}")
    return name


def _confined_json_path(base_dir: Path, pack_id: str) -> str:
    """Return ``base_dir/<basename(pack_id).json>`` after CodeQL path guards.

    ``pack_id`` must already be a single path segment. Uses
    ``os.path.basename`` + ``normpath`` + ``startswith`` containment —
    the idiom CodeQL documents for ``py/path-injection`` — then returns
    the checked path string for ``os.open`` / ``os.replace``.
    """
    import os.path

    from krellbot import community as kb_community

    # CodeQL-recognized sanitizer: basename strips directory components.
    # Basename the full filename (id + closed ``.json`` suffix).
    name = os.path.basename(f"{pack_id}.json")
    if not name or name in {".", ".."} or os.path.basename(name) != name:
        raise kb_community.InstallPayloadError(f"community pack id is not a single path segment: {pack_id!r}")
    if not name.endswith(".json") or name.startswith("."):
        raise kb_community.InstallPayloadError(f"community pack id is not a single path segment: {pack_id!r}")
    base_path = os.path.realpath(str(base_dir))
    fullpath = os.path.normpath(os.path.join(base_path, name))
    if fullpath != base_path and not fullpath.startswith(base_path + os.sep):
        raise kb_community.InstallPayloadError(f"community pack id is not a single path segment: {pack_id!r}")
    return fullpath


def read_installed_json(home: Path, pack_id: str) -> dict:
    """Read ``<home>/packs/community/<id>.json`` after CodeQL path guards.

    Same-module sink as ``atomic_install``: ``_safe_pack_id`` then
    ``_confined_json_path`` then ``os.open`` / ``os.read``. Cross-module
    callers must not open the path themselves — CodeQL does not treat
    helper returns as sanitized across module boundaries.
    """
    import os
    import os.path

    from krellbot import community as kb_community

    safe_id = _safe_pack_id(pack_id)
    install_dir = Path(home) / "packs" / "community"
    fullpath = _confined_json_path(install_dir, safe_id)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(fullpath, flags)
    except FileNotFoundError as exc:
        raise kb_community.IndexError_(f"community pack not installed: {safe_id!r}") from exc
    except OSError as exc:
        raise kb_community.IndexError_(f"community pack unreadable: {safe_id!r}") from exc
    try:
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 65536)
            if not block:
                break
            chunks.append(block)
        raw = b"".join(chunks)
    finally:
        os.close(fd)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise kb_community.IndexError_(f"community pack unreadable: {safe_id!r}") from exc
    if not isinstance(data, dict):
        raise kb_community.IndexError_(f"community pack unreadable: {safe_id!r}")
    embedded = data.get("id")
    if embedded != safe_id:
        raise kb_community.IndexError_(f"community pack not installed: {safe_id!r}")
    return data


def confined_installed_path(home: Path, pack_id: str) -> Path:
    """Return the confined community install path for a sanitized pack id."""
    safe_id = _safe_pack_id(pack_id)
    install_dir = Path(home) / "packs" / "community"
    return Path(_confined_json_path(install_dir, safe_id))


def atomic_install(home: Path, pack_id: str, body: bytes) -> Path:
    """Stage `body` in a temp dir, validate, atomic-rename to install dir.

    The body is first written to a file under a fresh temp directory
    (`tempfile.TemporaryDirectory`). If the body is a parseable tar,
    entries are validated for traversal and symlink escape against the
    staging directory. On any refusal `kb_community.InstallPayloadError`
    is raised and the destination file is not written.

    On success the staged file is moved into
    `<home>/packs/community/<pack_id>.json` with a single `os.replace`,
    which is atomic on POSIX. The mode is `0o600` because the staged
    file is opened with that mode at create time.
    """
    import os.path

    from krellbot import community as kb_community

    pack_id = _safe_pack_id(pack_id)
    if not isinstance(body, (bytes, bytearray)):
        raise kb_community.InstallPayloadError(f"community pack body must be bytes, got {type(body).__name__}")
    if len(body) > MAX_BODY_BYTES:
        raise kb_community.InstallPayloadError(f"community pack body too large: {len(body)} > {MAX_BODY_BYTES}")

    install_dir = Path(home) / "packs" / "community"

    # Identity check first: a non-archive body must already be a JSON object
    # whose id is the requested pack id, before anything is staged or the
    # install directory is created. Tar bodies skip it (`_validate_tar` owns
    # archive qualification).
    is_tar_body = _open_tar(body) is not None
    if not is_tar_body:
        _validate_raw_json_identity(body, pack_id)

    with tempfile.TemporaryDirectory(prefix="krellbot-install-") as staging_root:
        staging_dir = Path(staging_root)
        staged_path = _confined_json_path(staging_dir, pack_id)

        # Write body to the staged file with restrictive perms (0o600).
        # O_BINARY is a no-op on POSIX but matters on Windows so the
        # bytes on disk match the body verbatim.
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
        fd = os.open(staged_path, flags, 0o600)
        try:
            os.write(fd, body)
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            try:
                os.unlink(staged_path)
            except FileNotFoundError:
                pass
            raise
        os.close(fd)

        # Validate as archive if applicable. The staging directory is
        # the reference for traversal and symlink-escape detection, so
        # the extracted/installed tree cannot be reached by a malicious
        # entry name.
        if is_tar_body:
            _validate_tar(body, staging_dir)

        # All checks passed: publish into the install dir with a single
        # atomic rename. A failure before this line leaves the previous
        # installed file (if any) unchanged.
        install_dir.mkdir(parents=True, exist_ok=True)
        destination_path = _confined_json_path(install_dir, pack_id)
        os.replace(staged_path, destination_path)

        # fsync the install directory so the rename is durable across a
        # power loss. POSIX-only; ignored on failure (best effort).
        if hasattr(os, "O_RDONLY"):
            try:
                dir_fd = os.open(str(install_dir), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass

        # Production install path writes the configured sidecar the
        # pack-library classifier expects (installed+ready, not armed).
        # Pass only the basename-sanitized segment so request strings
        # never reach pack-library path joins (CodeQL).
        from krellbot.application import pack_library as pack_library_app

        safe_id = os.path.basename(pack_id)
        try:
            pack_library_app.mark_configured(Path(home), safe_id)
        except pack_library_app.InstallRefused:
            pass

        return Path(destination_path)
