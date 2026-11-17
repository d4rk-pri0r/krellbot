"""Demo/fixture seed honesty — opt-in labeled preview only (M18.5).

Pins that the seed defaults off, requires confirm, labels fixture/demo,
and refuses live_performance / soak_proof claims. Isolated KRELLBOT_HOME;
no exchange credentials or real orders.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from krellbot.application import demo_fixture_seed as seed
from tests.test_ns06_api import (
    TEST_PORT as NS06_PORT,
)
from tests.test_ns06_api import (
    _bootstrap_and_get_csrf,
    _build_app,
    asgi_call,
)

TEST_PORT = NS06_PORT


def _bootstrap(app, token: str) -> tuple[str, str]:
    csrf_token = _bootstrap_and_get_csrf(app, token)
    assert csrf_token, csrf_token
    state = app.state.krellbot
    session_value = next(iter(state.sessions.keys()))
    return session_value, csrf_token


def _headers(session_value: str, csrf_token: str | None = None) -> list[tuple[str, str]]:
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    if csrf_token is not None:
        headers.append(("X-Krellbot-CSRF", csrf_token))
    return headers


def test_fresh_home_stays_empty_and_honest(tmp_path: Path) -> None:
    status = seed.get_status(tmp_path)
    assert status["enabled"] is False
    assert status["deployments"] == []
    assert status["live_performance"] is False
    assert status["soak_proof"] is False
    assert status["is_fixture"] is False
    seed.assert_not_live_or_soak(status)
    assert not (tmp_path / "demo_fixture.json").exists()


def test_seed_requires_confirm_and_labels_fixture(tmp_path: Path) -> None:
    refused = seed.seed(tmp_path, confirm=False)
    assert refused["ok"] is False
    assert refused["code"] == "confirm_required"
    assert refused["enabled"] is False
    assert seed.get_status(tmp_path)["enabled"] is False

    enabled = seed.seed(tmp_path, confirm=True)
    assert enabled["ok"] is True
    assert enabled["enabled"] is True
    assert enabled["is_fixture"] is True
    assert enabled["badge"] == seed.FIXTURE_BADGE
    assert enabled["label"] == seed.FIXTURE_LABEL
    assert "fixture" in (enabled["label"] or "").lower() or "demo" in (enabled["label"] or "").lower()
    assert enabled["live_performance"] is False
    assert enabled["soak_proof"] is False
    assert len(enabled["deployments"]) >= 1
    for row in enabled["deployments"]:
        assert row["is_fixture"] is True
        assert row["live_performance"] is False
        assert row["soak_proof"] is False
        assert "fixture" in row["id"] or "demo" in row["label"].lower()
    seed.assert_not_live_or_soak(enabled)

    # Tampered file cannot flip honesty bits on read.
    path = tmp_path / "demo_fixture.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["live_performance"] = True
    raw["soak_proof"] = True
    for row in raw.get("deployments", []):
        row["live_performance"] = True
        row["soak_proof"] = True
        row["is_fixture"] = False
    path.write_text(json.dumps(raw), encoding="utf-8")
    projected = seed.get_status(tmp_path)
    seed.assert_not_live_or_soak(projected)
    assert projected["live_performance"] is False
    assert projected["soak_proof"] is False


def test_clear_restores_empty_honest_default(tmp_path: Path) -> None:
    seed.seed(tmp_path, confirm=True)
    assert seed.get_status(tmp_path)["enabled"] is True
    cleared = seed.clear(tmp_path)
    assert cleared["ok"] is True
    assert cleared["enabled"] is False
    assert cleared["deployments"] == []
    assert seed.get_status(tmp_path)["enabled"] is False
    assert not (tmp_path / "demo_fixture.json").exists()


def test_api_demo_fixture_seed_honesty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    token = f"boot-demo-fixture-{tmp_path.name}"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value, csrf = _bootstrap(app, token)

    status, _hdrs, body, _cookies = asgi_call(
        app,
        method="GET",
        path="/api/v1/demo-fixture",
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            *_headers(session_value),
        ],
    )
    assert status == 200
    payload = json.loads(body.decode("utf-8"))
    assert payload["enabled"] is False
    assert payload["live_performance"] is False
    assert payload["soak_proof"] is False

    refuse_body = b'{"confirm":false}'
    status, _hdrs, body, _cookies = asgi_call(
        app,
        method="POST",
        path="/api/v1/demo-fixture/seed",
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(refuse_body))),
            *_headers(session_value, csrf),
        ],
        body=refuse_body,
    )
    assert status == 400
    refused = json.loads(body.decode("utf-8"))
    assert refused["ok"] is False
    assert refused["code"] == "confirm_required"

    seed_body = b'{"confirm":true}'
    status, _hdrs, body, _cookies = asgi_call(
        app,
        method="POST",
        path="/api/v1/demo-fixture/seed",
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(seed_body))),
            *_headers(session_value, csrf),
        ],
        body=seed_body,
    )
    assert status == 200
    seeded = json.loads(body.decode("utf-8"))
    assert seeded["ok"] is True
    assert seeded["enabled"] is True
    assert seeded["is_fixture"] is True
    assert seeded["live_performance"] is False
    assert seeded["soak_proof"] is False
    assert seeded["badge"]
    assert "fixture" in seeded["badge"].lower() or "demo" in seeded["badge"].lower()

    status, _hdrs, body, _cookies = asgi_call(
        app,
        method="POST",
        path="/api/v1/demo-fixture/clear",
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
            ("Content-Length", "2"),
            *_headers(session_value, csrf),
        ],
        body=b"{}",
    )
    assert status == 200
    cleared = json.loads(body.decode("utf-8"))
    assert cleared["ok"] is True
    assert cleared["enabled"] is False
    assert cleared["deployments"] == []
