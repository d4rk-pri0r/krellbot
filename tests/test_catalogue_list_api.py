"""Signed catalogue list API — fetch/verify free+paid metadata.

``GET /api/v1/catalogue`` pulls a signed catalogue envelope through an
injectable transport, verifies it with the license ed25519 keys, caches
the closed metadata under ``$KRELLBOT_HOME/catalog/catalogue.json``, and
returns free + paid pack rows. Tampered payloads are refused: the cache
is not rewritten and the route returns 502.

Tests use fake signature fixtures only — a generated ed25519 keypair
monkeypatched into ``license._KEYS_DIR``. No real network, no real
orders, and no production private keys.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from krellbot import license as kb_license
from krellbot.application import pack_library
from tests.test_ns06_api import (
    TEST_PORT,
    _build_app,
    _post_json,
    asgi_call,
)

CATALOGUE_PATH = "/api/v1/catalogue"


# ---- fake signature fixtures ---------------------------------------------


@pytest.fixture
def catalogue_signing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Install a DEV public key and return a signer for catalogue payloads."""

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
        "updated": "2026-11-15T00:00:00Z",
        "packs": [
            {
                "id": "free-dual-ma",
                "label": "Free Dual MA",
                "description": "Educational free pack",
                "version": "1.0.0",
                "tier": "free",
                "permissions": [],
            },
            {
                "id": "paid-triple-stack",
                "label": "Triple Stack",
                "description": "Paid catalog pack",
                "version": "2.1.0",
                "tier": "paid",
                "permissions": ["catalog"],
            },
        ],
    }


class _FakeCatalogueTransport:
    """Records GETs and returns a pre-cooked signed envelope."""

    def __init__(self, response: dict) -> None:
        self.calls: list[dict] = []
        self._response = response

    def get(self, url: str, headers: dict | None = None) -> dict:
        self.calls.append({"url": url, "headers": dict(headers or {})})
        return self._response


# ---- HTTP helpers --------------------------------------------------------


def _session_headers(app) -> list[tuple[str, str]]:
    token = app.state.krellbot.bootstrap_token
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 200, (status, body)
    session = next(c for c in cookies if c.startswith("krellbot_session=")).split("=", 1)[1]
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session}"),
    ]


def _get_catalogue(
    app,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, bytes]:
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    status, _h, body, _c = asgi_call(app, method="GET", path=CATALOGUE_PATH, headers=base)
    return status, body


# ---- route + verify behavior ---------------------------------------------


def test_catalogue_list_returns_free_and_paid_entries(
    tmp_path: Path,
    catalogue_signing,
) -> None:
    """A verified signed catalogue surfaces free and paid metadata rows."""

    document = _sample_catalogue()
    payload, sig = catalogue_signing(document)
    transport = _FakeCatalogueTransport({"payload": payload, "sig": sig})

    app = _build_app(tmp_path)
    app.state.krellbot.catalogue_transport = transport

    status, body = _get_catalogue(app, headers=_session_headers(app))
    assert status == 200, body
    parsed = json.loads(body)

    assert parsed["schema_version"] == "1"
    assert parsed["catalogue_version"] == "1"
    assert parsed["updated"] == "2026-11-15T00:00:00Z"
    tiers = {row["id"]: row["tier"] for row in parsed["packs"]}
    assert tiers == {
        "free-dual-ma": "free",
        "paid-triple-stack": "paid",
    }
    assert len(transport.calls) == 1

    cached = kb_license.read_catalogue_cache(tmp_path)
    assert cached is not None
    assert {row["id"] for row in cached["packs"]} == set(tiers)


def test_catalogue_list_refuses_tampered_payload(
    tmp_path: Path,
    catalogue_signing,
) -> None:
    """A payload byte flip fails verification and leaves the cache untouched."""

    document = _sample_catalogue()
    payload, sig = catalogue_signing(document)
    # Flip one character inside the signed JSON so the signature no longer
    # matches, while keeping the envelope shape intact.
    tampered = payload.replace("free-dual-ma", "evil-dual-ma", 1)
    assert tampered != payload
    transport = _FakeCatalogueTransport({"payload": tampered, "sig": sig})

    app = _build_app(tmp_path)
    app.state.krellbot.catalogue_transport = transport

    status, body = _get_catalogue(app, headers=_session_headers(app))
    assert status == 502, body
    assert json.loads(body)["detail"] == "catalogue signature rejected"
    assert not kb_license.catalogue_cache_path(tmp_path).exists()


def test_catalogue_list_refuses_tampered_signature(
    tmp_path: Path,
    catalogue_signing,
) -> None:
    """A zeroed signature is refused and never rewrites a prior good cache."""

    document = _sample_catalogue()
    payload, sig = catalogue_signing(document)
    # Seed a prior verified cache so a later refusal must not clobber it.
    kb_license.write_catalogue_cache(tmp_path, document)
    prior = kb_license.catalogue_cache_path(tmp_path).read_bytes()

    bad_sig = "AA" * 43  # 64 zero bytes, unpadded base64url
    assert bad_sig != sig
    transport = _FakeCatalogueTransport({"payload": payload, "sig": bad_sig})

    app = _build_app(tmp_path)
    app.state.krellbot.catalogue_transport = transport

    status, body = _get_catalogue(app, headers=_session_headers(app))
    assert status == 502, body
    assert json.loads(body)["detail"] == "catalogue signature rejected"
    assert kb_license.catalogue_cache_path(tmp_path).read_bytes() == prior


def test_catalogue_list_requires_session(tmp_path: Path) -> None:
    """Unauthenticated catalogue reads are 403, same as other GET gates."""

    app = _build_app(tmp_path)
    status, body = _get_catalogue(app)
    assert status == 403, body


def test_verify_catalogue_rejects_unknown_tier(catalogue_signing) -> None:
    """Catalogue metadata must classify every entry as free or paid."""

    document = _sample_catalogue()
    document["packs"][0]["tier"] = "trial"
    payload, sig = catalogue_signing(document)
    with pytest.raises(ValueError, match="license signature rejected"):
        kb_license.verify_catalogue(payload.encode("utf-8"), sig)


def test_pack_library_refresh_catalogue_writes_cache(
    tmp_path: Path,
    catalogue_signing,
) -> None:
    """Application-layer refresh verifies, caches, and returns free+paid rows."""

    document = _sample_catalogue()
    payload, sig = catalogue_signing(document)
    transport = _FakeCatalogueTransport({"payload": payload, "sig": sig})

    out = pack_library.refresh_catalogue(tmp_path, transport=transport)
    assert {row["tier"] for row in out["packs"]} == {"free", "paid"}
    assert pack_library.list_catalogue(tmp_path)["catalogue_version"] == "1"
