"""NS22: community.install — atomic stage-then-rename into the install dir.

The install helper stages the downloaded body in a separate temp directory
first, then publishes it into the existing community install directory with
a single atomic rename. A failure before the rename leaves the previous
installed file (if any) unchanged.

Three refusals are exercised end-to-end through `community.install`:

  * archive traversal — an entry name inside a tar body that escapes the
    staging directory (Zip Slip);
  * symlink escape — a tar entry whose link target resolves outside the
    staging directory;
  * body over the install size limit.

Each refusal raises `community.InstallPayloadError` before any write to
the destination directory, so the destination tree is unchanged.
"""

from __future__ import annotations

import json
import tarfile
from io import BytesIO

import pytest

PACK_URL = "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/evil-pack.json"
INDEX_BODY = json.dumps({"packs": [{"id": "evil-pack", "url": PACK_URL}]}).encode("utf-8")


class _FakeTransport:
    """In-memory transport that returns pre-cooked bytes for any URL."""

    def __init__(self, mapping: dict[str, bytes]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        if url in self.mapping:
            return self.mapping[url]
        raise AssertionError(f"unexpected url: {url}")


def _make_tar(entries: list[tuple[str, bytes | None, str | None]]) -> bytes:
    """Build a tar archive whose entries describe safety-test fixtures.

    Each entry is `(name, data_or_none, linkname_or_none)`. When
    `data_or_none` is None the entry is a symlink (and `linkname_or_none`
    is the link target); otherwise it is a regular file with the given
    bytes.
    """
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data, linkname in entries:
            info = tarfile.TarInfo(name=name)
            if data is None:
                info.type = tarfile.SYMTYPE
                info.linkname = linkname or ""
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, BytesIO(data))
    return buf.getvalue()


def test_install_refuses_archive_traversal(home):
    """A tar body with an entry whose path escapes the install directory
    is refused. `community.install` raises the typed `InstallPayloadError`
    and the destination tree is unchanged.
    """
    from krellbot import community as kb_community

    body = _make_tar(
        [
            ("good.txt", b"safe content", None),
            ("../evil.txt", b"escapes via ..", None),
        ]
    )
    transport = _FakeTransport({kb_community.INDEX_URL: INDEX_BODY, PACK_URL: body})

    with pytest.raises(kb_community.InstallPayloadError):
        kb_community.install("evil-pack", transport=transport, home=home)

    # Destination tree is unchanged: no pack file appears under community/.
    community_dir = home / "packs" / "community"
    assert not (community_dir / "evil-pack.json").exists()
    assert not community_dir.exists() or not any(community_dir.iterdir())


def test_install_refuses_symlink_escape(home):
    """A tar body with a symlink whose target resolves outside the
    install directory is refused. Destination tree is unchanged.
    """
    from krellbot import community as kb_community

    body = _make_tar(
        [
            ("escape", None, "/etc/passwd"),
        ]
    )
    transport = _FakeTransport({kb_community.INDEX_URL: INDEX_BODY, PACK_URL: body})

    with pytest.raises(kb_community.InstallPayloadError):
        kb_community.install("evil-pack", transport=transport, home=home)

    community_dir = home / "packs" / "community"
    assert not (community_dir / "evil-pack.json").exists()
    assert not community_dir.exists() or not any(community_dir.iterdir())


def test_install_refuses_oversize_body(home):
    """A body over the install size limit is refused. The body never
    touches the destination. The destination tree is unchanged.
    """
    from krellbot import community as kb_community

    # 1.5 MiB: clearly above any 1_000_000-byte limit.
    body = b"x" * (1_500_000)
    transport = _FakeTransport({kb_community.INDEX_URL: INDEX_BODY, PACK_URL: body})

    with pytest.raises(kb_community.InstallPayloadError):
        kb_community.install("evil-pack", transport=transport, home=home)

    community_dir = home / "packs" / "community"
    assert not (community_dir / "evil-pack.json").exists()
    assert not community_dir.exists() or not any(community_dir.iterdir())


def test_install_stages_then_atomic_renames_json_body(home):
    """The new helper must be called from `community.install`: a JSON body
    is staged in a temp directory, validated (size + archive checks), and
    atomically renamed into the install dir. The destination bytes match
    the body verbatim. A previous file, if any, would have been left
    untouched until the rename.
    """
    from krellbot import community as kb_community

    pack_bytes = json.dumps(
        {
            "schema_version": 1,
            "id": "good-pack",
            "version": "1.2.3",
            "label": "Good",
            "author": "Safe Author",
            "timeframe": "1h",
            "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
            "entry": ["close", ">", "sma20"],
            "exit": ["close", "<", "sma20"],
            "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
            "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
        }
    ).encode("utf-8")

    index_body = json.dumps(
        {
            "packs": [
                {
                    "id": "good-pack",
                    "url": (
                        "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/good-pack.json"
                    ),
                }
            ]
        }
    ).encode("utf-8")

    class _JsonTransport:
        def __init__(self):
            self.calls: list[str] = []

        def get(self, url: str) -> bytes:
            self.calls.append(url)
            if url == kb_community.INDEX_URL:
                return index_body
            if url.endswith("/good-pack.json"):
                return pack_bytes
            raise AssertionError(f"unexpected url: {url}")

    transport = _JsonTransport()
    target = kb_community.install("good-pack", transport=transport, home=home)

    assert target == home / "packs" / "community" / "good-pack.json"
    assert target.read_bytes() == pack_bytes


def test_install_previous_file_unchanged_on_failure(home):
    """If a previous install wrote a file to the destination, a refused
    install must leave that file's bytes unchanged.
    """
    from krellbot import community as kb_community

    # Lay down a previous install under the destination path.
    community_dir = home / "packs" / "community"
    community_dir.mkdir(parents=True, exist_ok=True)
    previous_bytes = json.dumps({"id": "evil-pack", "version": "0.0.1"}).encode("utf-8")
    previous_path = community_dir / "evil-pack.json"
    previous_path.write_bytes(previous_bytes)
    original_mtime = previous_path.stat().st_mtime_ns
    original_bytes = previous_path.read_bytes()

    # Now drive a refused install (oversize body).
    body = b"y" * (1_500_000)
    transport = _FakeTransport({kb_community.INDEX_URL: INDEX_BODY, PACK_URL: body})

    with pytest.raises(kb_community.InstallPayloadError):
        kb_community.install("evil-pack", transport=transport, home=home)

    # Previous file bytes and mtime are unchanged.
    assert previous_path.read_bytes() == original_bytes
    assert previous_path.stat().st_mtime_ns == original_mtime


def test_install_payload_error_is_a_value_error(home):
    """The new typed error subclasses `ValueError` so callers that catch
    `ValueError` (or any supertype) still handle the refusal correctly.
    """
    from krellbot import community as kb_community

    assert issubclass(kb_community.InstallPayloadError, ValueError)

    body = b"z" * (1_500_000)
    transport = _FakeTransport({kb_community.INDEX_URL: INDEX_BODY, PACK_URL: body})

    with pytest.raises(ValueError):
        kb_community.install("evil-pack", transport=transport, home=home)
