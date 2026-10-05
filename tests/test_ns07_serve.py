"""NS07c — serve the built frontend shell from the loopback API.

Tests-first. ``krellbot.api.static`` does not exist before this NS lands;
the import lines below must fail in the RED phase.

Behavior under test:

  1. ``GET /`` returns the built ``frontend/dist/index.html`` with
     ``Content-Type: text/html`` and ``Cache-Control: no-store``. The body
     contains the shell copy ``Paper workstation``.
  2. ``GET /assets/<file>`` returns the matching file from
     ``frontend/dist/assets``. Path traversal (``..``), absolute paths,
     and missing files are 404; no file outside ``frontend/dist`` is
     ever read.
  3. ``GET /api/v1/capabilities`` still returns the JSON capabilities
     document. The static mount does not swallow ``/api``.
  4. A missing ``frontend/dist/index.html`` causes ``GET /`` to return
     404 with the closed JSON shape ``{"code": "shell_not_built"}``.
     The static layer does not synthesize the file.
  5. The legacy wizard/dashboard server (``krellbot.ui.server``) is
     untouched by this leaf.

The ASGI client is reused from ``tests.test_ns06_api``. The frontend is
builded when ``frontend/dist/index.html`` is absent so a cold checkout
runs green end to end.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_ns06_api import asgi_call

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"
INDEX_HTML = DIST_DIR / "index.html"

SHELL_PROMISE = "Paper workstation"
SHELL_NOT_BUILT_CODE = "shell_not_built"

# Env vars the API layer reads but the host might have set. Clearing them
# keeps the test independent of inherited keychain / venue credentials.
SECRET_ENV_VARS = (
    "KRELLBOT_ACTIVATION_KEY",
    "KRELLBOT_API_KEY",
    "KRELLBOT_API_SECRET",
    "KRELLBOT_COINBASE_API_KEY",
    "KRELLBOT_COINBASE_API_SECRET",
    "KRELLBOT_KRAKEN_API_KEY",
    "KRELLBOT_KRAKEN_API_SECRET",
    "KRELLBOT_KEYFILE",
    "KRELLBOT_SECRET_KEYFILE",
)


def _clear_secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset every inherited key/secret/keyfile env var without echoing values."""

    for name in SECRET_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _resolve_npm() -> str:
    """Return the npm executable to invoke (honours ``KB_NPM``)."""

    override = os.environ.get("KB_NPM")
    if override:
        return override
    found = shutil.which("npm")
    if not found:
        pytest.skip("npm is not available on PATH")
    return found


def _build_frontend() -> None:
    """Run ``npm ci --include=dev`` + ``npm run build`` for the test repo.

    Honours ``NODE_ENV=production`` by forcing dev-include; mirrors the
    helper in ``tests/test_ns07_assets.py``.
    """

    npm = _resolve_npm()
    env = os.environ.copy()
    env.setdefault("NODE_ENV", "development")
    for step in (["ci", "--include=dev"], ["run", "build"]):
        completed = subprocess.run(
            [npm, "--prefix", str(FRONTEND_DIR), *step],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=300,
        )
        if completed.returncode != 0:
            sys = __import__("sys")
            sys.stderr.write(completed.stdout)
            sys.stderr.write(completed.stderr)
            pytest.fail(f"npm {' '.join(step)} failed with {completed.returncode}")


@pytest.fixture(scope="module")
def built_dist() -> Path:
    """Return ``frontend/dist``, building the frontend if it is missing."""

    if INDEX_HTML.is_file():
        return DIST_DIR
    if not FRONTEND_DIR.is_dir():
        pytest.skip(f"frontend/ directory missing at {FRONTEND_DIR}")
    _build_frontend()
    if not INDEX_HTML.is_file():
        pytest.fail("vite build did not produce frontend/dist/index.html")
    return DIST_DIR


def _build_app(home: Path, *, dist_dir: Path) -> object:
    """Build a fresh API app with the given home and frontend dist directory."""

    from krellbot.api.app import create_app

    return create_app(
        home=home,
        port=8080,
        bootstrap_token=f"boot-{home.name}-{id(home)}",
        dist_dir=dist_dir,
    )


def _loopback_host_header(port: int = 8080) -> list[tuple[str, str]]:
    return [("Host", f"127.0.0.1:{port}")]


# ---- 1. GET / returns the built index.html -------------------------------


