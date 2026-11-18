"""Signed creator pack envelope + rev-share contract (verify-before-install).

Pins the M23.2 contract: ed25519 envelope over a closed creator-pack
document with rev-share metadata; verify-before-install refuses
tampered / incomplete disclosures; install writes only DSL JSON and
never executes pack code. Fake DEV keys only — no network, no real
orders, isolated ``KRELLBOT_HOME``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from krellbot import license as kb_license
from krellbot.packs import creator_signed


@pytest.fixture
def creator_signing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Install a DEV public key and return a signer for creator payloads."""

    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    keys = tmp_path / "creator-keys"
    keys.mkdir()
    pub_line = base64.urlsafe_b64encode(public).rstrip(b"=").decode("ascii")
    (keys / "creator-dev.pub").write_text(f"# DEV\n{pub_line}\n", encoding="utf-8")
    monkeypatch.setattr(kb_license, "_KEYS_DIR", keys)

    def sign(document: dict) -> tuple[str, str]:
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"))
        sig = private.sign(payload.encode("utf-8"))
        sig_text = base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")
        return payload, sig_text

    return sign


def _sample_pack() -> dict:
    return {
        "schema_version": 1,
        "id": "creator-trend",
        "version": "1.0.0",
        "label": "Creator trend",
        "author": "example-creator",
        "origin": "Signed creator pack. Not personalized advice.",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }


def _sample_document() -> dict:
    return {
        "envelope_version": "1",
        "kind": "creator_pack",
        "pack": _sample_pack(),
        "creator": {
            "id": "example-creator",
            "display_name": "Example Creator",
        },
        "rev_share": {
            "creator_bps": 7000,
            "platform_bps": 3000,
            "currency": "USD",
        },
        "sku": {
            "id": "creator-trend",
            "tier": "paid",
            "price_cents": 1999,
        },
        "disclosures": {
            "not_personalized_advice": True,
        },
    }


def test_verify_creator_pack_accepts_signed_rev_share_contract(creator_signing) -> None:
    document = _sample_document()
    payload, sig = creator_signing(document)
    out = creator_signed.verify_creator_pack(payload.encode("utf-8"), sig)
    assert out["kind"] == "creator_pack"
    assert out["rev_share"]["creator_bps"] == 7000
    assert out["rev_share"]["platform_bps"] == 3000
    assert out["sku"]["tier"] == "paid"
    assert out["disclosures"]["not_personalized_advice"] is True
    assert out["pack"]["id"] == "creator-trend"


def test_verify_before_install_refuses_tampered_signature(creator_signing) -> None:
    document = _sample_document()
    payload, sig = creator_signing(document)
    bad_sig = "AA" * 43
    assert bad_sig != sig
    with pytest.raises(ValueError, match="creator pack signature rejected"):
        creator_signed.verify_before_install({"payload": payload, "sig": bad_sig})


def test_verify_refuses_rev_share_that_does_not_sum_to_10000(creator_signing) -> None:
    document = _sample_document()
    document["rev_share"]["creator_bps"] = 5000
    document["rev_share"]["platform_bps"] = 4000
    payload, sig = creator_signing(document)
    with pytest.raises(ValueError, match="creator pack signature rejected"):
        creator_signed.verify_creator_pack(payload.encode("utf-8"), sig)


def test_verify_refuses_missing_not_personalized_advice_disclosure(creator_signing) -> None:
    document = _sample_document()
    document["disclosures"]["not_personalized_advice"] = False
    payload, sig = creator_signing(document)
    with pytest.raises(ValueError, match="creator pack signature rejected"):
        creator_signed.verify_creator_pack(payload.encode("utf-8"), sig)


def test_verify_refuses_sku_id_mismatch(creator_signing) -> None:
    document = _sample_document()
    document["sku"]["id"] = "other-pack"
    payload, sig = creator_signing(document)
    with pytest.raises(ValueError, match="creator pack signature rejected"):
        creator_signed.verify_creator_pack(payload.encode("utf-8"), sig)


def test_install_verified_creator_pack_writes_dsl_only(tmp_path: Path, creator_signing) -> None:
    home = tmp_path / "home"
    home.mkdir()
    document = _sample_document()
    payload, sig = creator_signing(document)
    envelope = {"payload": payload, "sig": sig}

    out = creator_signed.install_verified_creator_pack(home, envelope)
    assert out["rev_share"]["creator_bps"] == 7000

    path = home / "packs" / "creator" / "creator-trend.json"
    assert path.is_file()
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["id"] == "creator-trend"
    assert written["schema_version"] == 1
    assert "rev_share" not in written
    assert "sig" not in written
    # Install path is JSON write only — source must not eval pack bodies.
    source = Path(creator_signed.__file__).read_text(encoding="utf-8")
    assert "eval(" not in source
    assert "exec(" not in source


def test_install_refuses_tamper_without_writing(tmp_path: Path, creator_signing) -> None:
    home = tmp_path / "home"
    home.mkdir()
    document = _sample_document()
    payload, _sig = creator_signing(document)
    with pytest.raises(ValueError, match="creator pack signature rejected"):
        creator_signed.install_verified_creator_pack(
            home,
            {"payload": payload, "sig": "AA" * 43},
        )
    assert not (home / "packs" / "creator").exists()


def test_docs_name_signed_creator_pack_and_not_advice() -> None:
    root = Path(__file__).resolve().parents[1]
    creator_docs = (root / "docs" / "creator-packs.md").read_text(encoding="utf-8")
    pack_format = (root / "docs" / "pack-format.md").read_text(encoding="utf-8")
    assert "rev_share" in creator_docs
    assert "not personalized advice" in creator_docs.lower()
    assert "verify-before-install" in creator_docs.lower() or "verify before install" in creator_docs.lower()
    assert "creator-packs.md" in pack_format
