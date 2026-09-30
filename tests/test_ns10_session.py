"""NS10a — loopback session bootstrap.

Tests-first. The tests in this file are the contract for the leaf that
puts the one-time bootstrap token into the served loopback page and
keeps the returned CSRF token in module memory.

Behavior under test (brief: ``.superpowers/sdd/krellbot-2027/NS10/NS10a-brief.md``):

  1. ``GET /`` returns the built ``frontend/dist/index.html`` with the
     injected meta tag ``<meta name="krellbot-bootstrap" content="...">``
     whose ``content`` is the loopback app's bootstrap token. The
     on-disk ``frontend/dist/index.html`` is not modified — the
     token is injected at response time.
  2. A missing build still returns ``{"code": "shell_not_built"}``
     and does not invent HTML, even when a bootstrap token is
     supplied to ``create_app``.
  3. The token embedded in the served meta tag round-trips through
     the existing ``/api/v1/session/bootstrap`` endpoint (the existing
     NS06a endpoint accepts it and returns 200 + ``csrf_token``).
  4. A second ``/api/v1/session/bootstrap`` call with the same token
     is the existing server 403 (one-time redemption), regardless of
     where the token came from.
  5. The static layer still enforces ``Cache-Control: no-store`` on
     ``GET /`` even when a bootstrap token is injected.

The tests reuse the ASGI client and ``home`` fixture from
``tests/test_ns06_api`` and ``tests/test_ns07_serve``. The dist tree is
injected per-test so a cold checkout or a stale built tree cannot leak
state.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.test_ns06_api import asgi_call

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

TEST_PORT = 8080


def _clear_secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset every inherited key/secret/keyfile env var without echoing values."""

    for name in SECRET_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _build_app(home: Path, *, dist_dir: Path, bootstrap_token: str):
    """Build a fresh API app with the given home, dist directory, and
    bootstrap token."""

    from krellbot.api.app import create_app

    return create_app(
        home=home,
        port=TEST_PORT,
        bootstrap_token=bootstrap_token,
        dist_dir=dist_dir,
    )


def _loopback_host_header(port: int = TEST_PORT) -> list[tuple[str, str]]:
    return [("Host", f"127.0.0.1:{port}")]


def _default_origin_header(port: int = TEST_PORT) -> list[tuple[str, str]]:
    return [("Origin", f"http://127.0.0.1:{port}")]


def _post_json(
    app,
    path: str,
    payload: dict,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes, list[str]]:
    body = json.dumps(payload).encode("utf-8")
    base = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="POST", path=path, body=body, headers=base)


SHELL_HTML = (
    "<!doctype html>\n"
    '<html lang="en">\n'
    "  <head>\n"
    '    <meta charset="UTF-8" />\n'
    "    <title>krellbot — paper workstation</title>\n"
    "  </head>\n"
    "  <body>\n"
    '    <div id="root"></div>\n'
    "  </body>\n"
    "</html>\n"
)


def _write_minimal_dist(dist: Path) -> Path:
    """Create a dist tree with one valid HTML index and one asset.

    The token-free index.html matches the NS07a / NS07b invariants:
    a minimal HTML shell with a ``<head>`` and a ``<body>``.
    """

    assets = dist / "assets"
    assets.mkdir(parents=True)
    (assets / "index.js").write_text("// placeholder", encoding="utf-8")
    index_path = dist / "index.html"
    index_path.write_text(SHELL_HTML, encoding="utf-8")
    return index_path


# ---- 1. Bootstrap token is injected into served index.html ----------------