def test_root_returns_built_index_html(home: Path, built_dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``GET /`` returns ``frontend/dist/index.html`` with the right headers
    and body.

    The Vite-generated ``index.html`` carries the title marker
    ``krellbot — paper workstation`` (case-sensitive lowercase ``p``).
    The user-facing copy ``Paper workstation`` (capital ``P``) is the
    text the React app renders once the JS bundle loads; the bundle
    is reachable through ``/assets/<file>``. The brief's "body contains
    Paper workstation" is verified end-to-end: the served HTML plus the
    served JS bundle the browser receives carries that copy.
    """

    _clear_secret_env(monkeypatch)
    app = _build_app(home, dist_dir=built_dist)
    status, headers, body, _cookies = asgi_call(
        app,
        method="GET",
        path="/",
        headers=_loopback_host_header(),
    )
    assert status == 200, (status, headers, body)
    flat = {name.lower(): value for name, value in headers}
    ctype = flat.get("content-type", "")
    assert ctype.startswith("text/html"), ctype
    assert "no-store" in flat.get("cache-control", "").lower(), flat
    decoded = body.decode("utf-8")
    # The Vite title carries the canonical "paper workstation" marker.
    assert "paper workstation" in decoded, decoded[:512]
    # The JS bundle, reachable via /assets/<file>, carries the
    # capitalised "Paper workstation" copy the React app renders.
    assets_dir = built_dist / "assets"
    bundle_text = ""
    for path in sorted(assets_dir.iterdir()):
        bundle_text += path.read_text(encoding="utf-8")
    assert SHELL_PROMISE in bundle_text, "JS bundle is missing the shell copy"


def test_root_does_not_swallow_api(home: Path, built_dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The static mount must not swallow ``/api``; the capabilities
    endpoint still answers JSON.
    """

    _clear_secret_env(monkeypatch)
    app = _build_app(home, dist_dir=built_dist)
    status, _hdrs, body, _cookies = asgi_call(
        app,
        method="GET",
        path="/api/v1/capabilities",
        headers=_loopback_host_header(),
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded["schema_version"] == "1"
    assert decoded["live_orders"] is False


# ---- 2. GET /assets/<file> -------------------------------------------------


def test_assets_serves_existing_file(home: Path, built_dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``GET /assets/<file>`` returns the file from ``frontend/dist/assets``
    with a content-type derived from the extension.
    """

    assets_dir = built_dist / "assets"
    existing = next(path for path in assets_dir.iterdir() if path.is_file())
    rel_name = existing.name
    _clear_secret_env(monkeypatch)
    app = _build_app(home, dist_dir=built_dist)
    status, headers, body, _cookies = asgi_call(
        app,
        method="GET",
        path=f"/assets/{rel_name}",
        headers=_loopback_host_header(),
    )
    assert status == 200, (status, headers, body)
    assert body == existing.read_bytes(), "asset body did not match dist"
    flat = {name.lower(): value for name, value in headers}
    assert flat.get("content-type"), "asset response has no content-type"


def test_assets_missing_file_is_404(home: Path, built_dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A name that is not in ``frontend/dist/assets`` is 404."""

    _clear_secret_env(monkeypatch)
    app = _build_app(home, dist_dir=built_dist)
    status, _hdrs, _body, _cookies = asgi_call(
        app,
        method="GET",
        path="/assets/__nope__.js",
        headers=_loopback_host_header(),
    )
    assert status == 404, status


# ---- 3. path-traversal: .., absolute, outside-dist -----------------------


@pytest.fixture
def isolated_dist(home: Path) -> Path:
    """A throwaway dist tree with one allowed asset and a sibling secret.

    ``dist``
    ├── assets/legit.js
    └── secret.txt

    The secret is *inside* ``dist`` but *outside* ``dist/assets`` so a
    naive traversal ``/assets/../secret.txt`` would reach it.
    """

    dist = home / "dist_isolated"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (assets / "legit.js").write_text("LEGIT", encoding="utf-8")
    (dist / "secret.txt").write_text("SECRET_INSIDE_DIST", encoding="utf-8")
    return dist


def test_assets_dotdot_is_404_and_does_not_read_outside(
    home: Path, isolated_dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GET /assets/..`` is 404. The static layer must not serve the
    sibling ``secret.txt`` (or any other file outside ``dist/assets``).
    """

    _clear_secret_env(monkeypatch)
    app = _build_app(home, dist_dir=isolated_dist)
    status, _hdrs, body, _cookies = asgi_call(
        app,
        method="GET",
        path="/assets/..",
        headers=_loopback_host_header(),
    )
    assert status == 404, status
    assert b"SECRET_INSIDE_DIST" not in body, body


def test_assets_dotdot_segment_is_404_and_does_not_read_outside(
    home: Path, isolated_dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GET /assets/../secret.txt`` is 404 with no secret bytes leaked."""

    _clear_secret_env(monkeypatch)
    app = _build_app(home, dist_dir=isolated_dist)
    status, _hdrs, body, _cookies = asgi_call(
        app,
        method="GET",
        path="/assets/../secret.txt",
        headers=_loopback_host_header(),
    )
    assert status == 404, status
    assert b"SECRET_INSIDE_DIST" not in body, body


def test_assets_absolute_path_is_404(home: Path, isolated_dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``GET /assets//etc/passwd`` (a leading double slash that resolves
    to an absolute path on the request line) is 404 with no file read.
    """

    _clear_secret_env(monkeypatch)
    app = _build_app(home, dist_dir=isolated_dist)
    status, _hdrs, body, _cookies = asgi_call(
        app,
        method="GET",
        path="/assets//etc/passwd",
        headers=_loopback_host_header(),
    )
    assert status == 404, status
    # Nothing system-wide reached the client.
    assert b"root:" not in body


def test_assets_never_reads_outside_dist(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file written outside the configured ``dist_dir`` is never read,
    even when the URL traversal would nominally land on it.

    This is the strongest contract: the static resolver must not just
    refuse to serve; it must not open the file at all.
    """

    dist = tmp_path / "dist_clean"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "legit.js").write_text("LEGIT", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("OUTSIDE_FILE_CONTENTS", encoding="utf-8")
    _clear_secret_env(monkeypatch)
    app = _build_app(home, dist_dir=dist)
    # The traversal would resolve to ``outside.txt`` only if the static
    # layer lets ``..`` escape ``dist/assets``. The contract says 404.
    status, _hdrs, body, _cookies = asgi_call(
        app,
        method="GET",
        path="/assets/../../outside.txt",
        headers=_loopback_host_header(),
    )
    assert status == 404, status
    assert b"OUTSIDE_FILE_CONTENTS" not in body, body


# ---- 4. missing index.html -> shell_not_built ----------------------------


def test_missing_index_returns_shell_not_built(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``dist/index.html`` is absent, ``GET /`` is 404 with a
    closed JSON shape. The static layer must not synthesise the file.
    """

    empty_dist = tmp_path / "empty_dist"
    empty_dist.mkdir()
    # Note: NO assets/ or index.html.
    _clear_secret_env(monkeypatch)
    app = _build_app(home, dist_dir=empty_dist)
    status, headers, body, _cookies = asgi_call(
        app,
        method="GET",
        path="/",
        headers=_loopback_host_header(),
    )
    assert status == 404, (status, body)
    flat = {name.lower(): value for name, value in headers}
    ctype = flat.get("content-type", "")
    assert ctype.startswith("application/json"), ctype
    decoded = json.loads(body)
    assert decoded == {"code": SHELL_NOT_BUILT_CODE}, decoded
    # And the file was not synthesised.
    assert not (empty_dist / "index.html").exists()


def test_assets_still_404_when_index_missing(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing ``index.html`` does not break the asset route; a
    request is still 404 because the file is missing.
    """

    empty_dist = tmp_path / "empty_dist2"
    (empty_dist / "assets").mkdir(parents=True)
    _clear_secret_env(monkeypatch)
    app = _build_app(home, dist_dir=empty_dist)
    status, _hdrs, _body, _cookies = asgi_call(
        app,
        method="GET",
        path="/assets/whatever.js",
        headers=_loopback_host_header(),
    )
    assert status == 404, status


# ---- 5. legacy dashboard server is untouched -----------------------------


def test_legacy_dashboard_server_remains_intact(home: Path) -> None:
    """``krellbot.ui.server.DashboardServer`` still binds, exposes the
    token-gated dashboard, and is not touched by this leaf.
    """

    from krellbot.ui.server import DashboardServer

    server = DashboardServer(home=home, port=0)
    try:
        server.start()
        assert server.bound_host == "127.0.0.1"
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port, timeout=2)
        try:
            conn.request("GET", f"/{server.token}/")
            resp = conn.getresponse()
            resp.read()
            assert resp.status == 200
        finally:
            conn.close()
    finally:
        if server.bound_port:
            server.stop()
