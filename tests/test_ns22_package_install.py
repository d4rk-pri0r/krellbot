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

Four more refusals/properties cover the raw (non-tar) body identity:

  * malformed bytes — a body that is not strict UTF-8 JSON is refused;
  * mismatched id — a JSON body whose embedded `id` is not the requested
    pack id is refused, so an index entry cannot swap content under a
    trusted name;
  * no prior install — a refused body creates nothing;
  * matching id — a valid pack installs byte-for-byte and needs no license.

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

EXAMPLE_URL = "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/example.json"
EXAMPLE_INDEX_BODY = json.dumps({"packs": [{"id": "example", "url": EXAMPLE_URL}]}).encode("utf-8")


def _example_pack_bytes() -> bytes:
    """A complete, valid DSL pack whose id is exactly `example`."""
    return json.dumps(
        {
            "schema_version": 1,
            "id": "example",
            "version": "1.0.0",
            "label": "Example",
            "author": "Safe Author",
            "timeframe": "1h",
            "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
            "entry": ["close", ">", "sma20"],
            "exit": ["close", "<", "sma20"],
            "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
            "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
        }
    ).encode("utf-8")


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


def test_install_refuses_malformed_json_body_with_prior_install(home):
    """A non-tar body that is not JSON at all is refused. A previous
    install of the same id is left byte-for-byte unchanged, mtime included.
    """
    from krellbot import community as kb_community

    community_dir = home / "packs" / "community"
    community_dir.mkdir(parents=True, exist_ok=True)
    previous_path = community_dir / "example.json"
    previous_path.write_bytes(b'{"schema_version": 1, "id": "example", "version": "0.0.1"}')
    original_bytes = previous_path.read_bytes()
    original_mtime = previous_path.stat().st_mtime_ns

    transport = _FakeTransport({kb_community.INDEX_URL: EXAMPLE_INDEX_BODY, EXAMPLE_URL: b"not-json"})

    with pytest.raises(kb_community.InstallPayloadError):
        kb_community.install("example", transport=transport, home=home)

    assert previous_path.read_bytes() == original_bytes
    assert previous_path.stat().st_mtime_ns == original_mtime


def test_install_refuses_mismatched_embedded_id_with_prior_install(home):
    """A non-tar JSON body whose embedded id is not the requested pack id is
    refused. A previous install of the requested id survives unchanged.
    """
    from krellbot import community as kb_community

    community_dir = home / "packs" / "community"
    community_dir.mkdir(parents=True, exist_ok=True)
    previous_path = community_dir / "example.json"
    previous_path.write_bytes(b'{"schema_version": 1, "id": "example", "version": "0.0.1"}')
    original_bytes = previous_path.read_bytes()
    original_mtime = previous_path.stat().st_mtime_ns

    body = json.dumps({"id": "different-pack"}).encode("utf-8")
    transport = _FakeTransport({kb_community.INDEX_URL: EXAMPLE_INDEX_BODY, EXAMPLE_URL: body})

    with pytest.raises(kb_community.InstallPayloadError):
        kb_community.install("example", transport=transport, home=home)

    assert previous_path.read_bytes() == original_bytes
    assert previous_path.stat().st_mtime_ns == original_mtime
    # The impostor is not installed under any other name either.
    assert not (community_dir / "different-pack.json").exists()


def test_install_refuses_bad_body_when_no_prior_install(home):
    """With no previous install, a malformed or mismatched-id body must not
    create one. Nothing lands under packs/community/.
    """
    from krellbot import community as kb_community

    for body in (b"not-json", json.dumps({"id": "different-pack"}).encode("utf-8")):
        transport = _FakeTransport({kb_community.INDEX_URL: EXAMPLE_INDEX_BODY, EXAMPLE_URL: body})

        with pytest.raises(kb_community.InstallPayloadError):
            kb_community.install("example", transport=transport, home=home)

        community_dir = home / "packs" / "community"
        assert not (community_dir / "example.json").exists()
        assert not community_dir.exists() or not any(community_dir.iterdir())


