"""Issue #242: confine community pack installs to staging/install dirs.

The requested pack id is used as the staged file name and the installed
file name, so an id containing path syntax can escape both directories.
This suite drives the *actual* ``community.install`` and
``extensions.install.atomic_install`` seams with a private synthetic
HOME/TMPDIR and an injected in-memory transport; no network is used.

Sentinel invariants asserted for every refusal:

  * a private synthetic sibling just outside ``packs/community`` keeps
    its original bytes;
  * an unrelated file in the staging parent (TMPDIR) whose name matches
    the escaped staged path is not truncated or consumed;
  * ``packs/community`` stays empty;
  * only the index and pack URLs are fetched.

Valid one-segment ids - ASCII and Unicode - keep installing verbatim,
and the existing payload checks (embedded id mismatch, tar traversal)
still refuse before any destination write.
"""

from __future__ import annotations

import json
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

import pytest

PRIVATE_SENTINEL = b"PRIVATE-SIBLING-SENTINEL"
STAGING_SENTINEL = b"UNRELATED-STAGING-PARENT-SENTINEL"

PACK_URL = "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/pack.json"


class _Transport:
    """In-memory transport: no socket, no urllib, no real HTTP."""

    def __init__(self, mapping: dict[str, bytes]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        if url in self.mapping:
            return self.mapping[url]
        raise AssertionError(f"unexpected url: {url}")


def _index(pack_id: str) -> bytes:
    return json.dumps({"packs": [{"id": pack_id, "url": PACK_URL}]}).encode("utf-8")


def _pack_bytes(pack_id: str) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "id": pack_id,
            "version": "1.0.0",
            "label": "Synthetic",
            "author": "Synthetic Author",
            "timeframe": "1h",
            "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
            "entry": ["close", ">", "sma20"],
            "exit": ["close", "<", "sma20"],
            "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
            "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
        }
    ).encode("utf-8")


