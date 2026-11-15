"""Fleet pause / disarm + unresolved Operations parity.

Paper commands (`paper.pause_entries`, `paper.resume_entries`,
`paper.disarm`) remain the mutation surface. The armed fleet list
reflects their effects, and unresolved orders stay available on the
existing Operations read path (same closed shape / session gate).

Contract under test:

  1. ``paper.pause_entries`` → fleet row ``entries_paused: true``.
  2. ``paper.resume_entries`` → fleet row ``entries_paused: false``.
  3. ``paper.disarm`` → fleet ``armed: false``, ``deployments: []``.
  4. Unresolved orders route still returns closed rows under the same
     session as fleet (Operations parity for the fleet management view).
  5. Commands still require CSRF; fleet GET stays session-gated.
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
    _post_json,
    _run_paper_arm,
    asgi_call,
)

TEST_PORT = NS06_PORT


# ---- helpers --------------------------------------------------------------


def _get(
    app,
    path: str,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes, list[str]]:
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="GET", path=path, headers=base)


def _bootstrap(app, token: str) -> tuple[str, str]:
    csrf_token = _bootstrap_and_get_csrf(app, token)
    assert csrf_token, csrf_token
    state = app.state.krellbot
    session_value = next(iter(state.sessions.keys()))
    return session_value, csrf_token


def _session_headers(session_value: str, csrf_token: str | None = None) -> list[tuple[str, str]]:
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    if csrf_token is not None:
        headers.append(("X-Krellbot-CSRF", csrf_token))
    return headers


def _read_json(body: bytes) -> dict:
    decoded = json.loads(body)
    assert isinstance(decoded, dict), decoded
    return decoded


def _command(
    app,
    *,
    command: str,
    payload: dict,
    session_value: str,
    csrf_token: str,
) -> tuple[int, dict]:
    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        {
            "schema_version": "1",
            "command": command,
            "correlation_id": f"fleet-{command}",
            "payload": payload,
        },
        headers=_session_headers(session_value, csrf_token),
    )
    return status, _read_json(body)


def _get_fleet(app, session_value: str) -> tuple[int, dict]:
    status, _h, body, _c = _get(
        app,
        "/api/v1/paper/fleet",
        headers=_session_headers(session_value),
    )
    return status, _read_json(body)


def _seed_unresolved(home: Path, *, now: int) -> None:
    from krellbot.storage.database import OperationalStore

    store = OperationalStore(home / "ops.sqlite")
    store.connect()
    with store.transaction() as conn:
        for coid, age, lookup_kind in (
            ("coid-fleet-old", 200, "reconcile_absent"),
            ("coid-fleet-new", 30, None),
        ):
            ts = now - age
            outbox = json.dumps(
                {"coid": coid, "body": "{}", "sent": False, "ts": ts},
                sort_keys=True,
                separators=(",", ":"),
            )
            conn.execute(
                "INSERT INTO ledger (kind, payload) VALUES ('outbox', ?)",
                (outbox,),
            )
            audit = json.dumps(
                {"coid": coid, "ts": ts},
                sort_keys=True,
                separators=(",", ":"),
            )
            conn.execute(
                "INSERT INTO ledger (kind, payload) VALUES ('needs_reconcile', ?)",
                (audit,),
            )
            if lookup_kind is not None:
                lookup = json.dumps(
                    {"coid": coid},
                    sort_keys=True,
                    separators=(",", ":"),
                )
                conn.execute(
                    "INSERT INTO ledger (kind, payload) VALUES (?, ?)",
                    (lookup_kind, lookup),
                )


# ---- pause / resume / disarm via paper commands ↔ fleet ------------------


def test_fleet_pause_entries_reflects_on_fleet_list(home: Path) -> None:
    _run_paper_arm(home)
    token = f"boot-fleet-pause-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf_token = _bootstrap(app, token)

    status, before = _get_fleet(app, session_value)
    assert status == 200, before
    assert before["armed"] is True
    assert before["deployments"][0]["entries_paused"] is False

    cmd_status, cmd_body = _command(
        app,
        command="paper.pause_entries",
        payload={"venue": "kraken", "pair": "SUIUSD"},
        session_value=session_value,
        csrf_token=csrf_token,
    )
    assert cmd_status == 200, cmd_body
    assert cmd_body.get("ok") is True
    assert cmd_body.get("code") == "entries_paused"

    status, after = _get_fleet(app, session_value)
    assert status == 200, after
    assert after["deployments"][0]["entries_paused"] is True
    assert after["deployments"][0]["venue"] == "kraken"
    assert after["deployments"][0]["pair"] == "SUIUSD"


def test_fleet_resume_entries_clears_paused_on_fleet_list(home: Path) -> None:
    _run_paper_arm(home)
    from krellbot.application.paper import PaperService

    assert (
        PaperService(home=home)
        .pause_entries(
            venue="kraken",
            pair="SUIUSD",
            correlation_id="seed-fleet-resume",
        )
        .ok
    )

    token = f"boot-fleet-resume-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf_token = _bootstrap(app, token)

    status, before = _get_fleet(app, session_value)
    assert status == 200, before
    assert before["deployments"][0]["entries_paused"] is True

    cmd_status, cmd_body = _command(
        app,
        command="paper.resume_entries",
        payload={"venue": "kraken", "pair": "SUIUSD"},
        session_value=session_value,
        csrf_token=csrf_token,
    )
    assert cmd_status == 200, cmd_body
    assert cmd_body.get("ok") is True
    assert cmd_body.get("code") == "entries_resumed"

    status, after = _get_fleet(app, session_value)
    assert status == 200, after
    assert after["deployments"][0]["entries_paused"] is False


def test_fleet_disarm_clears_fleet_list(home: Path) -> None:
    _run_paper_arm(home)
    token = f"boot-fleet-disarm-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf_token = _bootstrap(app, token)

    status, before = _get_fleet(app, session_value)
    assert status == 200, before
    assert before["armed"] is True
    assert len(before["deployments"]) == 1

    cmd_status, cmd_body = _command(
        app,
        command="paper.disarm",
        payload={"venue": "kraken", "pair": "SUIUSD"},
        session_value=session_value,
        csrf_token=csrf_token,
    )
    assert cmd_status == 200, cmd_body
    assert cmd_body.get("ok") is True
    assert cmd_body.get("code") == "disarmed"

    status, after = _get_fleet(app, session_value)
    assert status == 200, after
    assert after["armed"] is False
    assert after["deployments"] == []


def test_fleet_pause_requires_csrf(home: Path) -> None:
    _run_paper_arm(home)
    token = f"boot-fleet-csrf-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value, _csrf = _bootstrap(app, token)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        {
            "schema_version": "1",
            "command": "paper.pause_entries",
            "payload": {"venue": "kraken", "pair": "SUIUSD"},
        },
        headers=_session_headers(session_value),
    )
    assert status == 403, (status, body)


# ---- unresolved Operations parity alongside fleet ------------------------


def test_unresolved_orders_parity_alongside_fleet(home: Path) -> None:
    """Fleet management shares the Operations unresolved read path."""

    now = 1_700_000_500
    _run_paper_arm(home)
    _seed_unresolved(home, now=now)

    token = f"boot-fleet-unresolved-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value, _csrf = _bootstrap(app, token)
    session = _session_headers(session_value)

    fleet_status, fleet_body = _get_fleet(app, session_value)
    assert fleet_status == 200, fleet_body
    assert fleet_body["armed"] is True

    status, headers, body, _c = _get(
        app,
        "/api/v1/operations/unresolved-orders",
        headers=session,
    )
    assert status == 200, body
    cache = [value for (name, value) in headers if name.lower() == "cache-control"]
    assert cache == ["no-store"], cache
    payload = _read_json(body)
    assert payload["schema_version"] == "1"
    assert isinstance(payload["orders"], list)
    assert [row["client_order_id"] for row in payload["orders"]] == [
        "coid-fleet-old",
        "coid-fleet-new",
    ]
    first = payload["orders"][0]
    assert set(first) == {"client_order_id", "age_seconds", "last_lookup_result"}
    assert first["last_lookup_result"] == "absent"
    raw = body.decode("utf-8")
    for forbidden in ("starting_cash", "pack_path", "owned_qty", "cap", "stop"):
        assert forbidden not in raw, (forbidden, raw)
