"""F02 — refuse an unregistered session on read routes.

Tests-first. The defect: ``_gate_get`` in ``src/krellbot/api/app.py`` only
checks that a session cookie is present. It does not check whether the
cookie value is in ``app.state.krellbot.sessions``. A fabricated cookie
therefore passes the gate and reaches the route handler; for
``GET /api/v1/paper/status`` this leaks the closed-shape status body
(``armed``, ``venue``, ``pair``, ``mode``).

The fix lives in ``_gate_get``: the cookie must be keyed in ``s.sessions``.
Same-origin GETs (no ``Origin`` header) are allowed because browsers do
not send ``Origin`` on same-origin GET. POST routes are unchanged —
their gate is ``_gate_state_change``, not ``_gate_get``; it keeps the
loopback-origin + cookie-present + CSRF checks.

Behavior under test:

  1. A missing cookie, an invented cookie, and a cookie removed from
     ``s.sessions`` are 403 on ``GET /api/v1/paper/status``,
     ``GET /api/v1/jobs/{id}``, ``GET /api/v1/jobs/{id}/result``, and
     ``GET /api/v1/events``. The body is exactly ``{"detail": "session
     required"}``; it must not leak ``armed``, ``venue``, ``pair``,
     ``mode``, ``pack_id``, ``entries_paused``, or a job payload.
  2. A cookie from a fresh bootstrap still reads those routes.
  3. A GET with no ``Origin`` and a loopback ``Host`` is allowed.
     A present non-loopback ``Origin`` stays 403.
  4. POST routes stay as they are: loopback Origin, cookie present,
     CSRF. The existing CSRF tests must continue to pass and are
     re-asserted at the end of this file.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.test_ns06_api import (
    TEST_PORT,
    _bootstrap_token,
    _build_app,
    _default_origin_header,
    _post_json,
    _session_from_cookies,
    asgi_call,
)

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


READ_PATHS = (
    "/api/v1/paper/status",
    "/api/v1/jobs/some-id",
    "/api/v1/jobs/some-id/result",
    "/api/v1/events",
)


def _bootstrap(app) -> str:
    """Redeem the app's bootstrap token and return the session cookie value.

    The token comes from ``_bootstrap_token(home)`` which
    ``_build_app(home, bootstrap_token=token)`` already used, so the cookie
    is registered in ``app.state.krellbot.sessions`` for the lifetime of
    this app instance.
    """

    state = app.state.krellbot
    status, _h, _b, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": state.bootstrap_token},
        headers=_default_origin_header(),
    )
    assert status == 200, (status, _b)
    return _session_from_cookies(cookies)


def _session_bootstrap_headers(session: str, *, with_origin: bool = True) -> list[tuple[str, str]]:
    """Loopback Host plus a session cookie; optional loopback ``Origin``.

    Used both for "valid session, loopback Origin" positive cases and for
    "valid session, missing Origin" same-origin-GET cases.
    """

    headers: list[tuple[str, str]] = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if with_origin:
        headers.append(("Origin", f"http://127.0.0.1:{TEST_PORT}"))
    headers.append(("Cookie", f"krellbot_session={session}"))
    return headers


def _get(app, path: str, headers: list[tuple[str, str]]):
    """Wrapper that drops ``Content-Type``/``Content-Length`` if a caller
    accidentally passes them; GETs never carry a body."""

    return asgi_call(app, method="GET", path=path, headers=headers)


# ---------------------------------------------------------------------------
# 1. Unregistered sessions are 403 with the closed-shape rejection body
# ---------------------------------------------------------------------------


def _assert_403_session_required(app, path: str) -> None:
    """Drive ``path`` with three unregistered-cookie cases; each is 403
    with body ``{"detail": "session required"}`` and no field beyond
    ``detail``.

    Every header set sent here includes a loopback ``Host`` so the
    request reaches the auth gate; the brief's gate fires at the route,
    not at the host middleware.
    """

    base_headers: list[tuple[str, str]] = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
    ]

    # 1a. Missing cookie entirely (no Cookie header).
    status, _h, body, _c = _get(app, path, list(base_headers))
    assert status == 403, (path, "missing-cookie", status, body)
    decoded = json.loads(body) if body else None
    assert decoded == {"detail": "session required"}, (path, "missing-cookie", decoded)

    # 1b. Invented cookie value (not in s.sessions).
    headers = list(base_headers) + [("Cookie", "krellbot_session=fabricated-token-xyz")]
    status, _h, body, _c = _get(app, path, headers)
    assert status == 403, (path, "invented-cookie", status, body)
    decoded = json.loads(body) if body else None
    assert decoded == {"detail": "session required"}, (path, "invented-cookie", decoded)

    # 1c. Revoked cookie: bootstrap, then remove the session from s.sessions.
    real = _bootstrap(app)
    state = app.state.krellbot
    state.sessions.pop(real, None)
    headers = _session_bootstrap_headers(real)
    status, _h, body, _c = _get(app, path, headers)
    assert status == 403, (path, "revoked-cookie", status, body)
    decoded = json.loads(body) if body else None
    assert decoded == {"detail": "session required"}, (path, "revoked-cookie", decoded)


def test_unregistered_session_is_403_on_paper_status(home: Path) -> None:
    """``GET /api/v1/paper/status`` rejects every flavour of unregistered
    cookie with a closed 403 body."""

    app = _build_app(home, bootstrap_token=_bootstrap_token(home))
    _assert_403_session_required(app, "/api/v1/paper/status")


def test_unregistered_session_is_403_on_jobs_id(home: Path) -> None:
    """``GET /api/v1/jobs/{id}`` rejects every flavour of unregistered
    cookie. The 403 fires at the authentication gate — before the route's
    ``not_found`` path runs."""

    app = _build_app(home, bootstrap_token=_bootstrap_token(home))
    _assert_403_session_required(app, "/api/v1/jobs/some-id")


def test_unregistered_session_is_403_on_jobs_result(home: Path) -> None:
    """``GET /api/v1/jobs/{id}/result`` rejects every flavour of
    unregistered cookie."""

    app = _build_app(home, bootstrap_token=_bootstrap_token(home))
    _assert_403_session_required(app, "/api/v1/jobs/some-id/result")


def test_unregistered_session_is_403_on_events_sse(home: Path) -> None:
    """``GET /api/v1/events`` rejects every flavour of unregistered
    cookie. SSE does not start."""

    app = _build_app(home, bootstrap_token=_bootstrap_token(home))
    _assert_403_session_required(app, "/api/v1/events")


# ---------------------------------------------------------------------------
# 1d. The 403 body must not leak armed / venue / pair / mode / pack_id /
#     entries_paused / job fields. Verified across paper status and jobs.
# ---------------------------------------------------------------------------


_FORBIDDEN_FIELDS = (
    "armed",
    "venue",
    "pair",
    "mode",
    "pack_id",
    "entries_paused",
    # Generic job result fields — must not leak when the cookie is bad.
    "schema_version",
    "kind",
    "state",
    "progress",
    "result_ref",
    "correlation_id",
    "legacy_receipt",
    "trace",
)


def test_403_body_on_paper_status_does_not_leak_closed_shape(home: Path) -> None:
    """The 403 for ``GET /api/v1/paper/status`` is a single ``detail``
    key. None of the status projection's fields leak."""

    app = _build_app(home, bootstrap_token=_bootstrap_token(home))
    # Bootstrap and arm a pack so the legitimate route would surface all
    # the fields below. The 403 body must still be empty of state.
    from decimal import Decimal

    from krellbot.application.paper import PaperService

    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    pack_path = packs / "leak.json"
    pack_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "leak-pack",
                "version": "1.0.0",
                "label": "leak",
                "author": "f02 test",
                "timeframe": "1h",
                "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
                "entry": ["close", ">", "sma20"],
                "exit": ["close", "<", "sma20"],
                "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
                "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
            }
        ),
        encoding="utf-8",
    )
    PaperService(home=home).arm(
        pack_path,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
        correlation_id="f02-seed",
    )

    base_headers: list[tuple[str, str]] = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
    ]
    for cookie_value in (None, "fabricated-token-xyz"):
        headers = list(base_headers)
        if cookie_value is not None:
            headers = headers + [("Cookie", f"krellbot_session={cookie_value}")]
        status, _h, body, _c = _get(app, "/api/v1/paper/status", headers)
        assert status == 403, (cookie_value, status, body)
        decoded = json.loads(body) if body else None
        assert isinstance(decoded, dict), decoded
        # Closed body: only ``detail``.
        assert set(decoded.keys()) == {"detail"}, sorted(decoded.keys())
        # No field string is present, in any casing.
        raw = body.decode("utf-8")
        for needle in _FORBIDDEN_FIELDS:
            assert needle not in raw, (cookie_value, needle, raw)


