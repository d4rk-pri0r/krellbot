"""Pack refund request revokes local SKU entitlement with journal audit.

Pins M21.3 behaviour:

  * FakePaymentTransport refunds a previously entitled catalogue SKU
    without any real processor keys or network.
  * Success revokes the entitlement, clears claim cache, and journals an
    entitlement_revoked audit row.
  * Failed / unreachable refund leaves the entitlement and license cache
    untouched and does not block paper.export.
  * The workstation refund route injects the fake transport.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from krellbot import journal as kb_journal
from krellbot import license as kb_license
from krellbot.application import checkout as checkout_app
from krellbot.application import pack_library
from krellbot.release_policy import PAPER_ONLY_RELEASE
from tests.test_ns06_api import (
    TEST_PORT,
    _build_app,
    _post_json,
    asgi_call,
)


def _write_catalogue(home: Path) -> None:
    document = {
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
    kb_license.write_catalogue_cache(home, document)


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


def _grant_paid(home: Path) -> checkout_app.CheckoutOutcome:
    transport = checkout_app.FakePaymentTransport(outcome="paid")
    return checkout_app.start_checkout(
        home,
        "paid-launch-dca",
        transport=transport,
        now=1_700_000_000,
    )


def _paper_export(app, headers: list[tuple[str, str]]) -> dict:
    body_bytes = json.dumps(
        {
            "schema_version": "1",
            "command": "paper.export",
            "payload": {"venue": "kraken", "pair": "BTCUSD"},
        }
    ).encode("utf-8")
    status, _h, body, _c = asgi_call(
        app,
        method="POST",
        path="/api/v1/commands",
        body=body_bytes,
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body_bytes))),
            *headers,
        ],
    )
    assert status == 200, body
    return json.loads(body)


def test_paper_only_release_untouched() -> None:
    assert PAPER_ONLY_RELEASE is True


def test_checkout_module_ships_no_processor_secrets() -> None:
    source = Path(checkout_app.__file__).read_text(encoding="utf-8")
    for needle in ("sk_live", "sk_test", "whsec_", "STRIPE_SECRET", "processor_key"):
        assert needle not in source


def test_fake_refund_revokes_entitlement_and_journals(home: Path) -> None:
    _write_catalogue(home)
    paid = _grant_paid(home)
    assert paid.status == "paid"
    assert checkout_app.has_entitlement(home, "paid-launch-dca")
    assert (home / "catalog" / "claim-cache.json").is_file()

    transport = checkout_app.FakePaymentTransport(refund_outcome="refunded")
    outcome = checkout_app.request_refund(
        home,
        "paid-launch-dca",
        transport=transport,
        now=1_700_000_100,
    )
    assert outcome.status == "refunded"
    assert outcome.message == "refund completed"
    assert outcome.sku == "paid-launch-dca"
    assert outcome.entitlements == ()
    assert outcome.refund_id == "re_fake_paid-launch-dca"
    assert len(transport.refund_calls) == 1
    assert transport.refund_calls[0]["sku"] == "paid-launch-dca"

    assert not checkout_app.has_entitlement(home, "paid-launch-dca")
    assert checkout_app.read_entitlements(home) == []
    assert not (home / "catalog" / "claim-cache.json").exists()
    assert kb_license.read_cache(home) is None

    catalog_path = checkout_app.catalog_json_path(home)
    if catalog_path.is_file():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        assert all(p.get("id") != "paid-launch-dca" for p in catalog.get("packs", []))

    records = kb_journal.read_records_lenient(home)
    revoked = [
        r
        for r in records
        if r.get("kind") == "entitlement"
        and isinstance(r.get("detail"), dict)
        and r["detail"].get("event") == "entitlement_revoked"
    ]
    assert len(revoked) == 1
    assert revoked[0]["pack"] == "paid-launch-dca"
    assert revoked[0]["detail"]["source"] == "refund"
    assert revoked[0]["detail"]["sku"] == "paid-launch-dca"
    assert revoked[0]["detail"]["refund_id"] == "re_fake_paid-launch-dca"

    with pytest.raises(pack_library.InstallRefused) as caught:
        pack_library.install_from_catalogue(home, "paid-launch-dca")
    assert caught.value.code == "activation_required"


def test_fake_failed_refund_leaves_trading_export_unblocked(home: Path) -> None:
    _write_catalogue(home)
    assert _grant_paid(home).status == "paid"

    transport = checkout_app.FakePaymentTransport(refund_outcome="failed")
    outcome = checkout_app.request_refund(
        home,
        "paid-launch-dca",
        transport=transport,
        now=1_700_000_100,
    )
    assert outcome.status == "failed"
    assert outcome.message == "refund refused"
    assert "paid-launch-dca" in outcome.entitlements
    assert checkout_app.has_entitlement(home, "paid-launch-dca")
    assert kb_license.read_cache(home) is None
    assert (home / "catalog" / "claim-cache.json").is_file()

    records = kb_journal.read_records_lenient(home)
    assert not any(
        r.get("kind") == "entitlement"
        and isinstance(r.get("detail"), dict)
        and r["detail"].get("event") == "entitlement_revoked"
        for r in records
    )

    app = _build_app(home)
    headers = _session_headers(app)
    payload = _paper_export(app, headers)
    assert payload["schema_version"] == "1"
    assert payload["code"] == "not_armed"
    assert payload["effect"] == "refused"
    assert checkout_app.has_entitlement(home, "paid-launch-dca")
    assert kb_license.read_cache(home) is None


def test_checkout_refund_route_uses_injected_fake_processor(home: Path) -> None:
    _write_catalogue(home)
    assert _grant_paid(home).status == "paid"
    app = _build_app(home)
    app.state.krellbot.checkout_transport = checkout_app.FakePaymentTransport(refund_outcome="refunded")

    headers = _session_headers(app)
    body_bytes = json.dumps({"sku": "paid-launch-dca"}).encode("utf-8")
    status, _h, body, _c = asgi_call(
        app,
        method="POST",
        path="/api/v1/checkout/refund",
        body=body_bytes,
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body_bytes))),
            *headers,
        ],
    )
    assert status == 200, body
    payload = json.loads(body)
    assert payload["status"] == "refunded"
    assert payload["message"] == "refund completed"
    assert payload["sku"] == "paid-launch-dca"
    assert payload["entitlements"] == []
    assert payload["refund_id"].startswith("re_")
    assert not checkout_app.has_entitlement(home, "paid-launch-dca")


def test_refund_refuses_unenitled_sku_without_charging(home: Path) -> None:
    _write_catalogue(home)
    transport = checkout_app.FakePaymentTransport(refund_outcome="refunded")
    outcome = checkout_app.request_refund(home, "paid-launch-dca", transport=transport, now=1)
    assert outcome.status == "refused"
    assert outcome.message == "sku not entitled"
    assert transport.refund_calls == []
    assert not checkout_app.has_entitlement(home, "paid-launch-dca")
