"""Referral / fee-share attribution with fake transport (M23.1).

Pins:

* Disclosure copy matches product-direction earn rule (1).
* Local receipt is written under ``$KRELLBOT_HOME/receipts/``.
* Server attribution uses an injectable transport; ``FakeTransport``
  records posts and never egresses.
* Unreachable server still leaves a local receipt.
* Unknown kinds are refused without posting.
* Loopback GET/POST API is session-gated like notifications.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from krellbot import referral as kb_referral

TEST_PORT = 8080


# ---- ASGI helpers (same idiom as test_opt_in_notifications) ----------------


def _ascii_headers(headers: list[tuple[str, str]]) -> list[tuple[bytes, bytes]]:
    return [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in headers]


def asgi_call(
    app,
    *,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes, list[str]]:
    body = body if body is not None else b""
    headers = list(headers or [])
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    captured: dict[str, object] = {"status": 500, "headers": [], "body": bytearray()}

    async def send(message: dict[str, object]) -> None:
        mtype = message["type"]
        if mtype == "http.response.start":
            captured["status"] = int(message["status"])
            captured["headers"] = list(message.get("headers", []))
        elif mtype == "http.response.body":
            captured["body"] = captured["body"] + message.get("body", b"")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("latin-1"),
        "query_string": b"",
        "server": ("127.0.0.1", 0),
        "client": ("127.0.0.1", 12345),
        "headers": _ascii_headers(headers),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))

    flat: list[tuple[str, str]] = []
    set_cookies: list[str] = []
    for name_b, value_b in captured["headers"]:
        name = name_b.decode("latin-1")
        value = value_b.decode("latin-1")
        if name.lower() == "set-cookie":
            set_cookies.append(value)
        else:
            flat.append((name, value))
    return int(captured["status"]), flat, bytes(captured["body"]), set_cookies


def _origin() -> list[tuple[str, str]]:
    return [("Origin", f"http://127.0.0.1:{TEST_PORT}")]


def _build_app(home: Path, *, bootstrap_token: str = "boot-referral"):
    from krellbot.api.app import create_app

    return create_app(home=home, port=TEST_PORT, bootstrap_token=bootstrap_token)


def _post_json(app, path: str, payload: dict, headers: list[tuple[str, str]] | None = None):
    body = json.dumps(payload).encode("utf-8")
    base = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="POST", path=path, body=body, headers=base)


def _get(app, path: str, headers: list[tuple[str, str]] | None = None):
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="GET", path=path, headers=base)


def _bootstrap(app, token: str = "boot-referral") -> list[tuple[str, str]]:
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_origin(),
    )
    assert status == 200, body
    decoded = json.loads(body)
    csrf = decoded["csrf_token"]
    cookie = next(c for c in cookies if c.startswith("krellbot_session="))
    session_value = cookie.split(";", 1)[0].split("=", 1)[1]
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session_value}"),
    ]


# ---- Disclosure + module ---------------------------------------------------


def test_disclosure_matches_product_direction_earn_rule_one() -> None:
    disc = kb_referral.disclosure()
    assert disc["headline"] == "Exchange fee share / referral"
    assert "creates or links an exchange account" in disc["body"]
    assert "Krellbot referral path" in disc["body"]
    assert disc["earn_rule"] == "1"
    assert "fee share / referral" in disc["packs_body"].lower()

    product = Path("docs/product-direction.md").read_text(encoding="utf-8")
    assert disc["headline"] in product
    assert "disclosed attribution when an" in product.lower()
    assert "referral path" in product


def test_exchange_signup_writes_local_receipt_and_posts_via_fake_transport(
    home: Path,
) -> None:
    fake = kb_referral.FakeTransport()
    outcome = kb_referral.attribute(
        home,
        kind="exchange_signup",
        venue="kraken",
        transport=fake,
        now=1_700_000_000,
        receipt_id="rcpt-exchange-1",
    )
    assert outcome.ok is True
    assert outcome.server_posted is True
    assert outcome.message == "attribution recorded"
    assert outcome.receipt_id == "rcpt-exchange-1"

    assert len(fake.posts) == 1
    posted = fake.posts[0]
    assert posted["url"].endswith("/api/referral/attribute")
    body = json.loads(posted["body"].decode("utf-8"))
    assert body["kind"] == "exchange_signup"
    assert body["venue"] == "kraken"
    assert body["receipt_id"] == "rcpt-exchange-1"
    assert body["disclosure"] == kb_referral.DISCLOSURE_HEADLINE
    assert "key" not in body
    assert "secret" not in body
    assert "license" not in body

    receipts = kb_referral.list_receipts(home)
    assert len(receipts) == 1
    assert receipts[0]["receipt_id"] == "rcpt-exchange-1"
    assert receipts[0]["server_posted"] is True
    on_disk = (home / "receipts" / kb_referral.RECEIPTS_FILE).read_text(encoding="utf-8")
    assert "rcpt-exchange-1" in on_disk


def test_pack_purchase_attribution_via_fake_transport(home: Path) -> None:
    fake = kb_referral.FakeTransport()
    outcome = kb_referral.attribute(
        home,
        kind="pack_purchase",
        pack_id="krell.alpha.connector",
        transport=fake,
        now=1_700_000_100,
        receipt_id="rcpt-pack-1",
    )
    assert outcome.ok is True
    assert outcome.server_posted is True
    body = json.loads(fake.posts[0]["body"].decode("utf-8"))
    assert body["kind"] == "pack_purchase"
    assert body["pack_id"] == "krell.alpha.connector"


def test_unreachable_server_still_leaves_local_receipt(home: Path) -> None:
    fake = kb_referral.FakeTransport(raise_unreachable=True)
    outcome = kb_referral.attribute(
        home,
        kind="exchange_signup",
        venue="coinbase",
        transport=fake,
        receipt_id="rcpt-local-only",
    )
    assert outcome.ok is True
    assert outcome.server_posted is False
    assert outcome.message == "attribution recorded locally; server unreachable"
    assert fake.posts == []
    receipts = kb_referral.list_receipts(home)
    assert len(receipts) == 1
    assert receipts[0]["receipt_id"] == "rcpt-local-only"
    assert receipts[0]["server_posted"] is False


def test_unknown_kind_refused_without_posting(home: Path) -> None:
    fake = kb_referral.FakeTransport()
    outcome = kb_referral.attribute(home, kind="ads", transport=fake)
    assert outcome.ok is False
    assert outcome.message == "unknown attribution kind"
    assert fake.posts == []
    assert kb_referral.list_receipts(home) == []


# ---- API -------------------------------------------------------------------


def test_referral_get_requires_session(home: Path) -> None:
    app = _build_app(home)
    status, _h, body, _c = _get(app, "/api/v1/referral", headers=_origin())
    assert status in {401, 403}
    assert b"creates or links" not in body


def test_referral_api_disclosure_and_attribute_with_fake_transport(home: Path) -> None:
    app = _build_app(home)
    fake = kb_referral.FakeTransport()
    app.state.krellbot.referral_transport = fake
    auth = _bootstrap(app)

    status, _h, body, _c = _get(app, "/api/v1/referral", headers=auth)
    assert status == 200, body
    payload = json.loads(body)
    assert payload["headline"] == kb_referral.DISCLOSURE_HEADLINE
    assert payload["body"] == kb_referral.DISCLOSURE_BODY
    assert payload["earn_rule"] == "1"
    assert payload["receipt_count"] == 0

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/referral/attribute",
        {"kind": "exchange_signup", "venue": "kraken"},
        headers=auth,
    )
    assert status == 200, body
    result = json.loads(body)
    assert result["ok"] is True
    assert result["server_posted"] is True
    assert result["kind"] == "exchange_signup"
    assert result["disclosure"]["headline"] == kb_referral.DISCLOSURE_HEADLINE
    assert len(fake.posts) == 1

    status, _h, body, _c = _get(app, "/api/v1/referral", headers=auth)
    assert status == 200, body
    after = json.loads(body)
    assert after["receipt_count"] == 1
    assert after["receipts"][0]["kind"] == "exchange_signup"
    assert after["receipts"][0]["venue"] == "kraken"


def test_referral_attribute_refuses_unknown_kind_via_api(home: Path) -> None:
    app = _build_app(home)
    fake = kb_referral.FakeTransport()
    app.state.krellbot.referral_transport = fake
    auth = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/referral/attribute",
        {"kind": "newsletter"},
        headers=auth,
    )
    assert status == 400, body
    result = json.loads(body)
    assert result["ok"] is False
    assert result["message"] == "unknown attribution kind"
    assert fake.posts == []