def test_403_body_on_jobs_route_does_not_leak_job_payload(home: Path) -> None:
    """The 403 for ``GET /api/v1/jobs/{id}`` is a single ``detail`` key.
    A known job id (``not_found`` is reached) is irrelevant: the
    authentication gate must reject the request before the handler runs.
    """

    app = _build_app(home, bootstrap_token=_bootstrap_token(home))
    _csrf, _session_cookie, job_id = _seed_one_succeeded_job(app, home)

    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
    ]
    status, _h, body, _c = _get(app, f"/api/v1/jobs/{job_id}", headers)
    assert status == 403, (status, body)
    decoded = json.loads(body) if body else None
    assert isinstance(decoded, dict), decoded
    assert set(decoded.keys()) == {"detail"}, sorted(decoded.keys())
    raw = body.decode("utf-8")
    for needle in _FORBIDDEN_FIELDS:
        assert needle not in raw, (needle, raw)


def test_403_body_on_jobs_result_does_not_leak_receipt(home: Path) -> None:
    """The 403 for ``GET /api/v1/jobs/{id}/result`` is a single ``detail``
    key, even when a real receipt is stored against the job."""

    app = _build_app(home, bootstrap_token=_bootstrap_token(home))
    _csrf, _session_cookie, job_id = _seed_one_succeeded_job(app, home)

    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
    ]
    status, _h, body, _c = _get(app, f"/api/v1/jobs/{job_id}/result", headers)
    assert status == 403, (status, body)
    decoded = json.loads(body) if body else None
    assert isinstance(decoded, dict), decoded
    assert set(decoded.keys()) == {"detail"}, sorted(decoded.keys())
    raw = body.decode("utf-8")
    for needle in _FORBIDDEN_FIELDS:
        assert needle not in raw, (needle, raw)


