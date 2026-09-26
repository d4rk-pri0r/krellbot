"""Frozen-release archive builder + manifest emitter.

`build_archive` walks a validated PyInstaller one-dir tree, rejects
unsafe members, writes a deterministic zip, computes the SHA-256 over
the bytes that ended up on disk, and returns the immutable manifest
the site installer consumes.

Manifest shape (the site-installer's contract):

    {
        "url":      <str>,   # pinned URL supplied by release automation
        "filename": <str>,   # basename of the archive file
        "size":     <int>,   # bytes on disk
        "os":       <str>,   # one of: linux, macos, windows
        "arch":     <str>,   # one of: x86_64, arm64
        "version":  <str>,   # e.g. "0.9.1"
        "sha256":   <str>,   # 64 lowercase hex chars
    }

Safety guarantees:

* Absolute or traversal member paths are rejected before any bytes
  are written.
* Symlinks that resolve outside the validated dist root are rejected.
* The executable name is platform-dependent: `krellbot` on POSIX,
  `krellbot.exe` on Windows. The Windows case refuses a missing `.exe`.
* `os` / `arch` are validated against a fixed allowlist.
* The `url` is taken verbatim from the caller's parameter; we never
  infer it from a branch tip, a CI ref, or environment state.
* The `url` is required to be non-empty, http(s)://, and its
  basename must equal the archive filename (the site installer
  downloads `manifest['url']` and expects the resulting file to
  match the manifest's `filename`; basename drift opens a class of
  cache-poisoning / wrong-version errors).

Determinism:

* ZIP entries are written with a fixed timestamp (1980-01-01) and
  sorted by member path so two builds with identical inputs produce
  byte-identical archives.
* SHA-256 is computed over `output.read_bytes()` AFTER `zip.close()`,
  so the digest reflects the bytes actually written.
* `size` is `output.stat().st_size` after the write.

POSIX modes:

* Each member's external_attr upper 16 bits are set to the source
  file's st_mode so the archive round-trips 0o755 for executables
  and 0o644 for static assets on POSIX.
* Python's `zipfile.extract` and `unzip` on POSIX do NOT honor
  external_attr by default — the site installer (Task A3) is
  responsible for chmod-ing the extracted `krellbot` member to
  0o755 after a trusted extraction. We record this as a
  documented caveat in the README/installer rather than relying on
  extraction-time mode restoration.
"""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse

# Canonical platform/arch tags. Anything outside these is a typo and
# is refused — the site installer keys off these exact strings.
_OS_TAGS = frozenset({"linux", "macos", "windows"})
_ARCH_TAGS = frozenset({"x86_64", "arm64"})

# Windows uses a .exe suffix; POSIX does not.
_EXE_POSIX = "krellbot"
_EXE_WINDOWS = "krellbot.exe"

# Required payload: a static index.html is what the loopback UI serves.
# Its presence proves the build bundled the static assets at the
# packaged path (not the checkout).
_STATIC_REL = Path("static") / "index.html"

# Fixed ZIP timestamp — gives deterministic zip output for identical
# inputs. PyInstaller-built executables embed their own timestamps, so
# a per-file mtime would not be deterministic anyway; using 1980-01-01
# matches what other deterministic-zip tools do.
_ZIP_DETERMINISTIC_DATE = (1980, 1, 1, 0, 0, 0)

# Buffer size for hashing the archive after writing.
_HASH_CHUNK = 1 << 20  # 1 MiB

# Accepted URL schemes for `manifest['url']`. Anything else is refused
# — the site installer only fetches over http(s).
_URL_SCHEMES = frozenset({"http", "https"})