def test_install_matching_id_body_written_verbatim_and_importable_free(home):
    """A valid raw JSON pack whose id matches the requested id installs
    byte-for-byte and is usable with no paid account: it is discovered as a
    DSL pack and requires no license.
    """
    from krellbot import catalog as kb_catalog
    from krellbot import community as kb_community
    from krellbot.pack import discover

    body = _example_pack_bytes()
    transport = _FakeTransport({kb_community.INDEX_URL: EXAMPLE_INDEX_BODY, EXAMPLE_URL: body})

    target = kb_community.install("example", transport=transport, home=home)

    assert target == home / "packs" / "community" / "example.json"
    assert target.read_bytes() == body

    found = {path: (kind, data) for path, kind, data in discover(home)}
    assert target in found
    kind, data = found[target]
    assert kind == "dsl"
    assert data["id"] == "example"
    assert kb_catalog.requires_license_for(target, home) is False


NONSTANDARD_CONSTANT_BODIES = [
    b'{"id": "example", "risk": NaN}',
    b'{"id": "example", "value": Infinity}',
    b'{"id": "example", "value": -Infinity}',
    b'{"id": "example", "risk": {"stop": {"type": "pct", "pct": NaN}}}',
]


@pytest.mark.parametrize("body", NONSTANDARD_CONSTANT_BODIES, ids=["nan", "infinity", "neg-infinity", "nested-risk-stop-pct-nan"])
def test_install_refuses_nonstandard_json_constants_with_prior_install(home, body):
    """A non-tar body containing the nonstandard JSON constants NaN,
    Infinity or -Infinity anywhere in the document is refused before any
    destination mutation, so an existing install of the same id survives
    byte-for-byte with its mtime intact.
    """
    from krellbot import community as kb_community

    community_dir = home / "packs" / "community"
    community_dir.mkdir(parents=True, exist_ok=True)
    previous_path = community_dir / "example.json"
    previous_path.write_bytes(b'{"schema_version": 1, "id": "example", "version": "0.0.1"}')
    original_bytes = previous_path.read_bytes()
    original_mtime = previous_path.stat().st_mtime_ns

    transport = _FakeTransport({kb_community.INDEX_URL: EXAMPLE_INDEX_BODY, EXAMPLE_URL: body})

    with pytest.raises(kb_community.InstallPayloadError) as excinfo:
        kb_community.install("example", transport=transport, home=home)

    # Refused at the JSON-constant boundary, not by an unrelated guard.
    assert "NaN" in str(excinfo.value) or "Infinity" in str(excinfo.value)

    assert previous_path.read_bytes() == original_bytes
    assert previous_path.stat().st_mtime_ns == original_mtime


@pytest.mark.parametrize("body", NONSTANDARD_CONSTANT_BODIES, ids=["nan", "infinity", "neg-infinity", "nested-risk-stop-pct-nan"])
def test_install_refuses_nonstandard_json_constants_when_no_prior_install(home, body):
    """With no previous install, a body carrying NaN/Infinity/-Infinity
    must not create one: neither the pack file nor the destination
    directory appears.
    """
    from krellbot import community as kb_community

    transport = _FakeTransport({kb_community.INDEX_URL: EXAMPLE_INDEX_BODY, EXAMPLE_URL: body})

    with pytest.raises(kb_community.InstallPayloadError):
        kb_community.install("example", transport=transport, home=home)

    community_dir = home / "packs" / "community"
    assert not (community_dir / "example.json").exists()
    assert not community_dir.exists() or not any(community_dir.iterdir())


def test_install_accepts_literal_constant_strings_unchanged(home):
    """The constants rule is lexical, not textual: a strict-JSON body whose
    *strings* merely contain the words NaN/Infinity stays valid and installs
    byte-for-byte.
    """
    from krellbot import community as kb_community

    body = json.dumps(
        {
            "schema_version": 1,
            "id": "example",
            "version": "1.0.0",
            "label": "NaN but textual",
            "author": "Infinity and beyond",
            "notes": ["Infinity", "NaN"],
        }
    ).encode("utf-8")
    transport = _FakeTransport({kb_community.INDEX_URL: EXAMPLE_INDEX_BODY, EXAMPLE_URL: body})

    target = kb_community.install("example", transport=transport, home=home)

    assert target.read_bytes() == body


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