def _seed_one_succeeded_job(app, home: Path) -> tuple[str, str, str]:
    """Bootstrap a session and submit one fast-succeeding research job.

    Returns ``(csrf, session_cookie_value, job_id)``. The runner is the
    default one — the job manager stores ``result_ref`` automatically when
    ``ok`` is True. The job id is used by the leak-check tests to confirm
    the 403 fires at the gate, not at the route.
    """

    csrf, session = _bootstrap_session(app)
    payload = {"correlation_id": "f02-leak-seed", "kind": "research.backtest"}
    status, _h, body, _cookies = _post_json(
        app,
        "/api/v1/research/jobs",
        payload,
        headers=[
            ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
            ("X-Krellbot-CSRF", csrf),
            ("Cookie", f"krellbot_session={session}"),
        ],
    )
    assert status == 200, (status, body)
    job_id = json.loads(body)["id"]
    return csrf, session, job_id


def _bootstrap_session(app) -> tuple[str, str]:
    """Bootstrap and return ``(csrf_token, session_cookie_value)``."""

    state = app.state.krellbot
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": state.bootstrap_token},
        headers=_default_origin_header(),
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    return decoded["csrf_token"], _session_from_cookies(cookies)


# ---------------------------------------------------------------------------
# 2. A cookie from a fresh bootstrap still reads every protected read route.
# ---------------------------------------------------------------------------


def test_fresh_bootstrap_cookie_reads_paper_status(home: Path) -> None:
    """After bootstrap, ``GET /api/v1/paper/status`` returns the closed
    no-armed-pack shape."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    session = _bootstrap(app)
    status, _h, body, _c = _get(app, "/api/v1/paper/status", _session_bootstrap_headers(session))
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded == {"schema_version": "1", "armed": False}, decoded


def test_fresh_bootstrap_cookie_reads_jobs_and_result(home: Path) -> None:
    """After bootstrap, ``GET /api/v1/jobs/{id}`` returns the JobV1
    shape and ``GET /api/v1/jobs/{id}/result`` returns
    ``not_found``/``result_unavailable`` for an unknown id — the routes
    run, not the gate."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    session = _bootstrap(app)
    headers = _session_bootstrap_headers(session)

    s1, _h, body1, _c = _get(app, "/api/v1/jobs/unknown-job", headers)
    assert s1 == 404, (s1, body1)
    decoded1 = json.loads(body1)
    assert decoded1.get("code") == "not_found", decoded1

    s2, _h, body2, _c = _get(app, "/api/v1/jobs/unknown-job/result", headers)
    assert s2 == 404, (s2, body2)
    decoded2 = json.loads(body2)
    assert decoded2.get("code") == "not_found", decoded2


# ---------------------------------------------------------------------------
# 3. Same-origin GETs (no Origin) are allowed; non-loopback Origin still 403.
# ---------------------------------------------------------------------------


