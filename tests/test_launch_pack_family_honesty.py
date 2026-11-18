"""Launch pack family honesty — one DCA family for Paid 1.0 (M21.2).

Pins:

  * shipped ``paid-launch-dca`` pack validates and carries honesty origin
  * catalogue fixture description: no returns promises; fixture/backtest
    labeled; not personalized advice
  * signed catalogue ``pack_sha256`` matches installed bytes
  * ``PAPER_ONLY_RELEASE`` stays True

Isolated ``KRELLBOT_HOME``; fake processors only; no exchange credentials.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from krellbot.packs import launch_family
from krellbot.release_policy import PAPER_ONLY_RELEASE

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "catalogue" / "launch_pack_family.json"


def test_paper_only_release_untouched() -> None:
    assert PAPER_ONLY_RELEASE is True


def test_shipped_launch_pack_is_dca_family_and_honest() -> None:
    pack = launch_family.load_pack()
    assert pack["id"] == launch_family.SKU_ID == "paid-launch-dca"
    assert "mode" not in pack  # reserved mode id stays mode-dca
    assert pack["timeframe"] in {"1h", "4h", "1d"}
    assert isinstance(pack["risk"]["max_account_pct"], int)
    origin = str(pack["origin"])
    assert "dca" in origin.lower()
    launch_family.assert_required_honesty_phrases(origin)
    launch_family.assert_no_returns_promises(origin)
    assert "not personalized advice" in origin.lower()
    assert "fixture" in origin.lower()
    assert "backtest" in origin.lower()


def test_catalogue_fixture_honesty_and_sha_matches_shipped_bytes() -> None:
    document = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    packs = document["packs"]
    assert len(packs) == 1
    entry = packs[0]
    assert entry["id"] == "paid-launch-dca"
    assert entry["tier"] == "paid"
    launch_family.assert_required_honesty_phrases(entry["description"])
    launch_family.assert_no_returns_promises(entry["description"])

    expected = launch_family.pack_sha256()
    assert entry["pack_sha256"] == expected
    validated = launch_family.validate_catalogue_entry(entry)
    assert validated["ok"] is True
    assert validated["pack_sha256"] == expected


def test_installed_bytes_match_signed_catalogue_pack_sha256(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    entry = launch_family.catalogue_entry()
    result = launch_family.install_pack_bytes(home)
    assert result["pack_id"] == "paid-launch-dca"
    assert result["pack_sha256"] == entry["pack_sha256"]

    installed_path = home / "packs" / "paid-launch-dca.json"
    installed = installed_path.read_bytes()
    assert hashlib.sha256(installed).hexdigest() == entry["pack_sha256"]
    launch_family.validate_catalogue_entry(entry, installed_bytes=installed)

    # Tampered installed bytes must fail the match check.
    tampered = json.loads(installed.decode("utf-8"))
    tampered["label"] = "Guaranteed returns DCA"
    bad_bytes = json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with pytest.raises(launch_family.LaunchFamilyHonestyError) as caught:
        launch_family.validate_catalogue_entry(entry, installed_bytes=bad_bytes)
    assert caught.value.code == "bytes_mismatch"


def test_returns_promise_copy_is_refused() -> None:
    with pytest.raises(launch_family.LaunchFamilyHonestyError) as caught:
        launch_family.assert_no_returns_promises(
            "This pack offers guaranteed returns and is not personalized advice. fixture backtest"
        )
    assert caught.value.code == "returns_promise"

    with pytest.raises(launch_family.LaunchFamilyHonestyError):
        launch_family.assert_required_honesty_phrases("DCA mode pack with no disclosures")


def test_dishonest_catalogue_description_refused() -> None:
    entry = launch_family.catalogue_entry()
    entry["description"] = "Launch DCA with guaranteed profit. fixture backtest not personalized advice."
    with pytest.raises(launch_family.LaunchFamilyHonestyError) as caught:
        launch_family.validate_catalogue_entry(entry)
    assert caught.value.code == "returns_promise"


def test_honesty_document_and_ui_copy_stay_aligned() -> None:
    doc = launch_family.honesty_document()
    assert doc["family_id"] == "dca"
    assert doc["sku"] == "paid-launch-dca"
    launch_family.assert_required_honesty_phrases(doc["ui_honesty"])
    launch_family.assert_required_honesty_phrases(doc["catalogue_description"])
    assert "fixture" in doc["fixture_backtest_label"].lower()
    assert "backtest" in doc["fixture_backtest_label"].lower()
    assert "live market performance" in doc["fixture_backtest_label"].lower()
