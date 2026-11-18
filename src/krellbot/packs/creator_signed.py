"""Signed creator pack envelope + rev-share contract (verify-before-install).

Third-party creators sell through the signed catalogue lane. The wire
envelope matches the M5 catalogue shape::

    {"payload": "<canonical json string>", "sig": "<unpadded base64url>"}

The inner payload is a closed creator-pack document (not executable
code). Verification reuses :func:`krellbot.license.verify_signed` and
the ed25519 public keys under ``src/krellbot/keys/``. Tampered or
malformed envelopes are refused before any pack bytes are written under
``KRELLBOT_HOME``.

This module never ``eval``s pack JSON, never opens a socket, and never
claims personalized advice. Community packs (M17) stay unsigned and
unpaid; first-party free/paid catalogue metadata stays in
:func:`krellbot.license.verify_catalogue`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from krellbot import license as kb_license
from krellbot import paths as kb_paths
from krellbot.pack import lint as pack_lint

_REJECT = "creator pack signature rejected"
_ENVELOPE_VERSION = "1"
_KIND = "creator_pack"
_PACK_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_CREATOR_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_BPS_TOTAL = 10_000


def _reject() -> ValueError:
    return ValueError(_REJECT)


def _require_str(obj: dict, key: str, *, max_len: int | None = None) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value:
        raise _reject()
    if max_len is not None and len(value) > max_len:
        raise _reject()
    return value


def _normalize_rev_share(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _reject()
    try:
        creator_bps = int(raw["creator_bps"])
        platform_bps = int(raw["platform_bps"])
    except (KeyError, TypeError, ValueError):
        raise _reject() from None
    if creator_bps < 0 or platform_bps < 0:
        raise _reject()
    if creator_bps + platform_bps != _BPS_TOTAL:
        raise _reject()
    currency = raw.get("currency", "USD")
    if not isinstance(currency, str) or not currency or len(currency) > 8:
        raise _reject()
    return {
        "creator_bps": creator_bps,
        "platform_bps": platform_bps,
        "currency": currency,
    }


def _normalize_creator(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise _reject()
    creator_id = _require_str(raw, "id", max_len=64)
    if not _CREATOR_ID.fullmatch(creator_id):
        raise _reject()
    display_name = _require_str(raw, "display_name", max_len=120)
    out = {"id": creator_id, "display_name": display_name}
    contact = raw.get("contact")
    if isinstance(contact, str) and contact and len(contact) <= 120:
        out["contact"] = contact
    return out


def _normalize_sku(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _reject()
    sku_id = _require_str(raw, "id", max_len=64)
    if not _PACK_ID.fullmatch(sku_id):
        raise _reject()
    tier = raw.get("tier")
    if tier != "paid":
        # Creator rev-share SKUs are paid catalogue entries only.
        raise _reject()
    try:
        price_cents = int(raw["price_cents"])
    except (KeyError, TypeError, ValueError):
        raise _reject() from None
    if price_cents < 0:
        raise _reject()
    return {"id": sku_id, "tier": "paid", "price_cents": price_cents}


def _normalize_disclosures(raw: Any) -> dict[str, bool]:
    if not isinstance(raw, dict):
        raise _reject()
    flag = raw.get("not_personalized_advice")
    if flag is not True:
        raise _reject()
    return {"not_personalized_advice": True}


def _normalize_pack(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _reject()
    if pack_lint.is_legacy(raw):
        raise _reject()
    if raw.get("schema_version") != 1:
        raise _reject()
    pack_id = raw.get("id")
    if not isinstance(pack_id, str) or not _PACK_ID.fullmatch(pack_id):
        raise _reject()
    errors = pack_lint.check(raw)
    if errors:
        raise _reject()
    # Return a fresh dict so callers cannot mutate the verified object
    # into something that was never signed.
    return json.loads(json.dumps(raw, sort_keys=True, separators=(",", ":")))


def normalize_creator_pack(verified: dict) -> dict[str, Any]:
    """Return the closed creator-pack document, or raise ValueError.

    Required shape after signature verification:

      * ``envelope_version`` — ``"1"``
      * ``kind`` — ``"creator_pack"``
      * ``pack`` — schema_version 1 DSL object (lint-clean)
      * ``creator`` — ``{id, display_name}`` (+ optional ``contact``)
      * ``rev_share`` — ``creator_bps`` + ``platform_bps`` sum to 10000
      * ``sku`` — paid SKU ``{id, tier: "paid", price_cents}``
      * ``disclosures.not_personalized_advice`` — must be ``true``

    Unknown fields are dropped. The reject message never includes
    payload bytes.
    """
    if not isinstance(verified, dict):
        raise TypeError(_REJECT)
    if verified.get("envelope_version") != _ENVELOPE_VERSION:
        raise _reject()
    if verified.get("kind") != _KIND:
        raise _reject()
    pack = _normalize_pack(verified.get("pack"))
    creator = _normalize_creator(verified.get("creator"))
    rev_share = _normalize_rev_share(verified.get("rev_share"))
    sku = _normalize_sku(verified.get("sku"))
    disclosures = _normalize_disclosures(verified.get("disclosures"))
    if sku["id"] != pack["id"]:
        raise _reject()
    return {
        "envelope_version": _ENVELOPE_VERSION,
        "kind": _KIND,
        "pack": pack,
        "creator": creator,
        "rev_share": rev_share,
        "sku": sku,
        "disclosures": disclosures,
    }


def verify_creator_pack(payload: bytes, sig: str, *, release: bool = False) -> dict[str, Any]:
    """Verify an ed25519-signed creator pack and return the closed document.

    ``payload`` is canonical JSON; ``sig`` is unpadded base64url of the
    64-byte signature. Raises ``ValueError("creator pack signature
    rejected")`` on a bad signature or a payload that is not a creator
    pack document.
    """
    try:
        verified = kb_license.verify_signed(payload, sig, release=release)
    except (TypeError, ValueError):
        raise _reject() from None
    return normalize_creator_pack(verified)


def verify_before_install(envelope: dict[str, Any], *, release: bool = False) -> dict[str, Any]:
    """Verify a wire envelope before any install write.

    Expects ``{"payload": "<canonical json string>", "sig": "<base64url>"}``.
    Returns the closed creator-pack document. Does not write under
    ``KRELLBOT_HOME`` and does not execute pack code.
    """
    if not isinstance(envelope, dict):
        raise TypeError(_REJECT)
    payload = envelope.get("payload")
    sig = envelope.get("sig")
    if not isinstance(payload, str) or not isinstance(sig, str):
        raise TypeError(_REJECT)
    return verify_creator_pack(payload.encode("utf-8"), sig, release=release)


def install_verified_creator_pack(home: Path, envelope: dict[str, Any], *, release: bool = False) -> dict[str, Any]:
    """Verify then write the inner DSL pack under ``packs/creator/``.

    Verify-before-install: signature + closed contract run first. On
    success the pack JSON alone is written (no envelope, no rev-share
    secret material). Rev-share metadata is returned to the caller for
    ledger work (M23.3) and is not persisted here. Failures raise
    before any write.
    """
    document = verify_before_install(envelope, release=release)
    pack = document["pack"]
    pack_id = pack["id"]
    root = Path(home) / "packs" / "creator"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{pack_id}.json"
    body = json.dumps(pack, sort_keys=True, separators=(",", ":")).encode("utf-8")
    kb_paths.atomic_write(path, body)
    return document


__all__ = [
    "install_verified_creator_pack",
    "normalize_creator_pack",
    "verify_before_install",
    "verify_creator_pack",
]