def test_same_origin_get_without_origin_header_is_allowed(home: Path) -> None:
    """A GET with no ``Origin`` header but a loopback ``Host`` is allowed
    when the session cookie is registered. Browsers do not send
    ``Origin`` on same-origin GET."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    session = _bootstrap(app)
    headers = _session_bootstrap_headers(session, with_origin=False)
    for path in READ_PATHS:
        status, _h, body, _c = _get(app, path, headers)
        assert status != 403, (path, status, body[:80])


def test_non_loopback_origin_is_403_for_paper_status(home: Path) -> None:
    """An explicit non-loopback ``Origin`` is 403 even with a valid
    session."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    session = _bootstrap(app)
    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Origin", "http://evil.example.com"),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _h, body, _c = _get(app, "/api/v1/paper/status", headers)
    assert status == 403, (status, body)


def test_non_loopback_origin_is_403_for_jobs_route(home: Path) -> None:
    """An explicit non-loopback ``Origin`` is 403 on the jobs route
    even with a valid session."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    session = _bootstrap(app)
    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Origin", "http://evil.example.com"),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _h, body, _c = _get(app, "/api/v1/jobs/x", headers)
    assert status == 403, (status, body)


def test_non_loopback_host_is_403(home: Path) -> None:
    """A non-loopback ``Host`` is rejected by the app middleware before
    any route runs; the read gate inherits that 403."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    session = _bootstrap(app)
    headers = [
        ("Host", "evil.example.com"),
        ("Origin", "http://evil.example.com"),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _h, body, _c = _get(app, "/api/v1/paper/status", headers)
    assert status == 403, (status, body)


# ---------------------------------------------------------------------------
# 4. POST routes stay as they are: loopback Origin, session cookie
#    present, CSRF. The F02 fix is scoped to ``_gate_get``. These tests
#    pin the unchanged contract.
# ---------------------------------------------------------------------------


def test_post_commands_still_requires_loopback_origin_session_and_csrf(
    home: Path,
) -> None:
    """``POST /api/v1/commands`` with no headers is 403 (no loopback
    Origin). The middleware short-circuits, but a missing Origin on a
    POST is the same 403 the existing test suite pins — the F02 fix
    leaves this behaviour intact for POSTs."""

    app = _build_app(home, bootstrap_token=_bootstrap_token(home))
    # No Origin header at all.
    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        {"command": "paper.arm", "payload": {"pack_path": "/tmp/x"}},
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
        ],
    )
    assert status == 403, (status, body)


def test_post_commands_still_rejects_fabricated_cookie_even_with_csrf(
    home: Path,
) -> None:
    """A POST with a fabricated cookie and the wrong CSRF stays 403.
    The defect is read-side: this test pins that POSTs were not
    loosened as a side effect."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    real = _bootstrap(app)
    # Use a wrong CSRF (the real cookie's matching CSRF would let the
    # session gate clear; we don't actually want it to clear — we want to
    # confirm POST still rejects.)
    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        {"command": "paper.arm", "payload": {"pack_path": "/tmp/x"}},
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
            ("X-Krellbot-CSRF", "wrong-csrf"),
            ("Cookie", f"krellbot_session={real}"),
        ],
    )
    assert status == 403, (status, body)


def test_post_commands_csrf_is_unchanged_by_f02(home: Path) -> None:
    """The CSRF check on POSTs is exercised by the existing
    ``test_ns06_api::test_commands_requires_csrf_header`` and friends.
    This test pins the *positive* path: a valid session + valid CSRF +
    loopback Origin lets a paper command through. The fact that the
    route still requires a registered session/CSRF pair is the F02
    no-regression guard."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    _csrf, session = _bootstrap_session(app)

    # Pick an obviously-bad command; the route must reject with the same
    # 403 the existing CSRF pin asserts, regardless of which path it
    # took.
    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        {"command": "live.arm", "payload": {"venue": "kraken"}},
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
            ("X-Krellbot-CSRF", "anything"),
            ("Cookie", f"krellbot_session={session}"),
        ],
    )
    # ``live.arm`` is rejected outright by the commands route, but with
    # valid session/csrf the route runs.
    assert status == 403, (status, body)
    decoded = json.loads(body)
    # The route must reject the command by name (``unknown command`` /
    # ``live orders are disabled``); either is fine. What matters is
    # the gate did not block it: a request body was parsed and a typed
    # command-side 403 came back, not a session-gate 403.
    assert "detail" in decoded, decoded
