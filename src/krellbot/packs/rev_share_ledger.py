"""Creator rev-share ledger with fake settlement transport.

After a paid creator-pack install or redeem, record the owed creator /
platform share locally under ``$KRELLBOT_HOME``. Settlement is an
injectable transport: tests use :class:`FakeSettlementTransport` so no
real payout network, bank credentials, or payout secrets live in the
repo or in ledger files.

Operator and creator views read only the local ledger. A row is
``settled`` only after a successful transport ack is persisted — views
never invent remote settlement state.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from krellbot import paths as kb_paths

SCHEMA_VERSION = 1
LEDGER_REL = Path("receipts") / "creator-rev-share.json"
_BPS_TOTAL = 10_000

EventKind = Literal["paid_install", "paid_redeem"]
EntryStatus = Literal["owed", "settled"]


class SettlementTransport(Protocol):
    """POST-shaped settlement seam. Tests inject a fake; no secrets."""

    def settle(self, batch: dict[str, Any]) -> dict[str, Any]:
        """Ack a settlement batch.

        ``batch`` carries only local-honest amounts and ids (no bank
        tokens, API keys, or payout secrets). A successful response must
        include ``ok: true`` and ``settled_entry_ids`` listing the
        entry ids that cleared. Optional ``settlement_id`` is recorded
        when present.
        """


@dataclass
class FakeSettlementTransport:
    """Test double that records settle calls and never egresses."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    fail_next: bool = False

    def settle(self, batch: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(json.loads(json.dumps(batch)))
        if self.fail_next:
            self.fail_next = False
            return {"ok": False, "settled_entry_ids": []}
        entry_ids = [str(e["entry_id"]) for e in batch.get("entries", []) if isinstance(e, dict)]
        return {
            "ok": True,
            "settlement_id": f"fake-{len(self.calls)}",
            "settled_entry_ids": entry_ids,
        }


def _ledger_path(home: Path) -> Path:
    return Path(home) / LEDGER_REL


def _empty_ledger() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "entries": []}


def _load(home: Path) -> dict[str, Any]:
    path = _ledger_path(home)
    if not path.is_file():
        return _empty_ledger()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_ledger()
    if not isinstance(raw, dict):
        return _empty_ledger()
    entries = raw.get("entries")
    if not isinstance(entries, list):
        entries = []
    clean: list[dict[str, Any]] = []
    for item in entries:
        if isinstance(item, dict):
            clean.append(item)
    return {"schema_version": SCHEMA_VERSION, "entries": clean}


def _save(home: Path, ledger: dict[str, Any]) -> None:
    path = _ledger_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(ledger, sort_keys=True, separators=(",", ":")).encode("utf-8")
    kb_paths.atomic_write(path, body + b"\n")


def compute_owed_cents(price_cents: int, creator_bps: int, platform_bps: int) -> tuple[int, int]:
    """Split ``price_cents`` by bps with integer cents (no float).

    Creator gets floor(price * creator_bps / 10000). Platform gets the
    remainder so ``creator + platform == price`` (remainder cents stay
    with the platform). Rejects a split that does not sum to 10000 bps.
    """
    if not isinstance(price_cents, int):
        raise TypeError("rev share ledger rejected")
    if price_cents < 0:
        raise ValueError("rev share ledger rejected")
    if not isinstance(creator_bps, int) or not isinstance(platform_bps, int):
        raise TypeError("rev share ledger rejected")
    if creator_bps < 0 or platform_bps < 0 or creator_bps + platform_bps != _BPS_TOTAL:
        raise ValueError("rev share ledger rejected")
    creator_owed = (price_cents * creator_bps) // _BPS_TOTAL
    platform_owed = price_cents - creator_owed
    return creator_owed, platform_owed


