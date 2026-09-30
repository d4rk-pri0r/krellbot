"""NS10b — paper status + paper pause / disarm workstation controls.

Tests-first. The Python half is the contract for ``GET /api/v1/paper/status``:

  1. The route uses the same session gate as ``GET /api/v1/jobs/{id}``
     (no CSRF, session cookie required, loopback Origin required, loopback
     Host required). A missing session cookie is 403; a non-loopback
     Origin is 403.
  2. With no pack armed the body is the closed shape
     ``{"schema_version": "1", "armed": false}``.
  3. With a pack armed the body returns ``armed: true`` plus
     ``venue``, ``pair``, ``entries_paused``, ``mode``, and ``pack_id``.
     The body never includes ``starting_cash`` (cash), ``owned_qty``
     (quantity), ``stop``, ``cap``, or ``pack_path`` — one focused test
     (``test_paper_status_omits_cash_stop_cap_quantity_and_path``)
     proves the no-leak contract in a single assertion surface.
  4. The status never carries ``mode: live``; the only mode the route
     may surface for a paper-armed record is ``"paper"``.

The route lives in the versioned loopback API; the brief's allowed-files
list names ``src/krellbot/api/app.py`` for one status route. There is no
control whose name includes ``Live`` and the session layer never receives
``mode: live``.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.test_ns06_api import (
    TEST_PORT as NS06_PORT,
)
from tests.test_ns06_api import (
    _bootstrap_and_get_csrf,
    _build_app,
    _default_host_header,
    _run_paper_arm,
    asgi_call,
)

# ``tests/test_ns06_api.py`` defines ``TEST_PORT = 8080``. The route is
# loopback-bound; keeping the same port keeps the gate parity test fair.
TEST_PORT = NS06_PORT


# ---- helpers --------------------------------------------------------------


def _get_paper_status(
    app,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes, list[str]]:
    """Issue ``GET /api/v1/paper/status`` against ``app``.

    Returns ``(status, headers_list, body_bytes, set_cookies)`` so the
    caller can assert on the closed shape the brief spells out.
    """

    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="GET", path="/api/v1/paper/status", headers=base)


def _bootstrap_session_cookie(app, token: str) -> str:
    """Redeem ``token`` on ``app`` and return the session cookie value.

    Sessions live in ``app.state.krellbot.sessions``; a fresh app means
    a fresh session map, so the caller must use the returned value with
    the same ``app`` instance. The bootstrap endpoint is one-time per
    process token, so building two apps with the same token and
    bootstrapping on each would fail the second time.
    """

    csrf_token = _bootstrap_and_get_csrf(app, token)
    assert csrf_token, csrf_token
    state = app.state.krellbot
    session_value = next(iter(state.sessions.keys()))
    return session_value


def _read_json(body: bytes) -> dict:
    decoded = json.loads(body)
    assert isinstance(decoded, dict), decoded
    return decoded


# ---- 1. session gate parity with GET /api/v1/jobs/{id} --------------------


def test_paper_status_without_session_cookie_is_403(home: Path) -> None:
    """``GET /api/v1/paper/status`` without a session cookie is 403, the
    same gate as ``GET /api/v1/jobs/{id}``.
    """

    app = _build_app(home)
    status, _h, _b, _c = _get_paper_status(
        app,
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, status


def test_paper_status_with_non_loopback_origin_is_403(home: Path) -> None:
    """``GET /api/v1/paper/status`` with a non-loopback Origin is 403,
    the same gate as ``GET /api/v1/jobs/{id}``."""

    token = f"boot-status-origin-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    headers = [
        ("Origin", "http://evil.example.com"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    status, _h, _b, _c = _get_paper_status(app, headers=headers)
    assert status == 403, status


def test_paper_status_with_non_loopback_host_is_403(home: Path) -> None:
    """``GET /api/v1/paper/status`` with a non-loopback Host is 403."""

    app = _build_app(home)
    headers = [
        ("Host", "evil.example.com"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
    ]
    status, _h, _b, _c = _get_paper_status(app, headers=headers)
    assert status == 403, status


def test_paper_status_does_not_require_csrf_header(home: Path) -> None:
    """The status route is gated only by the session cookie + loopback
    Origin; a missing or wrong ``X-Krellbot-CSRF`` header is accepted
    (matches the ``GET /api/v1/jobs/{id}`` contract).
    """

    token = f"boot-status-no-csrf-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
        ("X-Krellbot-CSRF", "not-the-real-csrf"),
    ]
    status, _h, body, _c = _get_paper_status(app, headers=headers)
    # The CSRF gate does not fire; we are looking at 200 with the closed
    # no-armed-pack shape.
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["armed"] is False, decoded


# ---- 2. no pack armed → closed shape --------------------------------------


def test_paper_status_with_no_armed_pack_returns_closed_shape(home: Path) -> None:
    """When no pack is armed the body is exactly
    ``{"schema_version": "1", "armed": false}``. No extra keys leak.
    """

    token = f"boot-status-empty-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    status, _h, body, _c = _get_paper_status(app, headers=headers)
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded == {"schema_version": "1", "armed": False}, decoded


# ---- 3. armed pack returns venue / pair / entries_paused / mode / pack_id


def test_paper_status_with_armed_pack_returns_typed_projection(home: Path) -> None:
    """When a paper pack is armed the body returns ``armed: true`` plus
    the closed field set: ``venue``, ``pair``, ``entries_paused``,
    ``mode``, ``pack_id``.
    """

    _run_paper_arm(home)
    token = f"boot-status-armed-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    status, _h, body, _c = _get_paper_status(app, headers=headers)
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded.get("armed") is True, decoded
    assert decoded.get("schema_version") == "1", decoded
    assert decoded.get("venue") == "kraken", decoded
    assert decoded.get("pair") == "SUIUSD", decoded
    assert decoded.get("mode") == "paper", decoded
    assert decoded.get("entries_paused") is False, decoded
    assert decoded.get("pack_id") == "trend-follow", decoded


def test_paper_status_reflects_entries_paused_state(home: Path) -> None:
    """The status surfaces ``entries_paused`` as a bool that tracks the
    on-disk armed-pack record.
    """

    _run_paper_arm(home)
    from krellbot.application.paper import PaperService

    PaperService(home=home).pause_entries(venue="kraken", pair="SUIUSD", correlation_id="seed-pause")
    token = f"boot-status-paused-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    status, _h, body, _c = _get_paper_status(app, headers=headers)
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded.get("entries_paused") is True, decoded
    assert decoded.get("armed") is True, decoded


# ---- 4. no-leak: status omits cash, stop, cap, quantity, path -------------


def test_paper_status_omits_cash_stop_cap_quantity_and_path(home: Path) -> None:
    """The status projection is the closed field set the brief spells
    out. Cash (``starting_cash``), stop, cap, quantity (``owned_qty``),
    and the pack path are never returned. This is the single Python
    assertion surface the brief requires.
    """

    _run_paper_arm(home)
    token = f"boot-status-no-leak-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    status, _h, body, _c = _get_paper_status(app, headers=headers)
    assert status == 200, (status, body)
    decoded = _read_json(body)
    # Field-by-field, with explicit reason text so the failure message
    # points at the leak.
    forbidden = {
        "starting_cash": "cash",
        "stop": "stop price",
        "cap": "cap percent",
        "owned_qty": "quantity",
        "pack_path": "pack path",
    }
    leaked = sorted(field for field in forbidden if field in decoded)
    assert leaked == [], (leaked, decoded)
    # And the strings must not appear anywhere in the serialised body.
    raw = body.decode("utf-8")
    for needle in ("starting_cash", "owned_qty", "stop", "cap", "pack_path"):
        assert needle not in raw, (needle, raw)


# ---- 5. status never reports ``mode: live`` -------------------------------


def test_paper_status_reports_the_armed_mode(home: Path) -> None:
    """A live armed record stays live. The route must not relabel it paper."""

    from krellbot.config import load_config, save_config

    _run_paper_arm(home)
    config = load_config(home)
    assert config.armed, "paper arm did not persist"
    config.armed[0].mode = "live"
    save_config(home, config)

    token = f"boot-status-mode-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    status, _h, body, _c = _get_paper_status(app, headers=headers)
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded.get("mode") == "live", decoded
    assert "starting_cash" not in decoded
    assert "stop" not in decoded


# ---- 6. status route appears in the OpenAPI schema ------------------------


def test_paper_status_path_appears_in_openapi(home: Path) -> None:
    """The new route is listed in the generated OpenAPI document so the
    M1 contract surface is one route per versioned endpoint."""

    app = _build_app(home)
    status, _h, body, _c = asgi_call(app, method="GET", path="/openapi.json", headers=_default_host_header())
    assert status == 200, status
    decoded = _read_json(body)
    paths = decoded.get("paths") or {}
    assert "/api/v1/paper/status" in paths, sorted(paths.keys())


# ---- 7. gate parity with jobs/{id} via shared helper -----------------------


def test_paper_status_gate_parity_with_jobs_endpoint(home: Path) -> None:
    """Both routes are gated by ``_gate_get``: same 403 surface, same
    allowed headers. A request that is 403 on ``GET /api/v1/jobs/{id}``
    is also 403 on ``GET /api/v1/paper/status``.
    """

    app = _build_app(home)
    # No session cookie, loopback Host.
    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
    ]
    s_paper, _, _, _ = _get_paper_status(app, headers=headers)
    s_jobs, _, _, _ = asgi_call(app, method="GET", path="/api/v1/jobs/anything", headers=headers)
    assert s_paper == 403, s_paper
    assert s_jobs == 403, s_jobs
    assert s_paper == s_jobs, (s_paper, s_jobs)


def test_paper_status_with_session_returns_200_for_jobs_route(home: Path) -> None:
    """Sanity check: the same fixture that drives the paper status route
    also drives the jobs route. The session cookie minted during
    bootstrap lets both routes through.
    """

    token = f"boot-status-parity-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    s_paper, _, body_paper, _ = _get_paper_status(app, headers=headers)
    assert s_paper == 200, (s_paper, body_paper)
    s_jobs, _, body_jobs, _ = asgi_call(app, method="GET", path="/api/v1/jobs/unknown-id", headers=headers)
    assert s_jobs == 404, (s_jobs, body_jobs)
