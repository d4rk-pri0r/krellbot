"""Live catalogue-SKU checkout seam (fake processor in CI).

Workstation checkout starts a paid entitlement for a catalogue SKU.
Success records the SKU in the local entitlements store and upserts the
purchased catalog entry so the pack library can refresh. Failure leaves
trading and export unblocked: no license-cache rewrite, no armed-config
mutation, and no kill-switch flip.

Payment goes through an injectable :class:`PaymentTransport`. Tests use
:class:`FakePaymentTransport` only — no real processor keys live in the
repo. Production posts SKU metadata to the cloud checkout endpoint over
HTTPS; the cloud owns processor secrets.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from krellbot import paths as kb_paths
from krellbot.application.activation import write_claim_cache
from krellbot.application.pack_library import (
    InstallRefused,
    _catalogue_entry,
    _safe_pack_id_segment,
)

_ENTITLEMENTS_FILENAME = "sku-entitlements.json"
_CATALOG_FILENAME = "catalog.json"
_DEFAULT_ORIGIN = "https://krellbot.dev"

SAFE_MESSAGES: frozenset[str] = frozenset(
    {
        "checkout paid",
        "checkout refused",
        "checkout unreachable",
        "sku not found",
        "sku not paid",
    }
)


class PaymentTransport(Protocol):
    """HTTP-shaped transport for the cloud checkout session endpoint."""

    def create_session(self, sku: str, *, metadata: dict[str, Any]) -> dict[str, Any]:
        """Create a checkout session for ``sku``.

        Closed response shape (secret-free):

          * ``status`` — ``"paid"``, ``"failed"``, or ``"unreachable"``
          * ``session_id`` — Stripe-shaped ``cs_...`` string when paid
        """


class CheckoutRefused(Exception):
    """Checkout refused without rewriting entitlement or license state."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CheckoutOutcome:
    """Closed, secret-free outcome of a catalogue-SKU checkout."""

    status: str
    message: str
    sku: str
    entitlements: tuple[str, ...]
    session_id: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"paid", "failed", "unreachable", "refused"}:
            raise ValueError(f"CheckoutOutcome.status must be paid/failed/unreachable/refused; got {self.status!r}")
        if self.message not in SAFE_MESSAGES:
            raise ValueError(f"CheckoutOutcome.message must be in SAFE_MESSAGES; got {self.message!r}")


def entitlements_path(home: Path) -> Path:
    """Return the on-disk path for local SKU entitlements."""
    return Path(home) / "catalog" / _ENTITLEMENTS_FILENAME


def catalog_json_path(home: Path) -> Path:
    """Return the purchased-catalog cache path used by the pack classifier."""
    return Path(home) / "catalog" / _CATALOG_FILENAME


def read_entitlements(home: Path) -> list[str]:
    """Return entitled SKU ids in stable sorted order, or [] when absent."""
    path = entitlements_path(home)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    skus = data.get("skus")
    if not isinstance(skus, list):
        return []
    out: list[str] = []
    for item in skus:
        if isinstance(item, str) and item and item not in out:
            out.append(item)
    return sorted(out)


def has_entitlement(home: Path, sku: str) -> bool:
    """True when ``sku`` is present in the local entitlements store."""
    try:
        safe = _safe_pack_id_segment(sku)
    except InstallRefused:
        return False
    return safe in set(read_entitlements(home))


def _write_entitlements(home: Path, skus: list[str]) -> Path:
    path = entitlements_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    body = json.dumps({"schema_version": "1", "skus": sorted(set(skus))}, sort_keys=True)
    kb_paths.atomic_write(path, (body + "\n").encode("utf-8"))
    return path


def grant_entitlement(home: Path, sku: str) -> list[str]:
    """Add ``sku`` to the entitlements store and return the full sorted list."""
    safe = _safe_pack_id_segment(sku)
    current = read_entitlements(home)
    if safe not in current:
        current.append(safe)
    _write_entitlements(home, current)
    return read_entitlements(home)


def _upsert_purchased_catalog(home: Path, entry: dict[str, Any]) -> None:
    """Upsert a catalogue entry into ``catalog/catalog.json`` for purchased rows."""
    pack_id = entry.get("id")
    if not isinstance(pack_id, str) or not pack_id:
        return
    path = catalog_json_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    existing: dict[str, Any] = {"packs": []}
    if path.is_file():
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                existing = parsed
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            existing = {"packs": []}
    packs_raw = existing.get("packs")
    packs: list[dict[str, Any]] = [p for p in packs_raw if isinstance(p, dict)] if isinstance(packs_raw, list) else []
    closed = {
        "id": pack_id,
        "tier": "paid",
    }
    for key in ("label", "description", "version"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            closed[key] = value
    permissions = entry.get("permissions")
    if isinstance(permissions, list) and all(isinstance(p, str) for p in permissions):
        closed["permissions"] = list(permissions)
    else:
        closed["permissions"] = []
    replaced = False
    next_packs: list[dict[str, Any]] = []
    for pack in packs:
        if pack.get("id") == pack_id:
            next_packs.append(closed)
            replaced = True
        else:
            next_packs.append(pack)
    if not replaced:
        next_packs.append(closed)
    document = {
        "schema_version": "1",
        "packs": next_packs,
    }
    kb_paths.atomic_write(path, (json.dumps(document, sort_keys=True) + "\n").encode("utf-8"))


class FakePaymentTransport:
    """In-memory payment transport for CI — never opens a socket.

    Configure ``outcome`` to ``"paid"``, ``"failed"``, or ``"unreachable"``.
    No processor secret is accepted or stored.
    """

    def __init__(self, *, outcome: str = "paid", session_prefix: str = "cs_fake") -> None:
        if outcome not in {"paid", "failed", "unreachable"}:
            raise ValueError("FakePaymentTransport.outcome must be paid/failed/unreachable")
        self.outcome = outcome
        self.session_prefix = session_prefix
        self.calls: list[dict[str, Any]] = []

    def create_session(self, sku: str, *, metadata: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"sku": sku, "metadata": dict(metadata)})
        if self.outcome == "paid":
            return {
                "status": "paid",
                "session_id": f"{self.session_prefix}_{sku}",
            }
        if self.outcome == "failed":
            return {"status": "failed", "session_id": None}
        return {"status": "unreachable", "session_id": None}