def _validate_dist(dist: Path, *, os_tag: str) -> None:
    """Raise if `dist` doesn't look like a usable one-dir build.

    Refuses:
      * a missing executable (`krellbot` on POSIX, `krellbot.exe` on Windows)
      * a missing `static/index.html` (bundled UI assets)
      * symlinks whose target resolves outside the validated dist root
      * any member whose path is absolute or contains `..` segments

    PyInstaller 6.x puts runtime code under `_internal/`, so the
    payload layout looks like::

        dist/krellbot/krellbot                 # the launcher executable
        dist/krellbot/_internal/krellbot/...   # Python modules
        dist/krellbot/_internal/krellbot/ui/static/index.html

    Both layouts — payload at the dist root (older PyInstaller) and at
    `_internal/...` (6.x default) — are accepted.
    """
    if not dist.is_dir():
        raise FileNotFoundError(f"dist directory does not exist: {dist}")

    exe_name = _EXE_WINDOWS if os_tag == "windows" else _EXE_POSIX
    exe = dist / exe_name
    if not exe.is_file():
        raise FileNotFoundError(
            f"required executable not found in dist: {exe_name} (os={os_tag})"
        )

    # The static payload must live somewhere under the dist tree. Look
    # at the dist root first, then the `_internal/krellbot/ui/...` layout
    # PyInstaller 6.x produces (the launcher executable is at
    # `dist/krellbot/krellbot`, with bytecode and data under
    # `_internal/krellbot/`).
    candidates = [
        dist / _STATIC_REL,
        dist / "_internal" / "krellbot" / "ui" / _STATIC_REL,
    ]
    if not any(p.is_file() for p in candidates):
        searched = ", ".join(str(p.relative_to(dist)) for p in candidates)
        raise FileNotFoundError(
            f"required payload missing: {_STATIC_REL.as_posix()} "
            f"(looked under: {searched})"
        )

    resolved_dist = dist.resolve()
    for member in dist.rglob("*"):
        # Symlink escape check: a symlink whose resolved target lives
        # outside the dist root can leak arbitrary content into the
        # archive and out at install time. Reject up front.
        if member.is_symlink():
            try:
                target = member.resolve()
            except OSError:
                # A broken symlink — refuse; PyInstaller's one-dir
                # output should not contain dangling links.
                raise ValueError(f"dangling symlink in dist: {member.relative_to(dist)}")
            if not target.exists():
                # `resolve()` can return a non-existent path; treat
                # the same as a broken link for safety.
                raise ValueError(f"dangling symlink in dist: {member.relative_to(dist)}")
            if not target.is_relative_to(resolved_dist):
                raise ValueError(
                    f"escaping symlink: {member.relative_to(dist)} -> {target}"
                )

        # Absolute or traversal paths must never reach the zip member list.
        try:
            relative = member.relative_to(dist)
        except ValueError:
            raise ValueError(f"unsafe archive member (not under dist): {member}")

        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe archive member: {relative}")


def _validate_tags(*, os_tag: str, arch: str) -> None:
    if os_tag not in _OS_TAGS:
        raise ValueError(
            f"unknown os tag {os_tag!r}; expected one of {sorted(_OS_TAGS)}"
        )
    if arch not in _ARCH_TAGS:
        raise ValueError(
            f"unknown arch tag {arch!r}; expected one of {sorted(_ARCH_TAGS)}"
        )


def _validate_url(url: str, *, filename: str) -> None:
    """Refuse a manifest url that is empty, malformed, or basename-mismatched.

    The site installer fetches `manifest['url']` over http(s); anything
    else is a contract violation. The url's basename must equal the
    archive filename so the installer can rely on `manifest['filename']`
    to verify the download — basename drift lets a redirected or
    misconfigured CDN serve the wrong artifact under the right URL.
    """
    if not url or not url.strip():
        raise ValueError(
            "manifest url is empty; release automation must pin a configured release base URL"
        )
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _URL_SCHEMES:
        raise ValueError(
            f"manifest url has invalid scheme {parsed.scheme!r}; expected one of {sorted(_URL_SCHEMES)}"
        )
    if not parsed.netloc:
        raise ValueError(f"manifest url is missing a host: {url!r}")
    url_basename = Path(parsed.path).name
    if url_basename != filename:
        raise ValueError(
            f"manifest url basename {url_basename!r} does not match archive "
            f"filename {filename!r}; refusing"
        )


