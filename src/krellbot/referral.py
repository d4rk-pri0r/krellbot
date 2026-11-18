"""Disclosed referral / fee-share attribution (M23.1).

Earn rule (1) from ``docs/product-direction.md``:

  Exchange fee share / referral — disclosed attribution when an
  operator creates or links an exchange account through a Krellbot
  referral path.

This module records a **local receipt** under ``$KRELLBOT_HOME/receipts/``
and posts a closed attribution payload to the server seam. Tests inject
a fake transport so CI never egresses. Pack purchase attribution uses
the same seam (second monetization surface that still discloses fee
share / referral honestly).

No exchange credentials, license keys, or balances are ever included.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from krellbot import paths as kb_paths

SCHEMA_VERSION = "1"
DEFAULT_URL = "https://krellbot.dev/api/referral/attribute"
RECEIPTS_FILE = "referral.jsonl"
KINDS = frozenset({"exchange_signup", "pack_purchase"})

Kind = Literal["exchange_signup", "pack_purchase"]

# Exact disclosure copy pinned to product-direction earn rule (1).
DISCLOSURE_HEADLINE = "Exchange fee share / referral"
DISCLOSURE_BODY = (
    "Disclosed attribution when an operator creates or links an exchange account through a Krellbot referral path."
)
# Packs surface: same earn rule, stated for pack purchase context.
PACKS_DISCLOSURE = (
    "Fee share / referral: pack purchases may include disclosed "
    "attribution under the exchange fee share / referral earn rule."
)

SAFE_MESSAGES: frozenset[str] = frozenset(
    {
        "attribution recorded",
        "attribution recorded locally; server unreachable",
        "attribution refused",
        "unknown attribution kind",
    }
)


class Transport(Protocol):
    """HTTP-shaped transport for server attribution POSTs."""

    def post(self, url: str, body: bytes, headers: dict) -> object: ...


@dataclass
class FakeTransport:
    """Test double: records posts and never egresses."""

    posts: list[dict[str, Any]] = field(default_factory=list)
    raise_unreachable: bool = False
    response: object = b'{"ok":true}'

    def post(self, url: str, body: bytes, headers: dict) -> object:
        if self.raise_unreachable:
            raise OSError("referral attribution unreachable")
        self.posts.append({"url": url, "body": body, "headers": dict(headers)})
        return self.response


class UrllibTransport:
    """Default HTTPS transport. Tests must inject FakeTransport instead."""

    def __init__(self, *, timeout: float = 10.0) -> None:
        self._timeout = timeout

    def post(self, url: str, body: bytes, headers: dict) -> object:
        if not isinstance(url, str) or not url.startswith("https://"):
            raise OSError("referral attribution unreachable")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        from krellbot.tls import urlopen

        try:
            with urlopen(req, timeout=self._timeout) as res:
                return res.read()
        except urllib.error.URLError as exc:
            raise OSError("referral attribution unreachable") from exc


@dataclass(frozen=True)
class AttributeOutcome:
    """Closed, secret-free outcome of one attribution attempt."""

    ok: bool
    message: str
    receipt_id: str
    kind: str
    server_posted: bool

    def __post_init__(self) -> None:
        if self.message not in SAFE_MESSAGES:
            raise ValueError(f"AttributeOutcome.message must be in SAFE_MESSAGES; got {self.message!r}")


def _origin() -> str:
    raw = os.environ.get("KRELLBOT_API", "https://krellbot.dev").rstrip("/")
    if not raw.startswith("https://"):
        return "https://krellbot.dev"
    return raw


def attribution_url() -> str:
    return _origin() + "/api/referral/attribute"


def disclosure() -> dict[str, str]:
    """Closed disclosure payload for Settings / Packs UI and GET API."""

    return {
        "schema_version": SCHEMA_VERSION,
        "headline": DISCLOSURE_HEADLINE,
        "body": DISCLOSURE_BODY,
        "packs_body": PACKS_DISCLOSURE,
        "earn_rule": "1",
        "source": "docs/product-direction.md",
    }


def _receipts_path(home: Path) -> Path:
    return Path(home) / "receipts" / RECEIPTS_FILE


def _append_receipt(home: Path, receipt: dict[str, Any]) -> Path:
    """Append one JSONL receipt under ``receipts/``. Returns the file path."""

    kb_paths.ensure_layout()
    path = _receipts_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
    fd = os.open(str(path), flags, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    if os.name != "nt":
        os.chmod(path, 0o600)
    return path


def list_receipts(home: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    """Return recent local referral receipts (newest last), capped."""

    path = _receipts_path(home)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and not row.get("ack"):
            out.append(row)
    if limit > 0 and len(out) > limit:
        out = out[-limit:]
    return out


def status(home: Path) -> dict[str, Any]:
    """Closed status for GET ``/api/v1/referral``."""

    receipts = list_receipts(home)
    return {
        **disclosure(),
        "receipt_count": len(receipts),
        "receipts": [
            {
                "receipt_id": str(r.get("receipt_id") or ""),
                "kind": str(r.get("kind") or ""),
                "ts": int(r.get("ts") or 0),
                "venue": str(r.get("venue") or ""),
                "pack_id": str(r.get("pack_id") or ""),
                "server_posted": bool(r.get("server_posted")),
            }
            for r in receipts
        ],
    }


def attribute(
    home: Path,
    *,
    kind: str,
    venue: str = "",
    pack_id: str = "",
    transport: Transport | None = None,
    url: str | None = None,
    now: int | None = None,
    receipt_id: str | None = None,
) -> AttributeOutcome:
    """Record a local receipt and post attribution to the server seam.

    ``transport`` is injected by tests (``FakeTransport``) and by the
    workstation API when a seam is configured. When ``transport`` is
    omitted, only the local receipt is written — no network egress —
    so redeem and CI paths never hang on a real HTTPS post. Callers
    that want the live server seam pass ``UrllibTransport()`` explicitly.
    """

    if kind not in KINDS:
        return AttributeOutcome(
            ok=False,
            message="unknown attribution kind",
            receipt_id="",
            kind=str(kind),
            server_posted=False,
        )

    rid = receipt_id or str(uuid.uuid4())
    ts = int(now if now is not None else time.time())
    venue_s = str(venue or "").strip()[:64]
    pack_s = str(pack_id or "").strip()[:96]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": rid,
        "kind": kind,
        "ts": ts,
        "venue": venue_s,
        "pack_id": pack_s,
        "disclosure": DISCLOSURE_HEADLINE,
    }

    server_posted = False
    message = "attribution recorded locally; server unreachable"
    if transport is not None:
        target = url or attribution_url()
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "user-agent": "krellbot/0.1",
        }
        try:
            transport.post(target, body, headers)
            server_posted = True
            message = "attribution recorded"
        except OSError:
            server_posted = False
            message = "attribution recorded locally; server unreachable"
    else:
        # Local-only: honest receipt without inventing a live server post.
        message = "attribution recorded"
        server_posted = False

    _append_receipt(
        home,
        {
            **payload,
            "server_posted": server_posted,
        },
    )

    return AttributeOutcome(
        ok=True,
        message=message,
        receipt_id=rid,
        kind=kind,
        server_posted=server_posted,
    )


def outcome_dict(outcome: AttributeOutcome) -> dict[str, Any]:
    """JSON-ready closed outcome (API / tests)."""

    return {
        "schema_version": SCHEMA_VERSION,
        "ok": outcome.ok,
        "code": "referral_attributed" if outcome.ok else "referral_refused",
        "message": outcome.message,
        "receipt_id": outcome.receipt_id,
        "kind": outcome.kind,
        "server_posted": outcome.server_posted,
        "disclosure": disclosure(),
    }
