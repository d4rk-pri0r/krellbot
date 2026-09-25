"""A pack you wrote does not need a license. Paid catalog packs do."""

from pathlib import Path

from krellbot.catalog import requires_license_for


def test_user_pack_does_not_require_a_license(tmp_path: Path) -> None:
    home = tmp_path / "kb"
    pack = home / "packs" / "mine.json"
    pack.parent.mkdir(parents=True)
    pack.write_text("{}", encoding="utf-8")
    assert requires_license_for(pack, home) is False


def test_paid_catalog_pack_requires_a_license(tmp_path: Path) -> None:
    home = tmp_path / "kb"
    pack = home / "packs" / "catalog" / "triple-stack.json"
    pack.parent.mkdir(parents=True)
    pack.write_text("{}", encoding="utf-8")
    assert requires_license_for(pack, home) is True
