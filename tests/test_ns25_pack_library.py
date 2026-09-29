"""NS25 — pack library UX with state buckets.

Tests for ``list_installed`` (the production pack-listing API used by the
dashboard) and ``update_pack``. The brief requires:

  1. Every pack returned by ``list_installed`` is classified into one of
     five buckets: ``purchased``, ``download_pending``, ``installed``,
     ``configured``, ``deployed``.
  2. ``list_installed`` returns ``rollback_ref`` for every deployed pack
     that has a prior installed version. ``rollback_ref`` is ``None``
     when there is no prior version.
  3. ``update_pack(home, pack_id, new_version)`` refuses when the
     deployed record's ``revision_id`` differs from the installed
     record's ``revision_id`` — the refusal is typed and leaves no
     on-disk change.
  4. ``list_installed`` reads the cached catalog from
     ``<home>/catalog/catalog.json`` when present and returns the
     purchased packs from there without any network call.

These tests use an isolated ``home`` so no real ``~/.krellbot`` and no
real network transport are involved.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from krellbot.ui.packs import list_installed, update_pack

# ---- helpers --------------------------------------------------------------


def _canonical_json(pack: dict) -> bytes:
    """Canonical v1 JSON for revision-id derivation.

    Mirrors ``krellbot.application.strategy._canonical_bytes``: sorted
    keys, ``(",", ":")`` separators, UTF-8.
    """
    return json.dumps(pack, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _revision_id(pack: dict) -> str:
    return hashlib.sha256(_canonical_json(pack)).hexdigest()


def _write_pack(home: Path, pack_id: str, version: str = "1.0.0") -> Path:
    """Write a runnable DSL pack under <home>/packs/<pack_id>.json."""
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": version,
        "label": f"Pack {pack_id}",
        "author": "ns25 tests",
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


def _write_deployed(
    home: Path,
    pack_id: str,
    *,
    version: str,
    revision_id: str,
    prior_revision_id: str | None = None,
) -> Path:
    """Write a deployed-state record for ``pack_id``.

    The deployed record carries the revision_id of the bytes that are
    currently in use, plus an optional prior revision_id for rollback.
    """
    packs = home / "packs"
    target = packs / f"{pack_id}.deployed.json"
    payload: dict = {
        "schema_version": "1",
        "pack_id": pack_id,
        "version": version,
        "revision_id": revision_id,
        "deployed_at": 1700000000,
        "permissions": ["trade"],
    }
    if prior_revision_id is not None:
        payload["prior_revision_id"] = prior_revision_id
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def _write_configured(home: Path, pack_id: str) -> Path:
    """Write a configured-state marker for ``pack_id``."""
    packs = home / "packs"
    target = packs / f"{pack_id}.configured.json"
    target.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "pack_id": pack_id,
                "configured_at": 1700000000,
                "permissions": [],
            }
        ),
        encoding="utf-8",
    )
    return target


def _write_download_pending(home: Path, pack_id: str) -> Path:
    """Write a download-pending marker for ``pack_id``."""
    packs = home / "packs"
    target = packs / f"{pack_id}.download_pending.json"
    target.write_text(
        json.dumps({"schema_version": "1", "pack_id": pack_id}),
        encoding="utf-8",
    )
    return target


def _write_catalog(home: Path, packs: list[dict]) -> Path:
    """Write a cached catalog under <home>/catalog/catalog.json."""
    catalog_dir = home / "catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    target = catalog_dir / "catalog.json"
    target.write_text(json.dumps({"packs": packs}), encoding="utf-8")
    return target


# ---- 1. all five buckets are returned distinct ----------------------------


def test_list_installed_classifies_every_pack_into_one_of_five_buckets(home: Path) -> None:
    """A real caller seeds one pack per bucket; ``list_installed`` returns
    all five buckets distinct. No helper is used — the production API is
    invoked end-to-end against a fresh tmpdir.
    """
    # bucket: deployed — pack file + deployed record with prior revision
    deployed_pack = _write_pack(home, "alpha", version="2.0.0")
    deployed_rev = _revision_id(_read(deployed_pack))
    _write_deployed(
        home,
        "alpha",
        version="2.0.0",
        revision_id=deployed_rev,
        prior_revision_id="0" * 64,
    )

    # bucket: configured — pack file + configured record, no deployed record
    _write_pack(home, "bravo", version="1.0.0")
    _write_configured(home, "bravo")

    # bucket: installed — pack file only
    _write_pack(home, "charlie", version="1.0.0")

    # bucket: download_pending — only a download marker
    _write_download_pending(home, "delta")

    # bucket: purchased — only in the cached catalog
    _write_catalog(
        home,
        [
            {
                "id": "echo",
                "version": "1.0.0",
                "label": "Echo paid pack",
                "permissions": [],
            }
        ],
    )

    rows = list_installed(home)
    by_id = {row["pack_id"]: row for row in rows}

    expected_ids = {"alpha", "bravo", "charlie", "delta", "echo"}
    assert set(by_id) == expected_ids, (set(by_id), expected_ids)

    assert by_id["alpha"]["bucket"] == "deployed"
    assert by_id["bravo"]["bucket"] == "configured"
    assert by_id["charlie"]["bucket"] == "installed"
    assert by_id["delta"]["bucket"] == "download_pending"
    assert by_id["echo"]["bucket"] == "purchased"

    # Every row carries the contract fields.
    for pack_id, row in by_id.items():
        assert isinstance(row["bucket"], str)
        assert isinstance(row["pack_id"], str) and row["pack_id"] == pack_id
        assert "version" in row
        assert "permissions" in row and isinstance(row["permissions"], list)
        assert "rollback_ref" in row


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---- 2. rollback_ref contract --------------------------------------------


def test_rollback_ref_set_when_deployed_has_prior_revision(home: Path) -> None:
    """A deployed pack with a prior revision_id carries a non-None
    ``rollback_ref`` in the returned row.
    """
    _write_pack(home, "foxtrot", version="2.0.0")
    _write_deployed(
        home,
        "foxtrot",
        version="2.0.0",
        revision_id=_revision_id(
            {
                "schema_version": 1,
                "id": "foxtrot",
                "version": "2.0.0",
                "label": "Pack foxtrot",
                "author": "ns25 tests",
                "timeframe": "1h",
                "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
                "entry": ["close", ">", "sma20"],
                "exit": ["close", "<", "sma20"],
                "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
                "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
            }
        ),
        prior_revision_id="0" * 64,
    )

    rows = list_installed(home)
    foxtrot = next(r for r in rows if r["pack_id"] == "foxtrot")
    assert foxtrot["bucket"] == "deployed"
    assert foxtrot["rollback_ref"] is not None
    # The rollback reference identifies the prior revision, not the
    # currently-deployed one. The shape is closed: a dict with at
    # minimum the prior revision_id and a pack id so the dashboard can
    # render a deterministic button.
    assert foxtrot["rollback_ref"]["prior_revision_id"] == "0" * 64
    assert foxtrot["rollback_ref"]["pack_id"] == "foxtrot"


def test_rollback_ref_none_when_deployed_has_no_prior(home: Path) -> None:
    """A deployed pack with no prior_revision_id carries a None rollback_ref."""
    _write_pack(home, "golf", version="1.0.0")
    _write_deployed(
        home,
        "golf",
        version="1.0.0",
        revision_id="any-rev",
        prior_revision_id=None,
    )

    rows = list_installed(home)
    golf = next(r for r in rows if r["pack_id"] == "golf")
    assert golf["bucket"] == "deployed"
    assert golf["rollback_ref"] is None


def test_rollback_ref_none_for_non_deployed_buckets(home: Path) -> None:
    """Non-deployed buckets never carry a rollback_ref."""
    _write_pack(home, "hotel", version="1.0.0")  # installed
    _write_pack(home, "india", version="1.0.0")
    _write_configured(home, "india")  # configured
    _write_download_pending(home, "juliet")  # download_pending
    _write_catalog(home, [{"id": "kilo", "version": "1.0.0"}])  # purchased

    rows = list_installed(home)
    by_id = {row["pack_id"]: row for row in rows}
    for pack_id in ("hotel", "india", "juliet", "kilo"):
        assert by_id[pack_id]["rollback_ref"] is None, pack_id


# ---- 3. update_pack refuses when revisions differ ------------------------


def test_update_pack_refuses_when_deployed_revision_differs(home: Path) -> None:
    """If the deployed record's revision_id does not match the installed
    file's revision_id, ``update_pack`` raises a typed refusal and
    leaves the installed file unchanged.
    """
    pack_path = _write_pack(home, "lima", version="1.0.0")
    installed_rev = _revision_id(json.loads(pack_path.read_text(encoding="utf-8")))

    # Deployed record points at a DIFFERENT revision_id than the
    # installed file. This simulates: a new version has been installed
    # but the deployed version hasn't been bumped yet.
    _write_deployed(
        home,
        "lima",
        version="1.0.0",
        revision_id="different-revision-id",
    )

    # Sanity: installed and deployed revision_ids actually differ.
    assert installed_rev != "different-revision-id"

    with pytest.raises(Exception) as excinfo:
        update_pack(home, "lima", "2.0.0")

    # Typed refusal: the exception has a stable attribute the caller
    # pattern-matches on, and it carries a non-empty message.
    err = excinfo.value
    assert getattr(err, "code", None) == "deployed_revision_mismatch"
    assert getattr(err, "deployed_revision_id", None) == "different-revision-id"
    assert getattr(err, "installed_revision_id", None) == installed_rev
    assert "lima" in str(err)

    # No on-disk change to the installed file.
    after = json.loads(pack_path.read_text(encoding="utf-8"))
    assert after["version"] == "1.0.0"


def test_update_pack_succeeds_when_no_deployed_record(home: Path) -> None:
    """With no deployed record, ``update_pack`` rewrites the installed file."""
    pack_path = _write_pack(home, "mike", version="1.0.0")

    update_pack(home, "mike", "2.0.0")

    after = json.loads(pack_path.read_text(encoding="utf-8"))
    assert after["version"] == "2.0.0"
    assert after["id"] == "mike"


def test_update_pack_succeeds_when_revisions_match(home: Path) -> None:
    """When the deployed record's revision_id matches the installed
    file's revision_id, ``update_pack`` rewrites the installed file.
    """
    pack_path = _write_pack(home, "november", version="1.0.0")
    installed_rev = _revision_id(json.loads(pack_path.read_text(encoding="utf-8")))
    _write_deployed(
        home,
        "november",
        version="1.0.0",
        revision_id=installed_rev,
    )

    update_pack(home, "november", "2.0.0")

    after = json.loads(pack_path.read_text(encoding="utf-8"))
    assert after["version"] == "2.0.0"


def test_update_pack_unknown_pack_raises(home: Path) -> None:
    """Calling ``update_pack`` for a pack with no installed file raises."""
    with pytest.raises(Exception) as excinfo:
        update_pack(home, "ghost-pack", "1.0.0")
    assert getattr(excinfo.value, "code", None) == "pack_not_found"


# ---- 4. cached catalog is read offline -----------------------------------


def test_list_installed_reads_catalog_when_no_network(home: Path) -> None:
    """``list_installed`` returns catalog-only packs without any fetch.

    No pack file, no deployed record, no configured record, no download
    marker — just a cached catalog. The test never installs a transport
    and asserts the purchased bucket appears in the response.
    """
    _write_catalog(
        home,
        [
            {"id": "oscar", "version": "1.0.0", "label": "Oscar"},
            {"id": "papa", "version": "2.0.0", "label": "Papa"},
        ],
    )

    rows = list_installed(home)
    by_id = {row["pack_id"]: row for row in rows}

    assert by_id["oscar"]["bucket"] == "purchased"
    assert by_id["papa"]["bucket"] == "purchased"
    assert by_id["oscar"]["version"] == "1.0.0"
    assert by_id["papa"]["version"] == "2.0.0"


def test_list_installed_ignores_missing_catalog(home: Path) -> None:
    """No catalog and no packs on disk: ``list_installed`` returns []."""
    rows = list_installed(home)
    assert rows == []
