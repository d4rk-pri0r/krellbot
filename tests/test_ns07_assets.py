"""NS07a — local frontend toolchain build evidence.

Builds the React shell into ``frontend/dist`` if it is missing, then asserts
that the built artefacts carry no third-party CDN references and contain the
exact copy the user-facing shell promises ("Paper workstation").

The test runs ``npm ci --include=dev`` plus ``npm run build`` because the
host environment exports ``NODE_ENV=production`` and the brief's plain
``npm ci`` would silently skip devDependencies without the flag.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"

FORBIDDEN_HOSTS = ("cdn", "googleapis", "unpkg", "jsdelivr")
SHELL_PROMISE = "Paper workstation"


def _resolve_npm() -> str:
    """Return the npm executable to invoke.

    Honours ``KB_NPM`` when set, otherwise falls back to the first ``npm``
    on ``PATH``. Tests intentionally do not vendor a Node binary; the host
    toolchain is the gate.
    """
    override = os.environ.get("KB_NPM")
    if override:
        return override
    found = shutil.which("npm")
    if not found:
        pytest.skip("npm is not available on PATH")
    return found


def _run_npm(args: list[str]) -> None:
    """Run npm with the dev-include flag so NODE_ENV=production does not
    silently drop devDependencies."""
    npm = _resolve_npm()
    env = os.environ.copy()
    env.setdefault("NODE_ENV", "development")
    completed = subprocess.run(
        [npm, "--prefix", str(FRONTEND_DIR), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=300,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        pytest.fail(f"npm {' '.join(args)} failed with {completed.returncode}")


@pytest.fixture(scope="module")
def built_dist() -> Path:
    """Build the frontend shell if the dist artefacts are not already present."""
    if DIST_DIR.is_dir() and any(DIST_DIR.iterdir()):
        return DIST_DIR
    if not FRONTEND_DIR.is_dir():
        pytest.skip(f"frontend/ directory missing at {FRONTEND_DIR}")
    _run_npm(["ci", "--include=dev"])
    _run_npm(["run", "build"])
    if not DIST_DIR.is_dir():
        pytest.fail("vite build did not produce frontend/dist")
    return DIST_DIR


def _iter_built_files(dist: Path) -> list[Path]:
    files: list[Path] = [dist / "index.html"]
    files.extend(sorted((dist / "assets").iterdir()))
    return files


def test_no_cdn_references(built_dist: Path) -> None:
    """The built artefacts must not reference any third-party CDN host."""
    offenders: list[tuple[str, str]] = []
    for path in _iter_built_files(built_dist):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for host in FORBIDDEN_HOSTS:
            if host in lowered:
                offenders.append((path.name, host))
    assert not offenders, f"forbidden host tokens present in build: {offenders}"


def test_shell_promise_text_present(built_dist: Path) -> None:
    """The built bundle must contain the user-facing shell copy."""
    payload = "\n".join(path.read_text(encoding="utf-8") for path in _iter_built_files(built_dist))
    assert SHELL_PROMISE in payload, f"expected {SHELL_PROMISE!r} in built artefacts under {built_dist}"
