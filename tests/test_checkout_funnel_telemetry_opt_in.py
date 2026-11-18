"""Checkout funnel telemetry stays opt-in (M21.4).

Pins:

  * Default off: view / checkout / install emit nothing.
  * After explicit consent, funnel events post closed payloads only.
  * Payloads never include keys, secrets, session ids, or strategy source.
  * Workstation GET/PUT /api/v1/telemetry mirrors the same consent flag.
  * PAPER_ONLY_RELEASE stays True.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from krellbot import license as kb_license
from krellbot import telemetry as kb_telemetry
from krellbot.application import checkout as checkout_app
from krellbot.release_policy import PAPER_ONLY_RELEASE
from tests.test_ns06_api import (
    TEST_PORT,
    _build_app,
    _post_json,
    asgi_call,
)


class SpyTransport:
    def __init__(self) -> None:
        self.bodies: list[dict] = []
        self.urls: list[str] = []

    def post(self, url: str, body: bytes, headers: dict) -> object:
        self.urls.append(url)
        self.bodies.append(json.loads(body.decode("utf-8")))
        return b"{}"


class _FakeCatalogueTransport:
    def __init__(self, response: dict) -> None:
        self._response = response

    def get(self, url: str, headers: dict | None = None) -> dict:
        return self._response


@pytest.fixture
def catalogue_signing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    keys = tmp_path / "catalogue-keys"
    keys.mkdir()
    pub_line = base64.urlsafe_b64encode(public).rstrip(b"=").decode("ascii")
    (keys / "catalogue-dev.pub").write_text(f"# DEV\n{pub_line}\n", encoding="utf-8")
    monkeypatch.setattr(kb_license, "_KEYS_DIR", keys)

    def sign(document: dict) -> tuple[str, str]:
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"))
        sig = private.sign(payload.encode("utf-8"))
        sig_text = base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")
        return payload, sig_text

    return sign


def _sample_catalogue() -> dict:
    return {
        "catalogue_version": "1",
        "updated": "2026-11-18T00:00:00Z",
        "packs": [
            {
                "id": "free-dual-ma",
                "label": "Free Dual MA",
                "version": "1.0.0",
                "tier": "free",
                "permissions": [],
            },
            {
                "id": "paid-launch-dca",
                "label": "Launch DCA",
                "version": "1.0.0",
                "tier": "paid",
                "permissions": ["catalog"],
            },
        ],
    }


def _session_headers(app) -> list[tuple[str, str]]:
    token = app.state.krellbot.bootstrap_token
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    csrf = decoded["csrf_token"]
    session = next(c for c in cookies if c.startswith("krellbot_session=")).split(";", 1)[0].split("=", 1)[1]
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session}"),
        ("X-Krellbot-CSRF", csrf),
    ]


def _get(app, path: str, headers: list[tuple[str, str]]):
    return asgi_call(
        app,
        method="GET",
        path=path,
        headers=[("Host", f"127.0.0.1:{TEST_PORT}"), *headers],
    )


def _put_json(app, path: str, payload: dict, headers: list[tuple[str, str]]):
    body_bytes = json.dumps(payload).encode("utf-8")
    return asgi_call(
        app,
        method="PUT",
        path=path,
        body=body_bytes,
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body_bytes))),
            *headers,
        ],
    )


def _post(app, path: str, payload: dict, headers: list[tuple[str, str]]):
    body_bytes = json.dumps(payload).encode("utf-8")
    return asgi_call(
        app,
        method="POST",
        path=path,
        body=body_bytes,
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body_bytes))),
            *headers,
        ],
    )


def test_paper_only_release_untouched() -> None:
    assert PAPER_ONLY_RELEASE is True


def test_funnel_off_by_default_sends_nothing(home: Path) -> None:
    spy = SpyTransport()
    kb_telemetry.maybe_send_funnel(home, "view", transport=spy)
    kb_telemetry.maybe_send_funnel(home, "checkout_start", sku="paid-launch-dca", transport=spy)
    assert spy.bodies == []
    assert not (home / "telemetry.json").exists()
    assert kb_telemetry.is_enabled(home) is False
    assert kb_telemetry.status(home)["default_off"] is True
    assert kb_telemetry.status(home)["enabled"] is False


def test_funnel_payload_excludes_secrets_and_strategy_source(home: Path) -> None:
    spy = SpyTransport()
    assert kb_telemetry.set_enabled(home, True)["enabled"] is True
    kb_telemetry.maybe_send_funnel(
        home,
        "checkout_success",
        sku="paid-launch-dca",
        transport=spy,
    )
    assert len(spy.bodies) == 1
    body = spy.bodies[0]
    assert set(body.keys()) == set(kb_telemetry.FUNNEL_PAYLOAD_KEYS)
    assert body["kind"] == "funnel"
    assert body["event"] == "checkout_success"
    assert body["sku"] == "paid-launch-dca"
    assert body["install_id"]
    wire = json.dumps(body).lower()
    for needle in (
        "secret",
        "api_key",
        "password",
        "license",
        "session_id",
        "strategy",
        "pack_bytes",
        "balance",
    ):
        assert needle not in wire
    for forbidden in kb_telemetry.FUNNEL_FORBIDDEN_KEYS:
        assert forbidden not in body


def test_funnel_rejects_path_shaped_sku(home: Path) -> None:
    spy = SpyTransport()
    kb_telemetry.set_enabled(home, True)
    kb_telemetry.maybe_send_funnel(
        home,
        "install",
        sku="../secret/strategy.py",
        transport=spy,
    )
    assert spy.bodies[0]["sku"] == ""


def test_telemetry_consent_api_default_off_and_enable(home: Path) -> None:
    app = _build_app(home)
    headers = _session_headers(app)

    status, _h, body, _c = _get(app, "/api/v1/telemetry", headers)
    assert status == 200, body
    payload = json.loads(body)
    assert payload["enabled"] is False
    assert payload["default_off"] is True
    assert payload["funnel_events"] == list(kb_telemetry.FUNNEL_EVENTS)
    assert "opt-in" in payload["disclosure"].lower() or "default" in payload["disclosure"].lower()
    assert "install_id" not in payload
    assert "key" not in payload
    assert "secret" not in payload

    status, _h, body, _c = _put_json(app, "/api/v1/telemetry", {"enabled": True}, headers)
    assert status == 200, body
    payload = json.loads(body)
    assert payload["enabled"] is True
    assert payload["ok"] is True
    assert kb_telemetry.is_enabled(home) is True


def test_checkout_funnel_emits_only_when_opted_in(
    home: Path,
    catalogue_signing,
) -> None:
    document = _sample_catalogue()
    payload, sig = catalogue_signing(document)

    app = _build_app(home)
    spy = SpyTransport()
    app.state.krellbot.catalogue_transport = _FakeCatalogueTransport({"payload": payload, "sig": sig})
    app.state.krellbot.checkout_transport = checkout_app.FakePaymentTransport(outcome="paid")
    app.state.krellbot.telemetry_transport = spy
    headers = _session_headers(app)

    # Default off — catalogue view + checkout produce no telemetry.
    status, _h, body, _c = _get(app, "/api/v1/catalogue", headers)
    assert status == 200, body
    status, _h, body, _c = _post(app, "/api/v1/checkout/start", {"sku": "paid-launch-dca"}, headers)
    assert status == 200, body
    assert json.loads(body)["status"] == "paid"
    assert spy.bodies == []

    # Opt in via API consent (checkout UI path). Consent write does not send.
    status, _h, body, _c = _put_json(app, "/api/v1/telemetry", {"enabled": True}, headers)
    assert status == 200, body
    assert spy.bodies == []

    status, _h, body, _c = _get(app, "/api/v1/catalogue", headers)
    assert status == 200, body
    status, _h, body, _c = _post(app, "/api/v1/checkout/start", {"sku": "paid-launch-dca"}, headers)
    assert status == 200, body
    assert json.loads(body)["status"] == "paid"

    events = [row["event"] for row in spy.bodies]
    assert events == ["view", "checkout_start", "checkout_success"]
    for row in spy.bodies:
        assert set(row.keys()) == set(kb_telemetry.FUNNEL_PAYLOAD_KEYS)
        assert row["kind"] == "funnel"
        assert "session_id" not in row
        wire = json.dumps(row).lower()
        assert "secret" not in wire
        assert "strategy" not in wire

    status, _h, body, _c = _post(app, "/api/v1/packs/install", {"pack_id": "free-dual-ma"}, headers)
    assert status == 200, body
    assert spy.bodies[-1]["event"] == "install"
    assert spy.bodies[-1]["sku"] == "free-dual-ma"


def test_failed_checkout_emits_checkout_fail_when_enabled(home: Path) -> None:
    kb_license.write_catalogue_cache(home, _sample_catalogue())
    kb_telemetry.set_enabled(home, True)
    spy = SpyTransport()
    app = _build_app(home)
    app.state.krellbot.checkout_transport = checkout_app.FakePaymentTransport(outcome="failed")
    app.state.krellbot.telemetry_transport = spy
    headers = _session_headers(app)

    status, _h, body, _c = _post(app, "/api/v1/checkout/start", {"sku": "paid-launch-dca"}, headers)
    assert status == 200, body
    assert json.loads(body)["status"] == "failed"
    events = [row["event"] for row in spy.bodies]
    assert events == ["checkout_start", "checkout_fail"]
    assert all(row["sku"] == "paid-launch-dca" for row in spy.bodies)


def test_docs_disclose_funnel_opt_in() -> None:
    docs = Path("docs/telemetry.md").read_text(encoding="utf-8")
    lowered = docs.lower()
    for needle in (
        "opt-in",
        "default",
        "view",
        "checkout_start",
        "checkout_success",
        "checkout_fail",
        "install",
        "arm",
        "strategy source",
        "session id",
    ):
        assert needle in lowered
