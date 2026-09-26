"""Build a PyInstaller one-dir frozen binary for the krellbot release.

This script is invoked by release CI on each of macOS / Windows / Linux.
It produces a one-dir tree (PyInstaller's default for `--onedir`) at
`<repo>/dist/krellbot/` containing the executable plus the bundled
runtime, static UI assets, and keyring backends. The companion script
`scripts/release_archive.py` then zips that tree into an immutable
release archive with a manifest.

This script does NOT claim code signing, does NOT upload anything, and
does NOT publish or push. CI is responsible for uploading the archive
and manifest as workflow artifacts.

Why one-dir (not one-file)?

* The static UI assets ship as ordinary files inside the directory;
  `krellbot.ui.server` reads them with `Path(__file__).parent / "static"`,
  which resolves inside the bundle at runtime.
* keyring backend discovery (`--collect-all keyring`) drops platform
  backends alongside the binary, so the user agent can resolve them.
* Build is faster and reproducible; the directory layout is what
  PyInstaller itself recommends for "real" installers.

Why a dedicated `scripts/frozen_main.py`?

* Avoids any reliance on `krellbot/__main__.py` shenanigans, which would
  couple the frozen build to internal packaging choices.
* Gives the entry point a single, unambiguous symbol
  (`from krellbot.cli import entry`).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# PyInstaller splits add-data args on the OS path separator. On POSIX
# this is `:`; on Windows it is `;`. Hard-coding the wrong one will
# silently split on the wrong character (Windows sees `:` in URLs, for
# instance) and produce a broken bundle.
_SEP = ";" if sys.platform == "win32" else ":"


def _build_args(*, entry: Path, dist_root: Path, work_root: Path, spec_root: Path, repo_root: Path) -> list[str]:
    """Assemble the PyInstaller CLI args for our one-dir build."""
    static_src = (repo_root / "src" / "krellbot" / "ui" / "static").resolve()
    static_dest = Path("krellbot") / "ui" / "static"

    args: list[str] = [
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name", "krellbot",
        # Where PyInstaller writes the bundle.
        "--distpath", str(dist_root.resolve()),
        # Build scratch (hashed, regenerable; safe to delete).
        "--workpath", str(work_root.resolve()),
        # Spec files: don't litter the repo with .spec outputs.
        "--specpath", str(spec_root.resolve()),
        # Static UI assets — same path inside the bundle as in the
        # source tree so `krellbot.ui.server._STATIC_DIR` resolves at
        # runtime to the bundled copy, not the checkout. Absolute source
        # path so PyInstaller resolves it regardless of cwd/specpath.
        "--add-data", f"{static_src}{_SEP}{static_dest}",
        # keyring backend discovery: copies every backend's Python files
        # and metadata into the bundle so any platform's keyring works.
        "--collect-all", "keyring",
        # The runtime imports these explicitly; collect their submodules
        # so PyInstaller's static analysis can't strip them.
        "--collect-submodules", "cryptography",
        "--collect-submodules", "jsonschema",
        # Hidden imports that PyInstaller's static analysis misses.
        "--hidden-import", "cryptography",
        "--hidden-import", "jsonschema",
        # `krellbot.cli` imports krellbot.ui.* lazily inside the `ui`
        # subcommand; PyInstaller's static analysis can't trace that,
        # so force them in.
        "--hidden-import", "krellbot.ui.server",
        "--hidden-import", "krellbot.ui.launch",
        # The frozen entry point.
        str(entry.resolve()),
    ]
    return args


def _pyinstaller() -> str:
    """Return the path to the pyinstaller executable, or raise."""
    exe = shutil.which("pyinstaller")
    if exe is None:
        # Fall back to `python -m PyInstaller` so the build still works
        # in environments that don't have pyinstaller on PATH (e.g. uv
        # venvs). The dev group pins pyinstaller so this is reliable.
        return sys.executable
    return exe


def _invoke_pyinstaller(args: list[str]) -> int:
    """Invoke pyinstaller with the given args. Returns the exit code."""
    pyi = _pyinstaller()
    if pyi == sys.executable:
        cmd = [sys.executable, "-m", "PyInstaller", *args]
    else:
        cmd = [pyi, *args]
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def _resolve_paths(repo_root: Path) -> tuple[Path, Path, Path, Path]:
    """Return (entry, dist_root, work_root, spec_root) for the build."""
    entry = repo_root / "scripts" / "frozen_main.py"
    dist_root = repo_root / "dist"
    work_root = repo_root / "build" / "pyinstaller"
    spec_root = repo_root / "build" / "spec"
    return entry, dist_root, work_root, spec_root


def freeze(*, repo_root: Path | None = None) -> Path:
    """Build the frozen one-dir tree at `repo_root / dist / krellbot`.

    Returns the path to the bundle directory (ready for
    `scripts.release_archive.build_archive` to validate and zip).
    Raises SystemExit if pyinstaller fails or the bundle is missing.
    """
    repo_root = repo_root or Path(__file__).resolve().parents[1]
    entry, dist_root, work_root, spec_root = _resolve_paths(repo_root)

    if not entry.is_file():
        raise SystemExit(f"entry script not found: {entry}")

    # Clean previous build artifacts so the run is reproducible.
    for stale in (dist_root, work_root, spec_root):
        if stale.exists():
            shutil.rmtree(stale)

    args = _build_args(
        entry=entry,
        dist_root=dist_root,
        work_root=work_root,
        spec_root=spec_root,
        repo_root=repo_root,
    )

    rc = _invoke_pyinstaller(args)
    if rc != 0:
        raise SystemExit(f"pyinstaller exited with code {rc}")

    # PyInstaller names the bundle after `--name`. On POSIX it's
    # `dist/krellbot/`; on Windows it's `dist/krellbot/`. Both are
    # directories because we used --onedir.
    bundle = dist_root / "krellbot"
    if not bundle.is_dir():
        raise SystemExit(f"expected bundle directory not found: {bundle}")

    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a PyInstaller one-dir frozen krellbot binary."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="path to the krellbot source checkout (default: parent of this script)",
    )
    args = parser.parse_args(argv)

    bundle = freeze(repo_root=args.repo_root)
    print(f"built: {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
