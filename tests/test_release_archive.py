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
    url = "https://example.com/releases/0.9.1/linux-x86_64.zip"

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

    common = {
        "version": "0.9.1",
        "platform_tag": "macos",
        "arch": "arm64",
        "url": "https://example.com/releases/0.9.1/macos-arm64.zip",
    }
    res_a = build_archive(dist_a, out_a, **common)
    res_b = build_archive(dist_b, out_b, **common)

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
        url="https://example.com/x.zip",
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
        url="https://example.com/releases/0.9.1/windows-x86_64.zip",
    )
    expected_keys = {"url", "filename", "size", "os", "arch", "version", "sha256"}
    assert expected_keys.issubset(result.keys())
    assert result["os"] == "windows"
    assert result["arch"] == "x86_64"
    assert result["version"] == "0.9.1"
    assert isinstance(result["url"], str) and result["url"].endswith("windows-x86_64.zip")
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
            url="https://example.com/x.zip",
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
            url="https://example.com/x.zip",
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
            url="https://example.com/x.zip",
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
            url=f"https://example.com/{os_tag}.zip",
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
            url="https://example.com/x.zip",
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
            url="https://example.com/x.zip",
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
        url="https://example.com/x.zip",
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
            url="https://example.com/x.zip",
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
            url="https://example.com/x.zip",
        )


# ---------- url handling ----------


def test_url_is_taken_verbatim_from_parameter(tmp_path):
    """The url parameter is the canonical URL; the manifest echoes it as-is."""
    dist = tmp_path / "dist"
    _fake_dist_one_dir(dist)
    out = tmp_path / "out.zip"
    url = "https://cdn.example.com/krellbot/0.9.1/linux-x86_64.zip?dl=1"
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
        url="https://example.com/x.zip",
    )
    assert result["filename"] == "krellbot-0.9.1-linux-x86_64.zip"
