"""Live catalogue-SKU checkout seam with a fake payment processor.

Pins M21.1 behaviour:

  * FakePaymentTransport grants a paid entitlement for a catalogue SKU
    without any real processor keys or network.
  * Success refreshes entitlements and unlocks paid catalogue install.
  * Failure leaves the license cache untouched and does not block
    paper.export (trading/export stay open).
  * The workstation route injects the fake transport; no ``sk_`` /
    processor secret strings ship in the checkout module.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def test_paper_only_release_untouched() -> None:
    assert PAPER_ONLY_RELEASE is True


def test_checkout_module_ships_no_processor_secrets() -> None:
    source = Path(checkout_app.__file__).read_text(encoding="utf-8")
    for needle in ("sk_live", "sk_test", "whsec_", "STRIPE_SECRET", "processor_key"):
        assert needle not in source


def test_fake_paid_checkout_grants_entitlement_and_unlocks_install(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _write_catalogue(home)

    with pytest.raises(pack_library.InstallRefused) as before:
        pack_library.install_from_catalogue(home, "paid-launch-dca")
    assert before.value.code == "activation_required"

    transport = checkout_app.FakePaymentTransport(outcome="paid")
    outcome = checkout_app.start_checkout(
        home,
        "paid-launch-dca",
        transport=transport,
        now=1_700_000_000,
    )
    assert outcome.status == "paid"
    assert outcome.message == "checkout paid"
    assert outcome.sku == "paid-launch-dca"
    assert "paid-launch-dca" in outcome.entitlements
    assert outcome.session_id == "cs_fake_paid-launch-dca"
    assert len(transport.calls) == 1
    assert transport.calls[0]["sku"] == "paid-launch-dca"

    assert checkout_app.has_entitlement(home, "paid-launch-dca")
    assert checkout_app.read_entitlements(home) == ["paid-launch-dca"]

    catalog = json.loads(checkout_app.catalog_json_path(home).read_text(encoding="utf-8"))
    assert any(p.get("id") == "paid-launch-dca" for p in catalog["packs"])

    claim = json.loads((home / "catalog" / "claim-cache.json").read_text(encoding="utf-8"))
    assert claim["session_id"] == "cs_fake_paid-launch-dca"

    # License cache must remain absent — SKU entitlement is the seam.
    assert kb_license.read_cache(home) is None

    row = pack_library.install_from_catalogue(home, "paid-launch-dca")
    assert row["pack_id"] == "paid-launch-dca"
    assert row["bucket"] == "download_pending"
    assert row["version"] == "1.0.0"


def test_fake_failed_checkout_leaves_trading_export_unblocked(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _write_catalogue(home)

    transport = checkout_app.FakePaymentTransport(outcome="failed")
    outcome = checkout_app.start_checkout(
        home,
        "paid-launch-dca",
        transport=transport,
        now=1_700_000_000,
    )
    assert outcome.status == "failed"
    assert outcome.message == "checkout refused"
    assert outcome.entitlements == ()
    assert not checkout_app.has_entitlement(home, "paid-launch-dca")
    assert kb_license.read_cache(home) is None
    assert not checkout_app.entitlements_path(home).exists()
    assert not (home / "catalog" / "claim-cache.json").exists()

    with pytest.raises(pack_library.InstallRefused) as caught:
        pack_library.install_from_catalogue(home, "paid-launch-dca")
    assert caught.value.code == "activation_required"

    # Trading/export stay open after a failed checkout: paper.export still
    # answers (not_armed here — nothing was armed). No license-cache poison.
    app = _build_app(home)
    headers = _session_headers(app)
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
    payload = json.loads(body)
    assert payload["schema_version"] == "1"
    assert payload["code"] == "not_armed"
    assert payload["effect"] == "refused"
    assert kb_license.read_cache(home) is None


def test_checkout_start_route_uses_injected_fake_processor(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _write_catalogue(home)
    app = _build_app(home)
    app.state.krellbot.checkout_transport = checkout_app.FakePaymentTransport(outcome="paid")

    headers = _session_headers(app)
    body_bytes = json.dumps({"sku": "paid-launch-dca"}).encode("utf-8")
    status, _h, body, _c = asgi_call(
        app,
        method="POST",
        path="/api/v1/checkout/start",
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
    assert payload["status"] == "paid"
    assert payload["message"] == "checkout paid"
    assert payload["sku"] == "paid-launch-dca"
    assert "paid-launch-dca" in payload["entitlements"]
    assert payload["session_id"].startswith("cs_")
    assert checkout_app.has_entitlement(home, "paid-launch-dca")


def test_checkout_refuses_free_sku_without_charging(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _write_catalogue(home)
    transport = checkout_app.FakePaymentTransport(outcome="paid")
    outcome = checkout_app.start_checkout(home, "free-dual-ma", transport=transport, now=1)
    assert outcome.status == "refused"
    assert outcome.message == "sku not paid"
    assert transport.calls == []
    assert not checkout_app.has_entitlement(home, "free-dual-ma")
