"""Paper owned position — read-only ``GET /api/v1/paper/position`` contract.

The Python half is the contract for the Paper surface's owned-position
sentence:

  1. The route uses the same session gate as
     ``GET /api/v1/paper/status`` (``_gate_get``): a missing session
     cookie is 403, a non-loopback Origin is 403, a non-loopback Host is
     403, and no CSRF header is required.
  2. With no pack armed the body is the closed shape
     ``{"schema_version": "1", "armed": false}``.
  3. With a pack armed the body is the closed projection
     ``free_cash`` + ``holdings`` read verbatim from the persisted
     ``<home>/run/paper-<venue>.json`` state, plus ``as_of_run``.
  4. After a fill (seeded exactly as the paper venue writes it) the
     holdings row and the free-cash decimal string survive the read
     byte-for-byte.
  5. After a backend restart (fresh app over the same home) the same
     values are re-read from the state file.
  6. After disarm the body is the unarmed closed shape again; after a
     re-arm over the preserved state file the position is back.
  7. With no state file yet the armed body carries ``free_cash: "0"``
     and no holdings, never a malformed projection.

All data lives under an isolated ``KRELLBOT_HOME`` (``tmp_path``). No
live venue, key, or order is touched; the state file is seeded exactly
as the engine writes it.
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
    _run_paper_arm,
    asgi_call,
)

TEST_PORT = NS06_PORT


# ---- helpers --------------------------------------------------------------


def _seed_paper_state(home: Path, venue: str, *, balances: dict, fills: list[dict]) -> None:
    """Seed ``<home>/run/paper-<venue>.json`` as the paper venue writes it."""

    run_dir = home / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    body = {
        "venue": venue,
        "balances": balances,
        "open_orders": [],
        "recent_fills": fills,
        "seeded": True,
    }
    (run_dir / f"paper-{venue}.json").write_text(
        json.dumps(body, sort_keys=True),
        encoding="utf-8",
    )


def _fill(coid: str, pair: str, side: str = "buy", ts_ms: int = 1_000) -> dict:
    return {
        "id": coid,
        "coid": coid,
        "pair": pair,
        "side": side,
        "qty": "62.538182660",
        "price": "4.0143",
        "ts_ms": ts_ms,
    }


def _bootstrap_session(app, token: str) -> str:
    _csrf = _bootstrap_and_get_csrf(app, token)
    state = app.state.krellbot
    return next(iter(state.sessions.keys()))


def _get_position(
    app,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes]:
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    status, flat, body, _set_cookies = asgi_call(
        app, method="GET", path="/api/v1/paper/position", headers=base
    )
    return status, flat, body


def _authenticated_headers(session_value: str) -> list[tuple[str, str]]:
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]


def _read_json(body: bytes) -> dict:
    decoded = json.loads(body)
    assert isinstance(decoded, dict), decoded
    return decoded


# ---- 1. session gate parity ----------------------------------------------


def test_paper_position_without_session_cookie_is_403(home: Path) -> None:
    """``GET /api/v1/paper/position`` without a session cookie is 403."""

    app = _build_app(home)
    status, _h, _b = _get_position(
        app,
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, status


def test_paper_position_with_non_loopback_origin_is_403(home: Path) -> None:
    """A non-loopback Origin is 403 even with a valid session."""

    token = "boot-position-origin"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, _b = _get_position(
        app,
        headers=[
            ("Origin", "http://evil.example.com"),
            ("Cookie", f"krellbot_session={session_value}"),
        ],
    )
    assert status == 403, status


def test_paper_position_with_non_loopback_host_is_403(home: Path) -> None:
    """A non-loopback Host is 403."""

    app = _build_app(home)
    status, _h, _b = _get_position(
        app,
        headers=[
            ("Host", "evil.example.com"),
            ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ],
    )
    assert status == 403, status


def test_paper_position_does_not_require_csrf_header(home: Path) -> None:
    """GET gate parity with ``/api/v1/paper/status``: no CSRF required."""

    token = "boot-position-no-csrf"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    headers = _authenticated_headers(session_value)
    headers.append(("X-Krellbot-CSRF", "not-the-real-csrf"))
    status, _h, body = _get_position(app, headers=headers)
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["armed"] is False, decoded


# ---- 2. no pack armed → closed shape --------------------------------------


def test_paper_position_with_no_armed_pack_returns_closed_shape(home: Path) -> None:
    """When no pack is armed the body is exactly the unarmed closed shape."""

    token = "boot-position-empty"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_position(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded == {"schema_version": "1", "armed": False}, decoded


# ---- 3. armed + state file → closed projection -----------------------------


def test_paper_position_returns_free_cash_and_holdings_verbatim(home: Path) -> None:
    """The armed body quotes the persisted state file byte-for-byte."""

    _run_paper_arm(home)
    _seed_paper_state(
        home,
        "kraken",
        balances={"USD": "748.874640020", "SUI": "62.538182660"},
        fills=[_fill("coid-entry-1", "SUIUSD")],
    )
    token = "boot-position-filled"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_position(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)

    assert decoded["schema_version"] == "1", decoded
    assert decoded["armed"] is True, decoded
    assert decoded["venue"] == "kraken", decoded
    assert decoded["pair"] == "SUIUSD", decoded
    assert decoded["mode"] == "paper", decoded
    # The decimal strings are verbatim from the state file: the full
    # precision survives, never re-formatted or zero-trimmed.
    assert decoded["free_cash"] == "748.874640020", decoded
    assert decoded["holdings"] == [{"symbol": "SUI", "qty": "62.538182660"}], decoded


def test_paper_position_after_fill_carries_the_base_holding(home: Path) -> None:
    """After a buy fill the quote balance drops and the base appears."""

    _run_paper_arm(home)
    # The paper venue seeds the starting cash on its first tick; a fill
    # then moves quote into base. The state below is exactly what the
    # venue persists after one buy of 62.538182660 SUI at 4.0143 from
    # 1000 USD (fee charged on the quote side).
    _seed_paper_state(
        home,
        "kraken",
        balances={"USD": "748.874640020", "SUI": "62.538182660"},
        fills=[_fill("coid-entry-1", "SUIUSD", side="buy")],
    )
    token = "boot-position-after-fill"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_position(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    holdings = {row["symbol"]: row["qty"] for row in decoded["holdings"]}
    assert holdings == {"SUI": "62.538182660"}, decoded
    assert decoded["free_cash"] == "748.874640020", decoded


def test_paper_position_after_restart_reads_the_same_state_file(home: Path) -> None:
    """A fresh app over the same home (backend PID restarted, state file
    preserved) re-reads the identical owned position."""

    _run_paper_arm(home)
    _seed_paper_state(
        home,
        "kraken",
        balances={"USD": "748.874640020", "SUI": "62.538182660"},
        fills=[_fill("coid-entry-1", "SUIUSD")],
    )
    token_one = "boot-position-restart-1"
    app_one = _build_app(home, bootstrap_token=token_one)
    session_one = _bootstrap_session(app_one, token_one)
    _s, _h, body_one = _get_position(app_one, headers=_authenticated_headers(session_one))
    first = _read_json(body_one)

    # "Restart": a brand-new app instance — fresh sessions, same home —
    # reads the same state file back.
    token_two = "boot-position-restart-2"
    app_two = _build_app(home, bootstrap_token=token_two)
    session_two = _bootstrap_session(app_two, token_two)
    _s, _h, body_two = _get_position(app_two, headers=_authenticated_headers(session_two))
    second = _read_json(body_two)

    assert second == first, (first, second)
    assert second["free_cash"] == "748.874640020", second
    assert second["holdings"] == [{"symbol": "SUI", "qty": "62.538182660"}], second


def test_paper_position_after_disarm_then_rearm_over_preserved_state(home: Path) -> None:
    """Disarm returns the unarmed closed shape; a re-arm over the same
    preserved state file re-surfaces the owned position."""

    _run_paper_arm(home)
    _seed_paper_state(
        home,
        "kraken",
        balances={"USD": "748.874640020", "SUI": "62.538182660"},
        fills=[_fill("coid-entry-1", "SUIUSD")],
    )

    from krellbot.application.paper import PaperService

    PaperService(home=home).disarm(venue="kraken", pair="SUIUSD", correlation_id="seed-disarm")

    token_one = "boot-position-disarmed"
    app_one = _build_app(home, bootstrap_token=token_one)
    session_one = _bootstrap_session(app_one, token_one)
    status, _h, body = _get_position(app_one, headers=_authenticated_headers(session_one))
    assert status == 200, (status, body)
    assert _read_json(body) == {"schema_version": "1", "armed": False}, body

    # Re-arm over the preserved state file: the owned position is back.
    _run_paper_arm(home)
    token_two = "boot-position-rearmed"
    app_two = _build_app(home, bootstrap_token=token_two)
    session_two = _bootstrap_session(app_two, token_two)
    status, _h, body_two = _get_position(app_two, headers=_authenticated_headers(session_two))
    assert status == 200, (status, body_two)
    decoded = _read_json(body_two)
    assert decoded["armed"] is True, decoded
    assert decoded["free_cash"] == "748.874640020", decoded
    assert decoded["holdings"] == [{"symbol": "SUI", "qty": "62.538182660"}], decoded


# ---- 4. empty state --------------------------------------------------------


def test_paper_position_armed_with_no_state_file_is_zero_cash(home: Path) -> None:
    """Armed but the engine has not ticked yet (no state file): the body
    is a well-formed zero projection, never a malformed one."""

    _run_paper_arm(home)
    token = "boot-position-no-state"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_position(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["armed"] is True, decoded
    assert decoded["free_cash"] == "0", decoded
    assert decoded["holdings"] == [], decoded


def test_paper_position_omits_zero_and_negative_holdings(home: Path) -> None:
    """Only balances above zero are holdings; the quote asset is never a
    holding row."""

    _run_paper_arm(home)
    _seed_paper_state(
        home,
        "kraken",
        balances={"USD": "1000", "SUI": "0", "BTC": "-1"},
        fills=[],
    )
    token = "boot-position-zero-holdings"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_position(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["holdings"] == [], decoded
    assert decoded["free_cash"] == "1000", decoded


def test_paper_position_is_served_no_store(home: Path) -> None:
    """The projection is fresh evidence, never a cacheable response."""

    token = "boot-position-no-store"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    _status, headers, _body = _get_position(
        app, headers=_authenticated_headers(session_value)
    )
    cache_control = [value for name, value in headers if name.lower() == "cache-control"]
    assert cache_control == ["no-store"], cache_control


def test_paper_position_path_appears_in_openapi(home: Path) -> None:
    """The route is listed in the generated OpenAPI document."""

    from tests.test_ns06_api import _default_host_header

    app = _build_app(home)
    status, _h, body, _c = asgi_call(
        app, method="GET", path="/openapi.json", headers=_default_host_header()
    )
    assert status == 200, status
    paths = _read_json(body).get("paths") or {}
    assert "/api/v1/paper/position" in paths, sorted(paths.keys())