def _iter_archive_members(dist: Path) -> list[tuple[Path, str]]:
    """Return sorted `(absolute_path, archive_member_name)` pairs.

    The member name is `relative.as_posix()` — already validated to be
    a relative path with no `..` segments by `_validate_dist`.
    """
    members: list[tuple[Path, str]] = []
    for member in sorted(dist.rglob("*"), key=lambda p: p.relative_to(dist).as_posix()):
        if member.is_dir():
            continue
        relative = member.relative_to(dist).as_posix()
        members.append((member, relative))
    return members


def _write_zip(dist: Path, output: Path) -> None:
    """Write a deterministic zip of the dist tree to `output`.

    Uses ZIP_DEFLATED, a fixed timestamp, and sorted entries. Each
    member's external_attr upper 16 bits carry the source file's
    POSIX st_mode so the archive round-trips executable bits (the
    PyInstaller launcher is 0o755; static assets are 0o644). On
    Windows there is no st_mode concept, so the source's high bits
    are masked to a safe default of 0o644 — the site installer
    chmods the extracted `krellbot` member to 0o755 after trusted
    extraction anyway, since Python's `zipfile.extract` does not
    honor external_attr on POSIX.

    Creates `output.parent` if needed. Caller is responsible for
    hashing after.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    # Ensure the destination is absent so we never append to a stale file.
    if output.exists():
        output.unlink()

    is_windows = sys.platform == "win32"

    # Manual entry writing (not writeall) so we control timestamps and modes.
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        allowZip64=False,
    ) as zf:
        for src, member_name in _iter_archive_members(dist):
            data = src.read_bytes()
            info = zipfile.ZipInfo(filename=member_name, date_time=_ZIP_DETERMINISTIC_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            if is_windows:
                # No st_mode on Windows; default to 0o644 for archive
                # members. The .exe marker is preserved by ZipInfo
                # itself, not by external_attr.
                mode = 0o644
            else:
                mode = src.stat().st_mode & 0o7777
            info.external_attr = (mode & 0xFFFF) << 16
            zf.writestr(info, data)


def _sha256_of(path: Path) -> str:
    """Lowercase hex SHA-256 of the file at `path`."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def build_archive(
    dist: Path,
    output: Path,
    *,
    version: str,
    platform_tag: str,
    arch: str,
    url: str,
) -> dict[str, str | int]:
    """Validate, archive, and manifest a frozen release.

    See the module docstring for the manifest shape and safety
    guarantees. Raises before writing anything if validation fails.
    """
    _validate_tags(os_tag=platform_tag, arch=arch)
    _validate_dist(dist, os_tag=platform_tag)
    # Validate url BEFORE we touch the filesystem for any write —
    # refuses empty/invalid/mismatched urls without leaving a
    # half-built archive on disk.
    _validate_url(url, filename=output.name)

    # Manifest url is taken verbatim — release automation pins this and
    # the site installer expects exactly what it was given.
    manifest: dict[str, str | int] = {
        "url": url,
        "filename": output.name,
        "size": 0,  # placeholder; overwritten after the write
        "os": platform_tag,
        "arch": arch,
        "version": version,
        "sha256": "",  # placeholder; overwritten after hashing
    }

    _write_zip(dist, output)

    # Hash the bytes that actually landed on disk, after the zip is closed.
    digest = _sha256_of(output)
    size = output.stat().st_size
    manifest["sha256"] = digest
    manifest["size"] = size

    return manifest


if __name__ == "__main__":  # pragma: no cover
    print(
        "scripts.release_archive is a library; invoke build_archive() from CI",
        file=sys.stderr,
    )
    sys.exit(2)
