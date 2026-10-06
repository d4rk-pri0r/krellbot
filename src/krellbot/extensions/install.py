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
    different-pack content under a trusted name.

Any refusal raises `kb_community.InstallPayloadError` *before* any
`os.replace` to the destination, so a previous install file (if any) is
left unchanged. On success the staged file is renamed into
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

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise kb_community.InstallPayloadError(
            f"community pack body is not valid UTF-8: {exc}"
        ) from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise kb_community.InstallPayloadError(f"community pack body is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise kb_community.InstallPayloadError(
            f"community pack body must be a JSON object, got {type(data).__name__}"
        )

    embedded_id = data.get("id")
    if embedded_id != pack_id:
        raise kb_community.InstallPayloadError(
            f"community pack body id {embedded_id!r} does not match requested pack id {pack_id!r}"
        )


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
    from krellbot import community as kb_community

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
        staged_file = staging_dir / f"{pack_id}.json"

        # Write body to the staged file with restrictive perms (0o600).
        # O_BINARY is a no-op on POSIX but matters on Windows so the
        # bytes on disk match the body verbatim.
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
        fd = os.open(str(staged_file), flags, 0o600)
        try:
            os.write(fd, body)
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            try:
                os.unlink(staged_file)
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
        destination = install_dir / f"{pack_id}.json"
        os.replace(staged_file, destination)

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

        return destination
