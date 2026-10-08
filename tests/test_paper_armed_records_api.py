"""Paper armed records list — ``GET /api/v1/paper/armed``.

The paper_status route returns only the first armed record, so a
workstation with packs armed on more than one venue/pair cannot see
them all. This route is the closed-shape list view: one row per armed
record from ``kb_config.load_config(s.home).armed``.

Contract under test:

  1. Same session gate as ``GET /api/v1/paper/status`` (``_gate_get``):
     a request without a session cookie is refused, and so is one with
     a non-loopback Origin or Host.
  2. With armed records present the body returns ``armed: true`` plus
     one closed row per record — venue, pair, mode, pack_id,
     entries_paused — for every record, not just the first.
  3. With no armed records the body is ``{"schema_version": "1",
     "armed": false, "records": []}``.
  4. The body never carries ``starting_cash`` (cash), ``owned_qty``
     (quantity), ``stop``, ``cap``, or ``pack_path`` — not as keys and
     not anywhere in the serialised body.
  5. The response is marked ``Cache-Control: no-store``.
"""

from __future__ import annotations

import json
from decimal import Decimal
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


def _get_paper_armed(
    app,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes, list[str]]:
    """Issue ``GET /api/v1/paper/armed`` against ``app``."""

    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="GET", path="/api/v1/paper/armed", headers=base)


def _bootstrap_session_cookie(app, token: str) -> str:
    """Redeem ``token`` on ``app`` and return the session cookie value."""

    csrf_token = _bootstrap_and_get_csrf(app, token)
    assert csrf_token, csrf_token
    state = app.state.krellbot
    return next(iter(state.sessions.keys()))


def _session_headers(session_value: str) -> list[tuple[str, str]]:
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]


def _write_pack(home: Path, *, pack_id: str, venue: str, pair: str) -> Path:
    """Write a runnable DSL pack under <home>/packs/ for ``venue``/``pair``."""

    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": pack_id,
        "author": "krellbot paper armed records tests",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": venue, "pair": pair}],
    }
    target = packs / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm(home: Path, pack_path: Path, *, venue: str, pair: str) -> None:
    """Arm one pack through the paper service boundary."""

    from krellbot.application.paper import PaperService

    result = PaperService(home=home).arm(
        pack_path,
        venue=venue,
        mode="paper",
        paper_balance=Decimal(1000),
        correlation_id="seed-armed-records",
    )
    assert result.ok, result.message


def _read_json(body: bytes) -> dict:
    decoded = json.loads(body)
    assert isinstance(decoded, dict), decoded
    return decoded


# ---- 1. session gate ------------------------------------------------------


def test_paper_armed_requires_a_session(home: Path) -> None:
    """No session cookie is 403 — the route does not run unauthenticated."""

    app = _build_app(home)
    status, _h, _b, _c = _get_paper_armed(
        app,
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, status


def test_paper_armed_refuses_non_loopback_origin(home: Path) -> None:
    """A non-loopback Origin is 403 even with a valid session."""

    token = f"boot-armed-origin-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    headers = [
        ("Origin", "http://evil.example.com"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    status, _h, _b, _c = _get_paper_armed(app, headers=headers)
    assert status == 403, status


def test_paper_armed_refuses_non_loopback_host(home: Path) -> None:
    """A non-loopback Host header is 403."""

    app = _build_app(home)
    headers = [
        ("Host", "evil.example.com"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
    ]
    status, _h, _b, _c = _get_paper_armed(app, headers=headers)
    assert status == 403, status


def test_paper_armed_does_not_leak_through_gate_on_a_fresh_app(home: Path) -> None:
    """A fresh app without a redeemed token serves no session at all, so
    the route is unreachable without the bootstrap handshake."""

    app = _build_app(home)
    status, _h, body, _c = _get_paper_armed(
        app,
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, (status, body)


# ---- 2. the closed list body ---------------------------------------------


def test_paper_armed_returns_every_record_not_just_the_first(home: Path) -> None:
    """Two armed records on different venue/pair appear as two rows.

    This is the gap the route exists to close: ``GET /api/v1/paper/status``
    returns only ``config.armed[0]``.
    """

    first = _write_pack(home, pack_id="trend-follow", venue="kraken", pair="SUIUSD")
    _arm(home, first, venue="kraken", pair="SUIUSD")
    second = _write_pack(home, pack_id="mean-revert", venue="coinbase", pair="BTC-USD")
    _arm(home, second, venue="coinbase", pair="BTC-USD")

    from krellbot.config import load_config

    config = load_config(home)
    assert len(config.armed) == 2, config.armed

    token = f"boot-armed-two-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_paper_armed(
        app, headers=_session_headers(session_value)
    )
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded.get("schema_version") == "1", decoded
    assert decoded.get("armed") is True, decoded
    records = decoded.get("records")
    assert isinstance(records, list), decoded
    assert len(records) == 2, decoded
    assert records[0] == {
        "venue": "kraken",
        "pair": "SUIUSD",
        "mode": "paper",
        "pack_id": "trend-follow",
        "entries_paused": False,
    }, records[0]
    assert records[1] == {
        "venue": "coinbase",
        "pair": "BTC-USD",
        "mode": "paper",
        "pack_id": "mean-revert",
        "entries_paused": False,
    }, records[1]


def test_paper_armed_returns_closed_records_from_load_config(home: Path) -> None:
    """The rows come from ``kb_config.load_config(s.home).armed`` — the
    same source the status route reads — with the same closed field set.
    """

    _run_paper_arm(home)
    token = f"boot-armed-one-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_paper_armed(
        app, headers=_session_headers(session_value)
    )
    assert status == 200, (status, body)
    decoded = _read_json(body)
    records = decoded["records"]
    assert len(records) == 1, decoded
    assert records[0] == {
        "venue": "kraken",
        "pair": "SUIUSD",
        "mode": "paper",
        "pack_id": "trend-follow",
        "entries_paused": False,
    }, records[0]


def test_paper_armed_reflects_entries_paused_per_row(home: Path) -> None:
    """``entries_paused`` is a per-row bool that tracks the on-disk record."""

    _run_paper_arm(home)
    from krellbot.application.paper import PaperService

    PaperService(home=home).pause_entries(
        venue="kraken", pair="SUIUSD", correlation_id="seed-pause-list"
    )
    token = f"boot-armed-paused-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_paper_armed(
        app, headers=_session_headers(session_value)
    )
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["records"][0]["entries_paused"] is True, decoded


# ---- 3. no armed records → armed=false -----------------------------------


def test_paper_armed_with_no_records_returns_armed_false(home: Path) -> None:
    """With an empty armed list the body is the closed empty shape."""

    token = f"boot-armed-empty-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_paper_armed(
        app, headers=_session_headers(session_value)
    )
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded == {
        "schema_version": "1",
        "armed": False,
        "records": [],
    }, decoded


