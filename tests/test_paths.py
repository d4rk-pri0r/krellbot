"""Durable filesystem layout and atomic writes for krellbot."""

import os
import sys

import pytest


def test_atomic_write_survives_crash_between_write_and_replace(monkeypatch, tmp_path):
    """If os.replace fails, the original file must stay intact and no .tmp remains."""
    from krellbot import paths

    target = tmp_path / "config.json"
    original = b"ORIGINAL_BYTES"
    target.write_bytes(original)

    real_replace = os.replace

    def boom(src, dst):
        raise OSError("simulated crash between write and replace")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        paths.atomic_write(target, b"NEW")

    assert target.read_bytes() == original
    tmp_sibling = target.with_name(target.name + ".tmp")
    assert not tmp_sibling.exists()

    absent = tmp_path / "absent.json"
    with pytest.raises(OSError):
        paths.atomic_write(absent, b"NEW")
    assert not absent.exists()
    assert not absent.with_name(absent.name + ".tmp").exists()

    # Restore os.replace so monkeypatch teardown is clean.
    monkeypatch.setattr(os, "replace", real_replace)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_home_dir_mode_0700(tmp_path, monkeypatch):
    """ensure_layout must create directories with mode 0o700 on POSIX."""
    from krellbot import paths

    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    home = paths.ensure_layout()
    for child in home.iterdir():
        if child.is_dir():
            assert child.stat().st_mode & 0o777 == 0o700, child
    # The home dir itself too.
    assert home.stat().st_mode & 0o777 == 0o700


def test_atomic_write_opens_in_binary_mode(tmp_path, monkeypatch):
    """On Windows os.open defaults to text mode and os.write turns \\n into \\r\\n.

    atomic_write must pass os.O_BINARY when the platform defines it, so the bytes
    on disk are exactly the bytes the caller hashed (cache manifests, key files).
    Simulated here: pretend O_BINARY exists and check it reaches os.open.
    """
    from krellbot import paths as kb_paths

    # Real flag on Windows; a fake bit elsewhere (stripped before the real open).
    binary = getattr(os, "O_BINARY", 0)
    strip = 0
    if not binary:
        binary = strip = 0x40000000
        monkeypatch.setattr(os, "O_BINARY", binary, raising=False)
    real_open = os.open
    seen: list[int] = []

    def spy_open(path, flags, *args, **kwargs):
        seen.append(flags)
        return real_open(path, flags & ~strip, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy_open)
    target = tmp_path / "out.csv"
    kb_paths.atomic_write(target, b"a\nb\n")
    assert seen and seen[0] & binary, "atomic_write must request O_BINARY"
    assert target.read_bytes() == b"a\nb\n"