def _require_document(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise TypeError("rev share ledger rejected")
    if document.get("kind") != "creator_pack":
        raise ValueError("rev share ledger rejected")
    creator = document.get("creator")
    rev_share = document.get("rev_share")
    sku = document.get("sku")
    pack = document.get("pack")
    if not isinstance(creator, dict) or not isinstance(rev_share, dict):
        raise TypeError("rev share ledger rejected")
    if not isinstance(sku, dict) or not isinstance(pack, dict):
        raise TypeError("rev share ledger rejected")
    creator_id = creator.get("id")
    display_name = creator.get("display_name")
    if not isinstance(creator_id, str) or not creator_id:
        raise ValueError("rev share ledger rejected")
    if not isinstance(display_name, str) or not display_name:
        raise ValueError("rev share ledger rejected")
    try:
        creator_bps = int(rev_share["creator_bps"])
        platform_bps = int(rev_share["platform_bps"])
        price_cents = int(sku["price_cents"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("rev share ledger rejected") from exc
    currency = rev_share.get("currency", "USD")
    if not isinstance(currency, str) or not currency or len(currency) > 8:
        raise ValueError("rev share ledger rejected")
    pack_id = pack.get("id")
    sku_id = sku.get("id")
    if not isinstance(pack_id, str) or not isinstance(sku_id, str):
        raise TypeError("rev share ledger rejected")
    if sku.get("tier") != "paid":
        raise ValueError("rev share ledger rejected")
    if pack_id != sku_id:
        raise ValueError("rev share ledger rejected")
    creator_owed, platform_owed = compute_owed_cents(price_cents, creator_bps, platform_bps)
    return {
        "pack_id": pack_id,
        "sku_id": sku_id,
        "creator_id": creator_id,
        "creator_display_name": display_name,
        "price_cents": price_cents,
        "creator_bps": creator_bps,
        "platform_bps": platform_bps,
        "currency": currency,
        "creator_owed_cents": creator_owed,
        "platform_owed_cents": platform_owed,
    }


def record_owed_share(
    home: Path,
    document: dict[str, Any],
    *,
    event_kind: EventKind = "paid_install",
    event_id: str | None = None,
    recorded_at: int | None = None,
) -> dict[str, Any]:
    """Append one owed-share row for a paid install/redeem document.

    Idempotent on ``event_id``: a second call with the same id returns the
    existing row and does not double-count. Never stores payout secrets.
    """
    if event_kind not in {"paid_install", "paid_redeem"}:
        raise ValueError("rev share ledger rejected")
    fields = _require_document(document)
    eid = event_id or str(uuid.uuid4())
    if not isinstance(eid, str) or not eid or len(eid) > 128:
        raise ValueError("rev share ledger rejected")
    ts = int(recorded_at) if recorded_at is not None else 0
    if ts < 0:
        raise ValueError("rev share ledger rejected")

    ledger = _load(home)
    for existing in ledger["entries"]:
        if existing.get("event_id") == eid:
            return json.loads(json.dumps(existing))

    entry = {
        "entry_id": str(uuid.uuid4()),
        "event_id": eid,
        "event_kind": event_kind,
        "recorded_at": ts,
        "status": "owed",
        "settlement_id": None,
        "settled_at": None,
        **fields,
    }
    ledger["entries"].append(entry)
    _save(home, ledger)
    return json.loads(json.dumps(entry))


def _public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Closed view shape — no secrets, only local-honest fields."""
    return {
        "entry_id": entry.get("entry_id"),
        "event_id": entry.get("event_id"),
        "event_kind": entry.get("event_kind"),
        "recorded_at": entry.get("recorded_at"),
        "status": entry.get("status"),
        "settlement_id": entry.get("settlement_id"),
        "settled_at": entry.get("settled_at"),
        "pack_id": entry.get("pack_id"),
        "sku_id": entry.get("sku_id"),
        "creator_id": entry.get("creator_id"),
        "creator_display_name": entry.get("creator_display_name"),
        "price_cents": entry.get("price_cents"),
        "creator_bps": entry.get("creator_bps"),
        "platform_bps": entry.get("platform_bps"),
        "currency": entry.get("currency"),
        "creator_owed_cents": entry.get("creator_owed_cents"),
        "platform_owed_cents": entry.get("platform_owed_cents"),
    }


def _summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
    owed_creator = 0
    owed_platform = 0
    settled_creator = 0
    settled_platform = 0
    pending = 0
    settled_n = 0
    for entry in entries:
        c = int(entry.get("creator_owed_cents") or 0)
        p = int(entry.get("platform_owed_cents") or 0)
        if entry.get("status") == "settled":
            settled_creator += c
            settled_platform += p
            settled_n += 1
        else:
            owed_creator += c
            owed_platform += p
            pending += 1
    return {
        "entry_count": len(entries),
        "pending_count": pending,
        "settled_count": settled_n,
        "creator_owed_cents_pending": owed_creator,
        "platform_owed_cents_pending": owed_platform,
        "creator_owed_cents_settled": settled_creator,
        "platform_owed_cents_settled": settled_platform,
    }


def operator_view(home: Path) -> dict[str, Any]:
    """Local-honest operator ledger view (all creators on this home)."""
    ledger = _load(home)
    entries = [_public_entry(e) for e in ledger["entries"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "role": "operator",
        "entries": entries,
        "summary": _summarize(entries),
    }


def creator_view(home: Path, creator_id: str) -> dict[str, Any]:
    """Local-honest creator view — only that creator's rows."""
    if not isinstance(creator_id, str) or not creator_id:
        raise ValueError("rev share ledger rejected")
    ledger = _load(home)
    entries = [_public_entry(e) for e in ledger["entries"] if e.get("creator_id") == creator_id]
    return {
        "schema_version": SCHEMA_VERSION,
        "role": "creator",
        "creator_id": creator_id,
        "entries": entries,
        "summary": _summarize(entries),
    }


def settle_pending(
    home: Path,
    *,
    transport: SettlementTransport,
    settled_at: int | None = None,
) -> dict[str, Any]:
    """Settle owed rows through ``transport`` and persist acks only.

    Builds a secret-free batch from local ``owed`` rows. Marks a row
    ``settled`` only when the transport response lists its ``entry_id``.
    A failed or empty ack leaves rows owed — views stay local-honest.
    """
    ledger = _load(home)
    pending = [e for e in ledger["entries"] if e.get("status") == "owed"]
    if not pending:
        return {
            "ok": True,
            "settled_entry_ids": [],
            "settlement_id": None,
            "pending_remaining": 0,
        }

    batch = {
        "kind": "creator_rev_share_settlement",
        "currency": pending[0].get("currency", "USD"),
        "entries": [
            {
                "entry_id": e["entry_id"],
                "creator_id": e["creator_id"],
                "pack_id": e["pack_id"],
                "creator_owed_cents": e["creator_owed_cents"],
                "platform_owed_cents": e["platform_owed_cents"],
                "currency": e.get("currency", "USD"),
            }
            for e in pending
        ],
    }
    # Never put secrets into the batch — only the closed fields above.
    response = transport.settle(batch)
    if not isinstance(response, dict) or response.get("ok") is not True:
        return {
            "ok": False,
            "settled_entry_ids": [],
            "settlement_id": None,
            "pending_remaining": len(pending),
        }

    settled_ids_raw = response.get("settled_entry_ids") or []
    if not isinstance(settled_ids_raw, list):
        settled_ids_raw = []
    settled_ids = {str(x) for x in settled_ids_raw}
    settlement_id = response.get("settlement_id")
    if not isinstance(settlement_id, str) or not settlement_id:
        settlement_id = None
    ts = int(settled_at) if settled_at is not None else 0

    applied: list[str] = []
    for entry in ledger["entries"]:
        if entry.get("status") != "owed":
            continue
        if entry.get("entry_id") not in settled_ids:
            continue
        entry["status"] = "settled"
        entry["settlement_id"] = settlement_id
        entry["settled_at"] = ts
        applied.append(str(entry["entry_id"]))

    if applied:
        _save(home, ledger)

    remaining = sum(1 for e in ledger["entries"] if e.get("status") == "owed")
    return {
        "ok": True,
        "settled_entry_ids": applied,
        "settlement_id": settlement_id,
        "pending_remaining": remaining,
    }


def ledger_path(home: Path) -> Path:
    """Return the on-disk ledger path under ``home``."""
    return _ledger_path(home)


__all__ = [
    "FakeSettlementTransport",
    "SettlementTransport",
    "compute_owed_cents",
    "creator_view",
    "ledger_path",
    "operator_view",
    "record_owed_share",
    "settle_pending",
]
