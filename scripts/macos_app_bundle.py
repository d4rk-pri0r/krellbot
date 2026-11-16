"""Wrap a PyInstaller one-dir tree into a notarizable Krellbot.app.

Layout produced::

    Krellbot.app/
      Contents/
        Info.plist
        MacOS/
          krellbot          # main executable (CFBundleExecutable)
          _internal/        # PyInstaller runtime (copied from onedir)
          …                 # any other one-dir members except installer helpers

Installer helpers (``install-krellbot.sh``, Windows installers, INSTALL.txt)
stay outside the ``.app``; signed macOS release zips ship the stapled app
as the payload. See ``docs/signing.md`` for the krellbot-cloud layout caveat.

This module does not invoke codesign or notarytool.
"""

from __future__ import annotations

import argparse
import plistlib
import shutil
from pathlib import Path

DEFAULT_BUNDLE_ID = "dev.krellbot.workstation"
DEFAULT_BUNDLE_NAME = "Krellbot"
DEFAULT_MIN_SYSTEM = "12.0"

# Keep these next to the one-dir for unsigned Linux/Windows archives; do not
# bury Linux/Windows installers inside the macOS app bundle.
_SKIP_APP_MEMBERS = frozenset(
    {
        "Install-Krellbot.cmd",
        "Install-Krellbot.ps1",
        "install-krellbot.sh",
        "INSTALL.txt",
    }
)


def build_app_bundle(
    onedir: Path,
    app_path: Path,
    *,
    version: str,
    bundle_identifier: str = DEFAULT_BUNDLE_ID,
    bundle_name: str = DEFAULT_BUNDLE_NAME,
    minimum_system_version: str = DEFAULT_MIN_SYSTEM,
) -> Path:
    """Create ``app_path`` (a ``*.app`` bundle) from a frozen one-dir tree.

    ``onedir`` must contain the ``krellbot`` executable. Existing ``app_path``
    is removed. Returns ``app_path``.
    """

    onedir = onedir.resolve()
    app_path = app_path.resolve()
    exe = onedir / "krellbot"
    if not exe.is_file():
        raise FileNotFoundError(f"one-dir missing krellbot executable: {exe}")

    if app_path.exists():
        shutil.rmtree(app_path)

    macos_dir = app_path / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)

    for child in sorted(onedir.iterdir()):
        if child.name in _SKIP_APP_MEMBERS:
            continue
        dest = macos_dir / child.name
        if child.is_dir():
            shutil.copytree(child, dest, symlinks=False)
        else:
            shutil.copy2(child, dest)

    info = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": "krellbot",
        "CFBundleIdentifier": bundle_identifier,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": bundle_name,
        "CFBundleDisplayName": bundle_name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version.lstrip("v"),
        "CFBundleVersion": version.lstrip("v"),
        "CFBundleSignature": "????",
        "LSMinimumSystemVersion": minimum_system_version,
        "LSUIElement": False,
        "NSHighResolutionCapable": True,
    }
    with (app_path / "Contents" / "Info.plist").open("wb") as fh:
        plistlib.dump(info, fh, sort_keys=False)

    bundled_exe = macos_dir / "krellbot"
    if not bundled_exe.is_file():
        raise FileNotFoundError(f"app bundle missing MacOS/krellbot: {bundled_exe}")
    bundled_exe.chmod(bundled_exe.stat().st_mode | 0o111)
    return app_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--onedir",
        type=Path,
        default=Path("dist/krellbot"),
        help="PyInstaller one-dir tree (default: dist/krellbot)",
    )
    parser.add_argument(
        "--app",
        type=Path,
        default=Path("dist/Krellbot.app"),
        help="output .app path (default: dist/Krellbot.app)",
    )
    parser.add_argument("--version", required=True, help="CFBundleShortVersionString")
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    args = parser.parse_args(argv)
    app = build_app_bundle(
        args.onedir,
        args.app,
        version=args.version,
        bundle_identifier=args.bundle_id,
    )
    print(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