def test_paper_armed_reports_armed_false_after_disarm(home: Path) -> None:
    """Disarming the last record flips the list back to armed=false."""

    _run_paper_arm(home)
    from krellbot.application.paper import PaperService

    result = PaperService(home=home).disarm(
        venue="kraken", pair="SUIUSD", correlation_id="seed-disarm-list"
    )
    assert result.ok, result.message
    token = f"boot-armed-disarmed-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_paper_armed(
        app, headers=_session_headers(session_value)
    )
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["armed"] is False, decoded
    assert decoded["records"] == [], decoded


# ---- 4. no-leak: the closed row never carries cash / qty / stop / cap / path


def test_paper_armed_omits_cash_qty_stop_cap_and_path(home: Path) -> None:
    """The row is the closed field set only. Cash (``starting_cash``),
    quantity (``owned_qty``), stop, cap, and the pack path never
    appear — not as row keys and not anywhere in the body.
    """

    _run_paper_arm(home)
    token = f"boot-armed-no-leak-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_paper_armed(
        app, headers=_session_headers(session_value)
    )
    assert status == 200, (status, body)
    decoded = _read_json(body)
    for row in decoded["records"]:
        leaked = sorted(
            field
            for field in (
                "starting_cash",
                "owned_qty",
                "stop",
                "cap",
                "pack_path",
            )
            if field in row
        )
        assert leaked == [], (leaked, row)
    raw = body.decode("utf-8")
    for needle in ("starting_cash", "owned_qty", "stop", "cap", "pack_path"):
        assert needle not in raw, (needle, raw)


# ---- 5. response hygiene --------------------------------------------------


def test_paper_armed_is_no_store(home: Path) -> None:
    """The list is never cached: ``Cache-Control: no-store``."""

    _run_paper_arm(home)
    token = f"boot-armed-store-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, headers, _b, _c = _get_paper_armed(
        app, headers=_session_headers(session_value)
    )
    assert status == 200, status
    cache_control = [
        value for (name, value) in headers if name.lower() == "cache-control"
    ]
    assert cache_control, headers
    assert cache_control[0].lower() == "no-store", cache_control


def test_paper_armed_coexists_with_paper_status(home: Path) -> None:
    """The single-record status route is unchanged: both routes answer
    200 for the same armed workstation, and the status body keeps its
    existing closed single-record shape.
    """

    _run_paper_arm(home)
    token = f"boot-armed-coexist-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    headers = _session_headers(session_value)

    s_armed, _h1, body_armed, _c1 = _get_paper_armed(app, headers=headers)
    assert s_armed == 200, s_armed
    decoded_armed = _read_json(body_armed)
    assert decoded_armed["armed"] is True, decoded_armed

    s_status, _h2, body_status, _c2 = asgi_call(
        app,
        method="GET",
        path="/api/v1/paper/status",
        headers=[("Host", f"127.0.0.1:{TEST_PORT}")] + headers,
    )
    assert s_status == 200, (s_status, body_status)
    decoded_status = _read_json(body_status)
    assert decoded_status == {
        "schema_version": "1",
        "armed": True,
        "venue": "kraken",
        "pair": "SUIUSD",
        "entries_paused": False,
        "mode": "paper",
        "pack_id": "trend-follow",
    }, decoded_status


def test_paper_armed_path_appears_in_openapi(home: Path) -> None:
    """The new route is listed in the generated OpenAPI document."""

    app = _build_app(home)
    status, _h, body, _c = asgi_call(
        app,
        method="GET",
        path="/openapi.json",
        headers=[("Host", f"127.0.0.1:{TEST_PORT}")],
    )
    assert status == 200, status
    decoded = _read_json(body)
    paths = decoded.get("paths") or {}
    assert "/api/v1/paper/armed" in paths, sorted(paths.keys())
