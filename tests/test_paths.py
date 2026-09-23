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
