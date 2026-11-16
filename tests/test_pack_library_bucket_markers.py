"""Pack library bucket markers reflect real install/arm flows.

Production writers under ``krellbot.application.pack_library`` create the
sidecars the classifier expects:

  * ``install_from_catalogue`` → ``download_pending``
  * ``mark_configured`` / catalog+community install → ``configured``
  * ``mark_deployed`` via paper arm → ``deployed``
  * disarm demotes deployed → configured

Fake transports / isolated ``KRELLBOT_HOME`` only; no network credentials.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot import license as kb_license
from krellbot.application import pack_library
from krellbot.application.paper import PaperService
from krellbot.extensions import install as kb_extensions_install


def _write_pack(home: Path, pack_id: str, *, version: str = "1.0.0") -> Path:
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": version,
        "label": f"Pack {pack_id}",
        "author": "bucket marker tests",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    target = packs / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _write_catalogue(home: Path) -> None:
    kb_license.write_catalogue_cache(
        home,
        {
            "catalogue_version": "1",
            "packs": [
                {
                    "id": "free-marker-pack",
                    "label": "Free Marker",
                    "version": "3.2.1",
                    "tier": "free",
                    "permissions": [],
                }
            ],
        },
    )


def test_catalogue_install_writes_download_pending_marker(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _write_catalogue(home)

    row = pack_library.install_from_catalogue(home, "free-marker-pack")
    assert row["bucket"] == "download_pending"
    assert row["version"] == "3.2.1"

    marker = home / "packs" / "free-marker-pack.download_pending.json"
    assert marker.is_file()
    listed = pack_library.list_installed(home)
    assert any(r["pack_id"] == "free-marker-pack" and r["bucket"] == "download_pending" for r in listed)


def test_mark_configured_writes_configured_sidecar_for_installed_pack(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _write_pack(home, "ready-pack")

    row = pack_library.mark_configured(home, "ready-pack", now=1_700_000_000)
    assert row["bucket"] == "configured"
    assert row["pack_id"] == "ready-pack"

    marker = home / "packs" / "ready-pack.configured.json"
    assert marker.is_file()
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data["pack_id"] == "ready-pack"
    assert data["configured_at"] == 1_700_000_000

    listed = pack_library.list_installed(home)
    assert any(r["pack_id"] == "ready-pack" and r["bucket"] == "configured" for r in listed)


def test_community_install_writes_configured_marker(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    body = {
        "schema_version": 1,
        "id": "community-ready",
        "version": "1.0.0",
        "label": "Community Ready",
        "author": "bucket marker tests",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    path = kb_extensions_install.atomic_install(
        home=home,
        pack_id="community-ready",
        body=json.dumps(body).encode("utf-8"),
    )
    assert path.is_file()
    assert (home / "packs" / "community-ready.configured.json").is_file()

    listed = pack_library.list_installed(home)
    assert any(r["pack_id"] == "community-ready" and r["bucket"] == "configured" for r in listed)


def test_paper_arm_writes_deployed_marker_for_library_pack(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    pack_path = _write_pack(home, "arm-me")

    result = PaperService(home=home, clock=lambda: 1_700_000_100).arm(
        pack_path,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
        correlation_id="bucket-arm",
    )
    assert result.ok, result.message

    deployed = home / "packs" / "arm-me.deployed.json"
    assert deployed.is_file()
    data = json.loads(deployed.read_text(encoding="utf-8"))
    assert data["pack_id"] == "arm-me"
    assert data["version"] == "1.0.0"
    assert isinstance(data["revision_id"], str) and len(data["revision_id"]) == 64
    assert data["deployed_at"] == 1_700_000_100

    listed = pack_library.list_installed(home)
    row = next(r for r in listed if r["pack_id"] == "arm-me")
    assert row["bucket"] == "deployed"
    assert row["version"] == "1.0.0"


def test_paper_disarm_demotes_deployed_to_configured(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    pack_path = _write_pack(home, "demote-me")
    service = PaperService(home=home, clock=lambda: 1_700_000_200)

    armed = service.arm(
        pack_path,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
        correlation_id="bucket-arm-then-disarm",
    )
    assert armed.ok, armed.message
    assert (home / "packs" / "demote-me.deployed.json").is_file()

    disarmed = service.disarm(venue="kraken", pair="SUIUSD", correlation_id="bucket-disarm")
    assert disarmed.ok, disarmed.message

    assert not (home / "packs" / "demote-me.deployed.json").exists()
    configured = home / "packs" / "demote-me.configured.json"
    assert configured.is_file()

    listed = pack_library.list_installed(home)
    row = next(r for r in listed if r["pack_id"] == "demote-me")
    assert row["bucket"] == "configured"


def test_mark_deployed_preserves_prior_revision_on_update(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _write_pack(home, "rev-pack", version="1.0.0")
    first = pack_library.mark_deployed(home, "rev-pack", now=10)
    assert first["bucket"] == "deployed"
    first_rev = json.loads((home / "packs" / "rev-pack.deployed.json").read_text(encoding="utf-8"))["revision_id"]

    _write_pack(home, "rev-pack", version="2.0.0")
    second = pack_library.mark_deployed(home, "rev-pack", now=20)
    assert second["bucket"] == "deployed"
    data = json.loads((home / "packs" / "rev-pack.deployed.json").read_text(encoding="utf-8"))
    assert data["version"] == "2.0.0"
    assert data["revision_id"] != first_rev
    assert data["prior_revision_id"] == first_rev
    assert second["rollback_ref"] == {
        "pack_id": "rev-pack",
        "prior_revision_id": first_rev,
    }


def test_mark_configured_refuses_unknown_pack(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    with pytest.raises(pack_library.InstallRefused) as caught:
        pack_library.mark_configured(home, "missing-pack")
    assert caught.value.code == "pack_not_found"


def test_draft_arm_path_does_not_write_library_deployed_marker(tmp_path: Path) -> None:
    """Arms from strategy draft paths are outside the pack library roots."""
    home = tmp_path / "home"
    home.mkdir()
    drafts = home / "strategies" / "drafts" / "solo"
    drafts.mkdir(parents=True)
    body = {
        "schema_version": 1,
        "id": "draft-only",
        "version": "1.0.0",
        "label": "Draft Only",
        "author": "bucket marker tests",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    draft_path = drafts / "pack.json"
    draft_path.write_text(json.dumps(body), encoding="utf-8")

    assert pack_library.library_pack_id_for_path(home, draft_path) is None

    result = PaperService(home=home).arm(
        draft_path,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
        correlation_id="draft-arm",
    )
    assert result.ok, result.message
    assert not (home / "packs" / "draft-only.deployed.json").exists()
    assert pack_library.list_installed(home) == []
