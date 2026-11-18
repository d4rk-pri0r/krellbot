"""Creator rev-share ledger with fake settlement transport.

Pins M23.3: owed share per paid install/redeem is recorded locally;
settlement goes through an injectable fake transport; operator and
creator views stay local-honest (no invented remote settlement, no
payout secrets). Isolated ``KRELLBOT_HOME`` only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from krellbot.packs import rev_share_ledger


def _document(
    *,
    creator_id: str = "example-creator",
    display_name: str = "Example Creator",
    pack_id: str = "creator-trend",
    price_cents: int = 1999,
    creator_bps: int = 7000,
    platform_bps: int = 3000,
) -> dict:
    return {
        "envelope_version": "1",
        "kind": "creator_pack",
        "pack": {
            "schema_version": 1,
            "id": pack_id,
            "version": "1.0.0",
            "label": "Creator trend",
            "author": creator_id,
            "origin": "Signed creator pack. Not personalized advice.",
            "timeframe": "1h",
            "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
            "entry": ["close", ">", "sma20"],
            "exit": ["close", "<", "sma20"],
            "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
            "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
        },
        "creator": {"id": creator_id, "display_name": display_name},
        "rev_share": {
            "creator_bps": creator_bps,
            "platform_bps": platform_bps,
            "currency": "USD",
        },
        "sku": {"id": pack_id, "tier": "paid", "price_cents": price_cents},
        "disclosures": {"not_personalized_advice": True},
    }


def test_compute_owed_cents_assigns_remainder_to_platform() -> None:
    # 1999 * 7000 // 10000 = 1399; remainder 600 goes to platform.
    creator, platform = rev_share_ledger.compute_owed_cents(1999, 7000, 3000)
    assert creator == 1399
    assert platform == 600
    assert creator + platform == 1999


def test_record_owed_share_persists_paid_install(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    entry = rev_share_ledger.record_owed_share(
        home,
        _document(),
        event_kind="paid_install",
        event_id="evt-install-1",
        recorded_at=1_700_000_000,
    )
    assert entry["status"] == "owed"
    assert entry["event_kind"] == "paid_install"
    assert entry["creator_owed_cents"] == 1399
    assert entry["platform_owed_cents"] == 600
    assert entry["settlement_id"] is None

    path = rev_share_ledger.ledger_path(home)
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == 1
    assert len(on_disk["entries"]) == 1
    assert on_disk["entries"][0]["event_id"] == "evt-install-1"
    # No payout secrets land in the ledger file.
    blob = path.read_text(encoding="utf-8").lower()
    for forbidden in ("password", "api_key", "secret", "token", "iban", "routing"):
        assert forbidden not in blob


def test_record_owed_share_idempotent_on_event_id(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    first = rev_share_ledger.record_owed_share(
        home,
        _document(),
        event_kind="paid_redeem",
        event_id="evt-redeem-1",
        recorded_at=10,
    )
    second = rev_share_ledger.record_owed_share(
        home,
        _document(price_cents=9999),
        event_kind="paid_redeem",
        event_id="evt-redeem-1",
        recorded_at=20,
    )
    assert first["entry_id"] == second["entry_id"]
    assert second["price_cents"] == 1999
    op = rev_share_ledger.operator_view(home)
    assert op["summary"]["entry_count"] == 1


def test_fake_settlement_marks_owed_rows_settled(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    rev_share_ledger.record_owed_share(
        home,
        _document(),
        event_kind="paid_install",
        event_id="evt-a",
        recorded_at=1,
    )
    rev_share_ledger.record_owed_share(
        home,
        _document(creator_id="other-creator", display_name="Other", pack_id="other-pack"),
        event_kind="paid_redeem",
        event_id="evt-b",
        recorded_at=2,
    )
    transport = rev_share_ledger.FakeSettlementTransport()
    result = rev_share_ledger.settle_pending(home, transport=transport, settled_at=99)
    assert result["ok"] is True
    assert len(result["settled_entry_ids"]) == 2
    assert result["pending_remaining"] == 0
    assert len(transport.calls) == 1
    batch = transport.calls[0]
    assert batch["kind"] == "creator_rev_share_settlement"
    assert "secret" not in json.dumps(batch).lower()
    assert "password" not in json.dumps(batch).lower()

    op = rev_share_ledger.operator_view(home)
    assert op["summary"]["pending_count"] == 0
    assert op["summary"]["settled_count"] == 2
    assert op["summary"]["creator_owed_cents_settled"] == 1399 + 1399
    for entry in op["entries"]:
        assert entry["status"] == "settled"
        assert entry["settlement_id"] == "fake-1"
        assert entry["settled_at"] == 99


def test_failed_settlement_leaves_rows_owed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    rev_share_ledger.record_owed_share(
        home,
        _document(),
        event_kind="paid_install",
        event_id="evt-fail",
        recorded_at=1,
    )
    transport = rev_share_ledger.FakeSettlementTransport(fail_next=True)
    result = rev_share_ledger.settle_pending(home, transport=transport, settled_at=5)
    assert result["ok"] is False
    assert result["settled_entry_ids"] == []
    assert result["pending_remaining"] == 1
    op = rev_share_ledger.operator_view(home)
    assert op["summary"]["pending_count"] == 1
    assert op["entries"][0]["status"] == "owed"
    assert op["entries"][0]["settlement_id"] is None


def test_operator_and_creator_views_are_local_honest(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    rev_share_ledger.record_owed_share(
        home,
        _document(creator_id="alice", display_name="Alice", pack_id="alice-pack"),
        event_kind="paid_install",
        event_id="evt-alice",
        recorded_at=1,
    )
    rev_share_ledger.record_owed_share(
        home,
        _document(creator_id="bob", display_name="Bob", pack_id="bob-pack", price_cents=1000),
        event_kind="paid_redeem",
        event_id="evt-bob",
        recorded_at=2,
    )

    op = rev_share_ledger.operator_view(home)
    assert op["role"] == "operator"
    assert op["summary"]["entry_count"] == 2
    assert {e["creator_id"] for e in op["entries"]} == {"alice", "bob"}

    alice = rev_share_ledger.creator_view(home, "alice")
    assert alice["role"] == "creator"
    assert alice["creator_id"] == "alice"
    assert len(alice["entries"]) == 1
    assert alice["entries"][0]["creator_id"] == "alice"
    assert alice["summary"]["entry_count"] == 1
    # Alice does not see Bob's row — local filter, not remote invent.
    assert all(e["creator_id"] == "alice" for e in alice["entries"])

    bob = rev_share_ledger.creator_view(home, "bob")
    assert bob["summary"]["creator_owed_cents_pending"] == 700  # 1000 * 7000 // 10000
    assert bob["entries"][0]["status"] == "owed"


def test_record_rejects_non_paid_or_bad_bps(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    bad_tier = _document()
    bad_tier["sku"]["tier"] = "free"
    with pytest.raises(ValueError, match="rev share ledger rejected"):
        rev_share_ledger.record_owed_share(home, bad_tier, event_id="x")

    bad_bps = _document(creator_bps=5000, platform_bps=4000)
    with pytest.raises(ValueError, match="rev share ledger rejected"):
        rev_share_ledger.record_owed_share(home, bad_bps, event_id="y")
    assert not rev_share_ledger.ledger_path(home).exists()


def test_docs_describe_ledger_and_fake_settlement() -> None:
    root = Path(__file__).resolve().parents[1]
    docs = (root / "docs" / "creator-packs.md").read_text(encoding="utf-8")
    assert "rev_share_ledger" in docs
    assert "FakeSettlementTransport" in docs
    assert "operator_view" in docs
    assert "creator_view" in docs
    assert "payout secrets" in docs.lower() or "no bank tokens" in docs.lower()