def _files(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def staging_parent(home, monkeypatch):
    """Private TMPDIR with an unrelated file matching the escaped name."""
    parent = home / "staging-parent"
    parent.mkdir()
    (parent / "synthetic-victim.json").write_bytes(STAGING_SENTINEL)
    monkeypatch.setattr(tempfile, "tempdir", str(parent))
    return parent


@pytest.fixture
def private_sibling(home):
    """Private synthetic sibling just outside packs/community."""
    sibling = home / "packs" / "synthetic-victim.json"
    sibling.parent.mkdir(parents=True, exist_ok=True)
    sibling.write_bytes(PRIVATE_SENTINEL)
    return sibling


def _assert_confined(home, private_sibling, staging_parent, transport) -> None:
    from krellbot import community as kb_community

    assert private_sibling.read_bytes() == PRIVATE_SENTINEL
    assert (staging_parent / "synthetic-victim.json").read_bytes() == STAGING_SENTINEL
    community_dir = home / "packs" / "community"
    assert not community_dir.exists() or not any(community_dir.iterdir())
    assert transport.calls == [kb_community.INDEX_URL, PACK_URL]


def test_install_refuses_parent_traversal_pack_id_before_staging_or_destination(home, private_sibling, staging_parent):
    """Requested id ``../synthetic-victim`` must be refused with the typed
    ``InstallPayloadError`` before the staging file or destination is
    touched: the private sibling outside ``packs/community`` and the
    unrelated staging-parent file both keep their bytes.

    On base this escapes: the staging file truncates the staging-parent
    file, which is then renamed over the private sibling.
    """
    from krellbot import community as kb_community

    pack_id = "../synthetic-victim"
    transport = _Transport({kb_community.INDEX_URL: _index(pack_id), PACK_URL: _pack_bytes(pack_id)})

    before_home_files = _files(home)

    with pytest.raises(kb_community.InstallPayloadError) as excinfo:
        kb_community.install(pack_id, transport=transport, home=home)

    assert str(excinfo.value).startswith("community pack id is not a single path segment: ")
    assert _files(home) == before_home_files
    _assert_confined(home, private_sibling, staging_parent, transport)


def test_atomic_install_refuses_traversal_pack_id_before_staging(home, private_sibling, staging_parent):
    """The shared ``atomic_install`` seam itself refuses a traversal id
    before the staging directory or the install destination is touched,
    so every caller is confined, not just ``community.install``.

    On base this returns the escaped destination and mutates both
    sentinels.
    """
    from krellbot import community as kb_community
    from krellbot.extensions import install as kb_install

    pack_id = "../synthetic-victim"
    before_home_files = _files(home)

    with pytest.raises(kb_community.InstallPayloadError) as excinfo:
        kb_install.atomic_install(home=home, pack_id=pack_id, body=_pack_bytes(pack_id))

    assert str(excinfo.value).startswith("community pack id is not a single path segment: ")
    assert _files(home) == before_home_files
    assert private_sibling.read_bytes() == PRIVATE_SENTINEL
    assert (staging_parent / "synthetic-victim.json").read_bytes() == STAGING_SENTINEL
    assert sorted(p.name for p in staging_parent.iterdir()) == ["synthetic-victim.json"]


def test_install_refuses_absolute_posix_pack_id(home, private_sibling, staging_parent):
    """An absolute POSIX id names a file outside both directories and is
    refused before any write; its sentinel file keeps its bytes.

    On base the staged name and destination both resolve to the absolute
    path, so the sentinel is truncated and re-published.
    """
    from krellbot import community as kb_community

    absolute = home / "absolute-victim.json"
    absolute.write_bytes(PRIVATE_SENTINEL)
    pack_id = str(absolute)
    transport = _Transport({kb_community.INDEX_URL: _index(pack_id), PACK_URL: _pack_bytes(pack_id)})

    with pytest.raises(kb_community.InstallPayloadError) as excinfo:
        kb_community.install(pack_id, transport=transport, home=home)

    assert str(excinfo.value).startswith("community pack id is not a single path segment: ")
    assert absolute.read_bytes() == PRIVATE_SENTINEL
    _assert_confined(home, private_sibling, staging_parent, transport)


@pytest.mark.parametrize("pack_id", ["example", "pack.v2", "p\u00e4ck-\u4f8b"])
def test_install_accepts_valid_one_segment_pack_id_verbatim(home, private_sibling, staging_parent, pack_id):
    """Control: ordinary, dotted and non-ASCII one-segment ids keep
    installing, with raw body bytes and the `author` field preserved.

    Passes on base and head: confinement must not become a slug-only
    restriction.
    """
    from krellbot import community as kb_community

    body = _pack_bytes(pack_id)
    transport = _Transport({kb_community.INDEX_URL: _index(pack_id), PACK_URL: body})

    target = kb_community.install(pack_id, transport=transport, home=home)

    expected = home / "packs" / "community" / f"{pack_id}.json"
    assert target == expected
    assert target.read_bytes() == body
    assert json.loads(target.read_bytes())["author"] == "Synthetic Author"
    # Only the pre-existing unrelated staging-parent file remains there.
    assert sorted(p.name for p in staging_parent.iterdir()) == ["synthetic-victim.json"]
    assert private_sibling.read_bytes() == PRIVATE_SENTINEL
    assert transport.calls == [kb_community.INDEX_URL, PACK_URL]


def test_install_still_refuses_mismatched_embedded_id(home, private_sibling, staging_parent):
    """Control: the existing embedded-id identity check is unchanged - a
    body whose `id` differs from the requested id is refused before any
    destination write. Passes on base and head.
    """
    from krellbot import community as kb_community

    pack_id = "example"
    body = _pack_bytes("different-pack")
    transport = _Transport({kb_community.INDEX_URL: _index(pack_id), PACK_URL: body})
    before_home_files = _files(home)

    with pytest.raises(kb_community.InstallPayloadError) as excinfo:
        kb_community.install(pack_id, transport=transport, home=home)

    assert "does not match requested pack id" in str(excinfo.value)
    assert _files(home) == before_home_files
    _assert_confined(home, private_sibling, staging_parent, transport)


def test_install_still_refuses_tar_traversal_entry(home, private_sibling, staging_parent):
    """Control: the existing tar traversal check is unchanged - an entry
    named `../evil.txt` is refused before the destination rename.
    Passes on base and head.
    """
    from krellbot import community as kb_community

    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in (("good.txt", b"safe"), ("../evil.txt", b"escape")):
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, BytesIO(data))
    body = buf.getvalue()
    pack_id = "example"
    transport = _Transport({kb_community.INDEX_URL: _index(pack_id), PACK_URL: body})
    before_home_files = _files(home)

    with pytest.raises(kb_community.InstallPayloadError) as excinfo:
        kb_community.install(pack_id, transport=transport, home=home)

    assert "refuses archive traversal" in str(excinfo.value)
    assert _files(home) == before_home_files
    _assert_confined(home, private_sibling, staging_parent, transport)


@pytest.mark.parametrize(
    "pack_id",
    [
        "subdir/pack",
        "subdir\\pack",
        "..\\synthetic-victim",
        "C:\\synthetic-victim",
        "C:/synthetic-victim",
        "C:synthetic-victim",
        "\\\\server\\share\\victim",
        "pack\x00evil",
        ".",
        "..",
    ],
)
def test_install_refuses_compound_windows_and_nul_pack_ids(home, private_sibling, staging_parent, pack_id):
    """POSIX separators, Windows separators/drive/UNC forms, NUL and
    path-special components are refused with the typed error before the
    staging file or destination is written.

    On base these either escape as a literal path segment, raise a raw
    OSError/ValueError, or are installed under a Windows-interpreted
    path.
    """
    from krellbot import community as kb_community

    transport = _Transport({kb_community.INDEX_URL: _index(pack_id), PACK_URL: _pack_bytes(pack_id)})
    before_home_files = _files(home)

    with pytest.raises(kb_community.InstallPayloadError) as excinfo:
        kb_community.install(pack_id, transport=transport, home=home)

    assert str(excinfo.value).startswith("community pack id is not a single path segment: ")
    assert _files(home) == before_home_files
    _assert_confined(home, private_sibling, staging_parent, transport)
