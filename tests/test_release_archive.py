"""Tests for scripts/release_archive.py (frozen release archive builder).

The archive builder turns a validated PyInstaller one-dir tree into a
deterministic zip + immutable manifest for the site installer. The
manifest shape is part of the site-installer's contract; the URL is
supplied by release automation and never inferred from a branch tip.

These tests exercise the real builder against tiny fake dist trees
through the public `build_archive` entry point. They do NOT require
PyInstaller or network access: `build_archive` walks an already-built
`dist/` tree and only needs the stdlib zip + hashlib modules.
"""

from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.release_archive import build_archive  # type: ignore[import-not-found]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_EXE_NAME = "krellbot"
_WINDOWS_EXE_NAME = "krellbot.exe"


def _fake_dist_one_dir(dist: Path, *, exe_bytes: bytes = b"fake executable") -> None:
    """Create a tiny one-dir tree mirroring a PyInstaller layout."""
    dist.mkdir(parents=True, exist_ok=True)
    (dist / _EXE_NAME).write_bytes(exe_bytes)
    static = dist / "static"
    static.mkdir()
    (static / "index.html").write_text("local", encoding="utf-8")


# ---------- happy path ----------


def test_manifest_includes_digest_and_platform(tmp_path):
    """The manifest carries os/arch/version/size/sha256/filename/url."""
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    out = tmp_path / "out.zip"
    url = "https://example.com/out.zip"

    result = build_archive(
        dist,
        out,
        version="0.9.1",
        platform_tag="linux",
        arch="x86_64",
        url=url,
    )

    assert result["os"] == "linux"
    assert result["arch"] == "x86_64"
    assert result["version"] == "0.9.1"
    assert result["url"] == url
    assert result["filename"] == out.name
    assert _SHA256_RE.match(result["sha256"])
    assert result["size"] == out.stat().st_size
    assert result["size"] > 0


def test_zip_is_deterministic_and_size_matches(tmp_path):
    """Same inputs produce the same SHA-256 across runs; size matches on disk."""
    dist_a = tmp_path / "dist_a"
    _fake_dist_one_dir(dist_a, exe_bytes=b"deterministic bytes")
    out_a = tmp_path / "out_a.zip"

    dist_b = tmp_path / "dist_b"
    _fake_dist_one_dir(dist_b, exe_bytes=b"deterministic bytes")
    out_b = tmp_path / "out_b.zip"

    base = {
        "version": "0.9.1",
        "platform_tag": "macos",
        "arch": "arm64",
    }
    res_a = build_archive(dist_a, out_a, url="https://example.com/out_a.zip", **base)
    res_b = build_archive(dist_b, out_b, url="https://example.com/out_b.zip", **base)

    # Deterministic: identical inputs give identical SHA-256.
    assert res_a["sha256"] == res_b["sha256"]
    # Hash matches the bytes that ended up on disk.
    assert hashlib.sha256(out_a.read_bytes()).hexdigest() == res_a["sha256"]
    assert hashlib.sha256(out_b.read_bytes()).hexdigest() == res_b["sha256"]


def test_zip_contains_payload(tmp_path):
    """The zip embeds the payload tree with deterministic member names."""
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    out = tmp_path / "out.zip"
    build_archive(
        dist,
        out,
        version="0.9.1",
        platform_tag="linux",
        arch="x86_64",
        url="https://example.com/out.zip",
    )

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert f"{_EXE_NAME}" in names
    assert "static/index.html" in names


def test_returned_manifest_shape(tmp_path):
    """Sidecar manifest dict carries every key the site installer reads."""
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    # Windows requires the .exe suffix.
    (dist / _WINDOWS_EXE_NAME).write_bytes(b"x")
    out = tmp_path / "out.zip"
    result = build_archive(
        dist,
        out,
        version="0.9.1",
        platform_tag="windows",
        arch="x86_64",
        url="https://example.com/out.zip",
    )
    expected_keys = {"url", "filename", "size", "os", "arch", "version", "sha256"}
    assert expected_keys.issubset(result.keys())
    assert result["os"] == "windows"
    assert result["arch"] == "x86_64"
    assert result["version"] == "0.9.1"
    assert isinstance(result["url"], str) and result["url"].endswith("out.zip")
    assert isinstance(result["size"], int) and result["size"] > 0