class UrllibCheckoutTransport:
    """POST JSON over HTTPS to the cloud checkout session endpoint.

    Refuses non-HTTPS URLs. Never carries processor API keys — the cloud
    owns those. Transport failures surface as ``unreachable``.
    """

    def __init__(self, *, url: str | None = None) -> None:
        self._url = url

    def create_session(self, sku: str, *, metadata: dict[str, Any]) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        from krellbot.tls import urlopen

        target = self._url or checkout_session_url()
        if not isinstance(target, str) or not target.startswith("https://"):
            return {"status": "unreachable", "session_id": None}
        payload = json.dumps({"sku": sku, "metadata": metadata}).encode("utf-8")
        req = urllib.request.Request(
            target,
            data=payload,
            headers={
                "content-type": "application/json",
                "user-agent": "krellbot/0.1",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=20) as res:
                parsed = json.loads(res.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            return {"status": "unreachable", "session_id": None}
        if not isinstance(parsed, dict):
            return {"status": "unreachable", "session_id": None}
        status = parsed.get("status")
        if status not in {"paid", "failed", "unreachable"}:
            return {"status": "unreachable", "session_id": None}
        session_id = parsed.get("session_id")
        if status == "paid" and (not isinstance(session_id, str) or not session_id.startswith("cs_")):
            return {"status": "unreachable", "session_id": None}
        return {
            "status": status,
            "session_id": session_id if isinstance(session_id, str) else None,
        }


def checkout_session_url() -> str:
    """Return the canonical cloud checkout-session URL."""
    raw = os.environ.get("KRELLBOT_API", _DEFAULT_ORIGIN).rstrip("/")
    if not raw.startswith("https://"):
        raw = _DEFAULT_ORIGIN
    return raw + "/api/checkout/session"


def start_checkout(
    home: Path,
    sku: str,
    *,
    transport: PaymentTransport | None = None,
    now: int | None = None,
) -> CheckoutOutcome:
    """Start checkout for a paid catalogue SKU via the injectable transport.

    On ``paid``: records the SKU entitlement, upserts the purchased
    catalog entry, and writes a claim-cache session for the device-token
    flow. On ``failed`` / ``unreachable``: leaves the license cache,
    armed config, and entitlements untouched so trading/export stay open.
    """
    home = Path(home)
    if now is None:
        now = int(time.time())
    try:
        safe_sku = _safe_pack_id_segment(sku)
    except InstallRefused:
        return CheckoutOutcome(
            status="refused",
            message="sku not found",
            sku="",
            entitlements=tuple(read_entitlements(home)),
        )

    entry = _catalogue_entry(home, safe_sku)
    if entry is None:
        return CheckoutOutcome(
            status="refused",
            message="sku not found",
            sku=safe_sku,
            entitlements=tuple(read_entitlements(home)),
        )
    if entry.get("tier") != "paid":
        return CheckoutOutcome(
            status="refused",
            message="sku not paid",
            sku=safe_sku,
            entitlements=tuple(read_entitlements(home)),
        )

    client = transport if transport is not None else UrllibCheckoutTransport()
    try:
        response = client.create_session(
            safe_sku,
            metadata={"source": "workstation", "catalogue_id": safe_sku},
        )
    except OSError:
        return CheckoutOutcome(
            status="unreachable",
            message="checkout unreachable",
            sku=safe_sku,
            entitlements=tuple(read_entitlements(home)),
        )

    if not isinstance(response, dict):
        return CheckoutOutcome(
            status="unreachable",
            message="checkout unreachable",
            sku=safe_sku,
            entitlements=tuple(read_entitlements(home)),
        )

    status = response.get("status")
    if status == "failed":
        return CheckoutOutcome(
            status="failed",
            message="checkout refused",
            sku=safe_sku,
            entitlements=tuple(read_entitlements(home)),
        )
    if status != "paid":
        return CheckoutOutcome(
            status="unreachable",
            message="checkout unreachable",
            sku=safe_sku,
            entitlements=tuple(read_entitlements(home)),
        )

    session_id = response.get("session_id")
    if not isinstance(session_id, str) or not session_id.startswith("cs_"):
        return CheckoutOutcome(
            status="unreachable",
            message="checkout unreachable",
            sku=safe_sku,
            entitlements=tuple(read_entitlements(home)),
        )

    entitlements = grant_entitlement(home, safe_sku)
    _upsert_purchased_catalog(home, entry)
    write_claim_cache(home, session_id=session_id, issued_at=int(now))
    return CheckoutOutcome(
        status="paid",
        message="checkout paid",
        sku=safe_sku,
        entitlements=tuple(entitlements),
        session_id=session_id,
    )


__all__ = [
    "SAFE_MESSAGES",
    "CheckoutOutcome",
    "CheckoutRefused",
    "FakePaymentTransport",
    "PaymentTransport",
    "UrllibCheckoutTransport",
    "catalog_json_path",
    "checkout_session_url",
    "entitlements_path",
    "grant_entitlement",
    "has_entitlement",
    "read_entitlements",
    "start_checkout",
]
