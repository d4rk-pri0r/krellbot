"""Built frontend artefacts stay local — no third-party CDN hosts.

Builds the React shell into ``frontend/dist`` if it is missing, then asserts
that the built artefacts carry no third-party CDN *host* references and
contain the exact copy the user-facing shell promises ("Paper workstation").

The CDN guard matches host-like tokens (URL hosts / known CDN hostnames),
not bare substrings inside Vite content-hashes such as ``index-Cdn….css``.

The test runs ``npm ci --include=dev`` plus ``npm run build`` because the
host environment exports ``NODE_ENV=production`` and a plain ``npm ci``
would silently skip devDependencies without the flag.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"

SHELL_PROMISE = "Paper workstation"

# Host-like tokens only — never bare "cdn" / "Cdn" inside a Vite hash.
_FORBIDDEN_HOST_RE = re.compile(
    r"(?:"
    r"(?:https?:)?//[^\s\"'<>]*\bcdn\b"  # URL whose host label contains cdn
    r"|\.cdn\."  # .cdn. inside a hostname
    r"|[\"'=(]\s*//cdn\."  # protocol-relative //cdn.…
    r"|[\"'=(]\s*cdn\."  # quoted/attr cdn.…
    r"|googleapis\.com"
    r"|unpkg\.com"
    r"|jsdelivr\.net"
    r")",
    re.IGNORECASE,
)


def forbidden_host_tokens(text: str) -> list[str]:
    """Return distinct forbidden CDN host tokens found in ``text``."""
    return sorted({match.group(0).strip() for match in _FORBIDDEN_HOST_RE.finditer(text)})


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
    # Locally bundled fonts/images are binary, not UTF-8 source documents.
    files.extend(
        path for path in sorted((dist / "assets").iterdir()) if path.suffix in {".js", ".css", ".html", ".json", ".svg"}
    )
    return files


def test_cdn_matcher_ignores_vite_content_hash() -> None:
    """Bare ``Cdn`` inside a Vite asset hash is not a CDN host reference."""
    assert forbidden_host_tokens('href="/assets/index-CdnAbc123.css"') == []
    assert forbidden_host_tokens("index-CdnXyZ.js") == []
    assert forbidden_host_tokens('const label = "cdn"') == []


def test_cdn_matcher_catches_host_like_tokens() -> None:
    """URL hosts and known CDN hostnames are refused."""
    assert forbidden_host_tokens('src="https://cdn.jsdelivr.net/npm/x"')
    assert forbidden_host_tokens("https://fonts.googleapis.com/css2")
    assert forbidden_host_tokens("https://unpkg.com/react@18")
    assert forbidden_host_tokens('href="//cdn.example.com/lib.js"')
    assert forbidden_host_tokens('src="https://cdn.cloudflare.com/x.js"')


def test_no_cdn_references(built_dist: Path) -> None:
    """The built artefacts must not reference any third-party CDN host."""
    offenders: list[tuple[str, str]] = []
    for path in _iter_built_files(built_dist):
        text = path.read_text(encoding="utf-8")
        for token in forbidden_host_tokens(text):
            offenders.append((path.name, token))
    assert not offenders, f"forbidden host tokens present in build: {offenders}"


def test_shell_promise_text_present(built_dist: Path) -> None:
    """The built bundle must contain the user-facing shell copy."""
    payload = "\n".join(path.read_text(encoding="utf-8") for path in _iter_built_files(built_dist))
    assert SHELL_PROMISE in payload, f"expected {SHELL_PROMISE!r} in built artefacts under {built_dist}"
