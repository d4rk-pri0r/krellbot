"""macOS Krellbot.app wrap + app-archive manifest pins."""

from __future__ import annotations

import plistlib
import zipfile
from pathlib import Path

from scripts.macos_app_bundle import build_app_bundle
from scripts.release_archive import build_macos_app_archive


def _fake_onedir(dist: Path) -> None:
    dist.mkdir(parents=True)
    exe = dist / "krellbot"
    exe.write_bytes(b"\x00fake-mach-o")
    exe.chmod(0o755)
    (dist / "install-krellbot.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    schema = dist / "_internal" / "krellbot" / "pack" / "schema.json"
    schema.parent.mkdir(parents=True)
    schema.write_text('{"type":"object"}', encoding="utf-8")
    shell = dist / "_internal" / "frontend" / "dist" / "index.html"
    shell.parent.mkdir(parents=True)
    shell.write_text("<html></html>", encoding="utf-8")


def test_build_app_bundle_embeds_onedir_under_macos(tmp_path: Path) -> None:
    onedir = tmp_path / "krellbot"
    _fake_onedir(onedir)
    app = tmp_path / "Krellbot.app"

    build_app_bundle(onedir, app, version="0.9.7")

    assert (app / "Contents" / "MacOS" / "krellbot").is_file()
    assert (app / "Contents" / "MacOS" / "_internal" / "krellbot" / "pack" / "schema.json").is_file()
    assert not (app / "Contents" / "MacOS" / "install-krellbot.sh").exists()
    with (app / "Contents" / "Info.plist").open("rb") as fh:
        info = plistlib.load(fh)
    assert info["CFBundleExecutable"] == "krellbot"
    assert info["CFBundleIdentifier"] == "dev.krellbot.workstation"
    assert info["CFBundleShortVersionString"] == "0.9.7"
    assert info["LSMinimumSystemVersion"] == "12.0"


def test_build_macos_app_archive_roots_zip_at_app(tmp_path: Path) -> None:
    onedir = tmp_path / "krellbot"
    _fake_onedir(onedir)
    app = tmp_path / "Krellbot.app"
    build_app_bundle(onedir, app, version="v0.9.7")
    out = tmp_path / "krellbot-macos-arm64.zip"

    manifest = build_macos_app_archive(
        app,
        out,
        version="v0.9.7",
        arch="arm64",
        url="https://example.com/v0.9.7/krellbot-macos-arm64.zip",
    )

    assert manifest["os"] == "macos"
    assert manifest["arch"] == "arm64"
    assert manifest["filename"] == out.name
    assert len(manifest["sha256"]) == 64
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "Krellbot.app/Contents/MacOS/krellbot" in names
    assert "Krellbot.app/Contents/Info.plist" in names
    assert not any(n.startswith("krellbot/") for n in names)