# ---------- dist validation: required structure ----------


def test_missing_executable_is_refused(tmp_path):
    """A dist tree without the `krellbot` executable is refused."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "static").mkdir()
    (dist / "static" / "index.html").write_text("local", encoding="utf-8")
    out = tmp_path / "out.zip"
    with pytest.raises((FileNotFoundError, ValueError)):
        build_archive(
            dist,
            out,
            version="0.9.1",
            platform_tag="linux",
            arch="x86_64",
            url="https://example.com/out.zip",
        )
    assert not out.exists(), "no archive should be written when the dist is invalid"


def test_missing_static_index_is_refused(tmp_path):
    """A dist tree without static/index.html is refused."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / _EXE_NAME).write_bytes(b"x")
    out = tmp_path / "out.zip"
    with pytest.raises((FileNotFoundError, ValueError)):
        build_archive(
            dist,
            out,
            version="0.9.1",
            platform_tag="linux",
            arch="x86_64",
            url="https://example.com/out.zip",
        )


# ---------- platform / arch allowlist ----------


def test_unknown_os_is_refused(tmp_path):
    """os values outside the canonical set are refused."""
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    out = tmp_path / "out.zip"
    with pytest.raises(ValueError):
        build_archive(
            dist,
            out,
            version="0.9.1",
            platform_tag="darwin",  # canonical is "macos", not "darwin"
            arch="x86_64",
            url="https://example.com/out.zip",
        )


def test_canonical_os_tags_are_accepted(tmp_path):
    """linux / macos / windows all work."""
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    for os_tag in ("linux", "macos", "windows"):
        out = tmp_path / f"out_{os_tag}.zip"
        # For windows we need the .exe name in the dist tree.
        if os_tag == "windows":
            (dist / _WINDOWS_EXE_NAME).write_bytes(b"x")
        build_archive(
            dist,
            out,
            version="0.9.1",
            platform_tag=os_tag,
            arch="x86_64",
            url=f"https://example.com/out_{os_tag}.zip",
        )
        assert out.exists()


@pytest.mark.parametrize("arch", ["x86", "i386", "amd64", "riscv64"])
def test_unknown_arch_is_refused(tmp_path, arch):
    """arch values outside the canonical set are refused."""
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    out = tmp_path / "out.zip"
    with pytest.raises(ValueError):
        build_archive(
            dist,
            out,
            version="0.9.1",
            platform_tag="linux",
            arch=arch,
            url="https://example.com/out.zip",
        )


def test_windows_requires_dotexe_executable(tmp_path):
    """A Windows dist without `krellbot.exe` is refused."""
    dist = tmp_path / "dist"
    dist.mkdir()
    # Only the non-suffixed executable exists.
    (dist / _EXE_NAME).write_bytes(b"x")
    (dist / "static").mkdir()
    (dist / "static" / "index.html").write_text("local", encoding="utf-8")
    out = tmp_path / "out.zip"
    with pytest.raises((FileNotFoundError, ValueError)):
        build_archive(
            dist,
            out,
            version="0.9.1",
            platform_tag="windows",
            arch="x86_64",
            url="https://example.com/out.zip",
        )