def test_root_injects_bootstrap_meta_tag(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``GET /`` returns the built ``dist/index.html`` with the bootstrap
    token injected as ``<meta name="krellbot-bootstrap" content="...">``.

    The on-disk ``index.html`` is not modified: the token appears only
    in the response body, never in the file the Vite build wrote.
    """

    _clear_secret_env(monkeypatch)
    dist = tmp_path / "dist_meta"
    index_path = _write_minimal_dist(dist)
    token = f"boot-{home.name}-{id(home)}-meta"

    app = _build_app(home, dist_dir=dist, bootstrap_token=token)
    status, headers, body, _cookies = asgi_call(
        app,
        method="GET",
        path="/",
        headers=_loopback_host_header(),
    )
    assert status == 200, (status, headers, body)
    decoded = body.decode("utf-8")
    # The bootstrap token is injected as a meta tag.
    assert 'name="krellbot-bootstrap"' in decoded, decoded
    assert f'content="{token}"' in decoded, decoded
    # The on-disk file is unchanged: no token, no meta tag.
    on_disk = index_path.read_text(encoding="utf-8")
    assert "krellbot-bootstrap" not in on_disk, on_disk
    assert token not in on_disk, on_disk
    # Cache-Control: no-store still applies.
    flat = {name.lower(): value for name, value in headers}
    assert "no-store" in flat.get("cache-control", "").lower(), flat
    # The injected meta tag lives inside <head>, not <body>.
    head_open = decoded.find("<head>")
    head_close = decoded.find("</head>")
    assert head_open != -1 and head_close != -1, decoded
    inside_head = decoded[head_open:head_close]
    assert 'name="krellbot-bootstrap"' in inside_head, inside_head


def test_root_injects_meta_with_token_containing_url_safe_chars(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The injection does not HTML-mangle the token.

    ``secrets.token_urlsafe`` returns the URL-safe alphabet
    (``A-Z a-z 0-9 - _``). A token of that shape round-trips into the
    meta tag's ``content`` attribute unchanged and is decoded
    byte-for-byte by the bootstrap endpoint.
    """

    _clear_secret_env(monkeypatch)
    dist = tmp_path / "dist_token_chars"
    _write_minimal_dist(dist)
    # A realistic token from secrets.token_urlsafe(32) — URL-safe only.
    token = "abcd-EFGH_1234_ijkl-MNOP_5678-qrst_UVWX_90yz"

    app = _build_app(home, dist_dir=dist, bootstrap_token=token)
    status, _hdrs, body, _cookies = asgi_call(app, method="GET", path="/", headers=_loopback_host_header())
    assert status == 200, (status, body)
    decoded = body.decode("utf-8")
    assert f'content="{token}"' in decoded, decoded


def test_root_meta_tag_has_no_localstorage_or_script(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The injection is a single static ``<meta>`` tag — no inline
    ``<script>``, no ``localStorage`` mention. The bootstrap redemption
    is left to the JS bundle.
    """

    _clear_secret_env(monkeypatch)
    dist = tmp_path / "dist_static_only"
    _write_minimal_dist(dist)
    token = f"boot-static-{home.name}"
    app = _build_app(home, dist_dir=dist, bootstrap_token=token)
    _status, _hdrs, body, _cookies = asgi_call(app, method="GET", path="/", headers=_loopback_host_header())
    decoded = body.decode("utf-8")
    # No inline script tags were added by the static layer.
    assert "<script" not in decoded
    # No localStorage mention anywhere.
    assert "localStorage" not in decoded


# ---- 2. Missing build still returns shell_not_built ------------------------


def test_root_missing_build_still_returns_shell_not_built(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing build returns ``{"code": "shell_not_built"}`` with 404
    even when ``create_app`` was supplied a bootstrap token. The
    static layer does not invent HTML, and it does not leak the
    bootstrap token into a synthesised shell.
    """

    _clear_secret_env(monkeypatch)
    empty_dist = tmp_path / "empty"
    empty_dist.mkdir()
    app = _build_app(home, dist_dir=empty_dist, bootstrap_token="some-token")

    status, headers, body, _cookies = asgi_call(app, method="GET", path="/", headers=_loopback_host_header())
    assert status == 404, (status, body)
    flat = {name.lower(): value for name, value in headers}
    assert flat.get("content-type", "").startswith("application/json")
    decoded = json.loads(body)
    assert decoded == {"code": "shell_not_built"}, decoded
    # And the file was not synthesised.
    assert not (empty_dist / "index.html").exists()
    # The bootstrap token does not appear in the response body.
    assert "some-token" not in body.decode("utf-8")


# ---- 3. Token in the served meta tag round-trips through /session/bootstrap


def test_served_token_redeems_at_bootstrap_endpoint(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The token embedded in the served meta tag is the same token the
    bootstrap endpoint accepts. Redeeming it returns 200 + csrf_token
    and sets the loopback session cookie.
    """

    _clear_secret_env(monkeypatch)
    dist = tmp_path / "dist_redeem"
    _write_minimal_dist(dist)
    token = f"boot-redeem-{home.name}"
    app = _build_app(home, dist_dir=dist, bootstrap_token=token)

    status, _hdrs, body, _cookies = asgi_call(app, method="GET", path="/", headers=_loopback_host_header())
    assert status == 200, (status, body)
    decoded = body.decode("utf-8")
    match = re.search(r'name="krellbot-bootstrap"\s+content="([^"]+)"', decoded)
    assert match, decoded
    served_token = match.group(1)
    assert served_token == token, served_token

    # Now redeem it.
    rstatus, _rhdrs, rbody, rcookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": served_token},
        headers=_default_origin_header(),
    )
    assert rstatus == 200, (rstatus, rbody, rcookies)
    payload = json.loads(rbody)
    assert payload["schema_version"] == "1"
    csrf_token = payload.get("csrf_token")
    assert isinstance(csrf_token, str) and len(csrf_token) >= 16, payload
    # Session cookie set.
    assert any(c.startswith("krellbot_session=") for c in rcookies)


# ---- 4. Bootstrap redemption is one-time (existing server contract) ----


def test_bootstrap_second_call_with_same_token_is_403(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bootstrap token is one-time. A second POST with the same
    token returns the existing server 403, regardless of which API
    surface delivered it.
    """

    _clear_secret_env(monkeypatch)
    token = f"boot-once-{home.name}"
    # An absent dist directory is fine: the bootstrap endpoint lives at
    # /api/v1/session/bootstrap, not at GET /.
    from krellbot.api.app import create_app

    app = create_app(
        home=home,
        port=TEST_PORT,
        bootstrap_token=token,
        dist_dir=Path("/nonexistent-dist"),
    )
    s1, _h, _b, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    assert s1 == 200, (s1, cookies)
    s2, _h, _b, _c = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    assert s2 == 403, s2


# ---- 5. Cache-Control: no-store is preserved -----------------------------


def test_root_keeps_no_store_when_meta_tag_is_injected(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The injected meta tag does not weaken the no-store contract.
    A freshly-built bundle replaces the previous one on the next
    reload, so the new token (which is per-process) replaces the old.
    """

    _clear_secret_env(monkeypatch)
    dist = tmp_path / "dist_no_store"
    _write_minimal_dist(dist)
    token = f"boot-no-store-{home.name}"
    app = _build_app(home, dist_dir=dist, bootstrap_token=token)
    status, headers, body, _cookies = asgi_call(app, method="GET", path="/", headers=_loopback_host_header())
    assert status == 200, (status, body)
    flat = {name.lower(): value for name, value in headers}
    assert flat.get("cache-control", "").lower() == "no-store", flat