def test_windows_accepts_dotexe_executable(tmp_path):
    """A Windows dist with `krellbot.exe` is accepted."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / _WINDOWS_EXE_NAME).write_bytes(b"x")
    (dist / "static").mkdir()
    (dist / "static" / "index.html").write_text("local", encoding="utf-8")
    out = tmp_path / "out.zip"
    result = build_archive(
        dist,
        out,
        version="0.9.1",
        platform_tag="windows",
        arch="x86_64",
        url="https://example.com/out.zip",
    )
    assert result["os"] == "windows"


# ---------- path safety: no absolute, no traversal, no escaping symlinks ----------


def test_escaping_symlink_is_refused(tmp_path):
    """A symlink that resolves outside the dist root is rejected."""
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = dist / "static" / "leak.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unsupported on this fs: {exc}")

    out = tmp_path / "out.zip"
    with pytest.raises(ValueError):
        build_archive(
            dist,
            out,
            version="0.9.1",
            platform_tag="linux",
            arch="x86_64",
            url="https://example.com/out.zip",
        )


def test_dangling_symlink_is_refused(tmp_path):
    """A dangling symlink is refused."""
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    link = dist / "static" / "dangling.txt"
    try:
        link.symlink_to(dist / "static" / "does-not-exist.txt")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unsupported on this fs: {exc}")

    out = tmp_path / "out.zip"
    with pytest.raises(ValueError):
        build_archive(
            dist,
            out,
            version="0.9.1",
            platform_tag="linux",
            arch="x86_64",
            url="https://example.com/out.zip",
        )


# ---------- url handling ----------


def test_url_is_taken_verbatim_from_parameter(tmp_path):
    """The url parameter is the canonical URL; the manifest echoes it as-is."""
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    out = tmp_path / "out.zip"
    url = "https://cdn.example.com/krellbot/0.9.1/out.zip?dl=1"
    result = build_archive(
        dist,
        out,
        version="0.9.1",
        platform_tag="linux",
        arch="x86_64",
        url=url,
    )
    assert result["url"] == url


# ---------- output file naming ----------


def test_filename_field_equals_output_basename(tmp_path):
    """manifest['filename'] is the basename of the output archive."""
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    out = tmp_path / "krellbot-0.9.1-linux-x86_64.zip"
    result = build_archive(
        dist,
        out,
        version="0.9.1",
        platform_tag="linux",
        arch="x86_64",
        url="https://example.com/krellbot-0.9.1-linux-x86_64.zip",
    )
    assert result["filename"] == "krellbot-0.9.1-linux-x86_64.zip"


# ---------- POSIX executable mode preservation ----------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX external_attr is masked to 0o644 on Windows")
def test_posix_executable_mode_preserved_in_zip(tmp_path):
    """A 0o755 fake executable round-trips through the zip as 0o755 on POSIX.

    PyInstaller 6.x produces a launcher executable on POSIX with mode
    0o755. The archive must preserve that mode (top 16 bits of
    `external_attr` carry the unix mode). Without preservation, the
    extracted `krellbot` member is non-executable and the site installer
    has to chmod it after extraction.

    On Windows there is no st_mode, so `release_archive._write_zip`
    deliberately masks every member to 0o644 (the .exe marker is kept
    by ZipInfo itself, not by external_attr). The site installer chmods
    the extracted `krellbot.exe` after trusted extraction. POSIX
    coverage is preserved here; Windows-mode masking is covered by
    `test_windows_archive_masks_modes_to_0o644` below.
    """
    import stat
    import zipfile

    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    exe = dist / _EXE_NAME
    exe.chmod(0o755)
    # Sanity: the fake dist's executable is actually 0o755 on disk.
    assert stat.S_IMODE(exe.stat().st_mode) == 0o755

    out = tmp_path / "out.zip"
    build_archive(
        dist,
        out,
        version="0.9.1",
        platform_tag="linux",
        arch="x86_64",
        url="https://example.com/out.zip",
    )

    with zipfile.ZipFile(out) as zf:
        info = zf.getinfo(_EXE_NAME)
        # Top 16 bits of external_attr hold the unix mode.
        mode = (info.external_attr >> 16) & 0o7777
    assert mode == 0o755, f"expected 0o755, got {oct(mode)}; external_attr=0x{info.external_attr:x}"


def test_static_member_is_not_executable_in_zip(tmp_path):
    """A bundled static asset does NOT inherit 0o755 by accident."""
    import zipfile

    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    # Make the executable correct.
    (dist / _EXE_NAME).chmod(0o755)
    # Static file is world-readable but not executable.
    (dist / "static" / "index.html").chmod(0o644)

    out = tmp_path / "out.zip"
    build_archive(
        dist,
        out,
        version="0.9.1",
        platform_tag="linux",
        arch="x86_64",
        url="https://example.com/out.zip",
    )

    with zipfile.ZipFile(out) as zf:
        mode = (zf.getinfo("static/index.html").external_attr >> 16) & 0o7777
    assert mode == 0o644, f"static asset should not be executable; got {oct(mode)}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific external_attr contract")
def test_windows_archive_masks_modes_to_0o644(tmp_path):
    """On Windows, ``release_archive._write_zip`` deliberately masks every
    member's external_attr upper 16 bits to 0o644 (the platform has no
    st_mode concept for archive members; the .exe marker is preserved
    by ZipInfo itself, not by external_attr). The site installer is
    responsible for chmod-ing the extracted ``krellbot.exe`` after a
    trusted extraction.

    This pins the actual Windows contract so a future change that
    leaks the host st_mode into the archive would fail loudly on a
    Windows runner. POSIX coverage stays in
    ``test_posix_executable_mode_preserved_in_zip``.
    """
    import zipfile

    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    (dist / _WINDOWS_EXE_NAME).write_bytes(b"x")

    out = tmp_path / "out.zip"
    build_archive(
        dist,
        out,
        version="0.9.1",
        platform_tag="windows",
        arch="x86_64",
        url="https://example.com/out.zip",
    )

    with zipfile.ZipFile(out) as zf:
        for name in zf.namelist():
            mode = (zf.getinfo(name).external_attr >> 16) & 0o7777
            assert mode == 0o644, f"Windows archive member {name!r} must have external_attr mode 0o644, got {oct(mode)}"


# ---------- url validation (fails closed) ----------


def test_empty_url_is_refused(tmp_path):
    """An empty url is refused; no archive is written."""
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    out = tmp_path / "out.zip"
    with pytest.raises(ValueError):
        build_archive(
            dist,
            out,
            version="0.9.1",
            platform_tag="linux",
            arch="x86_64",
            url="",
        )
    assert not out.exists()


def test_whitespace_url_is_refused(tmp_path):
    """Whitespace-only url is refused; no archive is written."""
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    out = tmp_path / "out.zip"
    with pytest.raises(ValueError):
        build_archive(
            dist,
            out,
            version="0.9.1",
            platform_tag="linux",
            arch="x86_64",
            url="   ",
        )
    assert not out.exists()


def test_invalid_url_scheme_is_refused(tmp_path):
    """A url without http(s) scheme is refused; no archive is written."""
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    out = tmp_path / "out.zip"
    with pytest.raises(ValueError):
        build_archive(
            dist,
            out,
            version="0.9.1",
            platform_tag="linux",
            arch="x86_64",
            url="not-a-url/releases/0.9.1/linux-x86_64.zip",
        )
    assert not out.exists()


def test_url_basename_must_equal_archive_filename(tmp_path):
    """A url whose basename differs from the archive filename is refused.

    The site installer downloads `manifest['url']` and expects the
    resulting Content-Disposition / final filename to match the archive
    filename the manifest was built for. Allowing basename drift opens
    a class of cache-poisoning / wrong-version errors.
    """
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    out = tmp_path / "krellbot-linux-x86_64.zip"
    # The url's basename is wrong — should be `krellbot-linux-x86_64.zip`.
    with pytest.raises(ValueError):
        build_archive(
            dist,
            out,
            version="0.9.1",
            platform_tag="linux",
            arch="x86_64",
            url="https://example.com/releases/0.9.1/something-else.zip",
        )
    assert not out.exists()


def test_url_basename_with_query_string_still_must_match(tmp_path):
    """Even a url with a query string must end with the archive filename."""
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    out = tmp_path / "krellbot-linux-x86_64.zip"
    # Trailing slash + correct basename + query string is OK.
    result = build_archive(
        dist,
        out,
        version="0.9.1",
        platform_tag="linux",
        arch="x86_64",
        url="https://cdn.example.com/krellbot/0.9.1/krellbot-linux-x86_64.zip?dl=1",
    )
    assert result["filename"] == "krellbot-linux-x86_64.zip"
