"""C75: community install typed refusals for invalid-UTF-8 index/pack body.

Two refusal-boundary regressions in the community INSTALL path, driven
through the real ``cli._cmd_community_install`` seam with an injected
stub transport — the project's own documented test seam
(``_UrllibGetTransport``: "Tests inject their own.") — never a fake HTTP
layer, never the network.

BASE (main 0bdf126) behavior reproduced by this suite through that seam:

  * an index body that is not valid UTF-8 escaped the CLI boundary as a
    raw ``UnicodeDecodeError`` traceback (``community.install`` caught
    only ``json.JSONDecodeError`` at the index decode);
  * a pack body that is not valid UTF-8 escaped as a raw
    ``kb_community.InstallPayloadError`` traceback (the typed class was
    missing from the ``_cmd_community_install`` catch set).

HEAD behavior required by this suite:

  * invalid-UTF-8 index -> typed ``IndexError_`` one-liner on stderr,
    rc 1, nothing installed;
  * invalid-UTF-8 pack body -> typed ``InstallPayloadError`` one-liner
    on stderr (raised by ``extensions/install.py``
    ``_validate_raw_json_identity``), rc 1, nothing installed;
  * controls unchanged: torn-JSON index one-liner byte-identical, and a
    healthy install still returns rc 0 with the pack file written
    verbatim.
"""

from __future__ import annotations

import json

import pytest

EXAMPLE_URL = "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/example.json"
INDEX_BODY = json.dumps({"packs": [{"id": "example", "url": EXAMPLE_URL}]}).encode("utf-8")

# 0xff is never a valid UTF-8 start byte, so these bodies fail decode
# before any JSON parsing could happen.
BAD_UTF8_INDEX = b'{"packs": [{"id": "example", "url": "' + EXAMPLE_URL.encode("utf-8") + b'"}]}\xff'
BAD_UTF8_BODY = b'{"id": "example", "label": "\xff\xfe"}'

TORN_JSON_INDEX = b'{"packs": ['


@pytest.fixture(autouse=True)
def _live_flags_off(monkeypatch):
    """Pin the live gates off so the seam runs under the documented
    probe conditions regardless of the ambient environment."""
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "0")
    monkeypatch.setenv("KRELLBOT_LIVE", "0")
    monkeypatch.setenv("KRELLBOT_API_LIVE", "0")


class _StubTransport:
    """In-memory transport returning pre-cooked bytes per URL.

    This is the documented stub-transport seam for `community install`:
    ``cli._UrllibGetTransport`` exists only as the default; tests inject
    their own transport, so no network is ever touched.
    """

    def __init__(self, mapping: dict[str, bytes]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        if url in self.mapping:
            return self.mapping[url]
        raise AssertionError(f"unexpected url: {url}")


def _healthy_pack_bytes() -> bytes:
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


def _community_dir(home) -> object:
    return home / "packs" / "community"


def _assert_nothing_installed(home) -> None:
    """No pack file for the requested id, and nothing at all under
    packs/community/ (the directory itself may exist, but empty)."""
    community = _community_dir(home)
    assert not (community / "example.json").exists()
    assert not community.exists() or not any(community.iterdir())


# ------------------------- refusal shape: index UTF-8 ------------------------


def test_cli_install_invalid_utf8_index_is_typed_one_liner_rc1(home, fresh_keyring, capsys):
    """An index body that is not valid UTF-8 is refused with the typed
    one-liner family the torn-JSON shape already has: exactly one stderr
    line beginning `community index is not valid UTF-8: `, rc 1, nothing
    installed, and only the index URL ever fetched.

    On base the raw UnicodeDecodeError escaped this seam as a traceback.
    """
    from krellbot import cli as kb_cli
    from krellbot import community as kb_community

    transport = _StubTransport({kb_community.INDEX_URL: BAD_UTF8_INDEX})

    rc = kb_cli._cmd_community_install("example", transport=transport)

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err
    lines = captured.err.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("community index is not valid UTF-8: ")
    assert transport.calls == [kb_community.INDEX_URL]
    _assert_nothing_installed(home)


def test_install_invalid_utf8_index_raises_typed_index_error(home):
    """The boundary fix lives in `community.install`: an undecodable
    index body raises the typed `IndexError_` (never a raw
    UnicodeDecodeError) with the family-consistent wording, chained to
    the original decode error.
    """
    from krellbot import community as kb_community

    transport = _StubTransport({kb_community.INDEX_URL: BAD_UTF8_INDEX})

    with pytest.raises(kb_community.IndexError_) as excinfo:
        kb_community.install("example", transport=transport, home=home)

    message = str(excinfo.value)
    assert message.startswith("community index is not valid UTF-8: ")
    assert excinfo.value.__cause__ is not None
    _assert_nothing_installed(home)


# ------------------------ refusal shape: pack body UTF-8 ---------------------


def test_cli_install_invalid_utf8_pack_body_is_typed_one_liner_rc1(home, fresh_keyring, capsys):
    """A pack body that is not valid UTF-8 is refused with the typed
    `InstallPayloadError` message from extensions/install.py
    `_validate_raw_json_identity` — one stderr line beginning
    `community pack body is not valid UTF-8: `, rc 1, nothing installed.

    On base the raw InstallPayloadError escaped this seam as a traceback
    because the typed class was missing from the catch set.
    """
    from krellbot import cli as kb_cli
    from krellbot import community as kb_community

    transport = _StubTransport({kb_community.INDEX_URL: INDEX_BODY, EXAMPLE_URL: BAD_UTF8_BODY})

    rc = kb_cli._cmd_community_install("example", transport=transport)

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err
    lines = captured.err.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("community pack body is not valid UTF-8: ")
    assert transport.calls == [kb_community.INDEX_URL, EXAMPLE_URL]
    _assert_nothing_installed(home)


# ------------------------------- controls ------------------------------------


def test_cli_install_torn_json_index_one_liner_unchanged(home, fresh_keyring, capsys):
    """Control: the pre-existing torn-JSON index refusal keeps its exact
    one-liner family and rc 1. This passes unchanged on base and head.
    """
    from krellbot import cli as kb_cli
    from krellbot import community as kb_community

    transport = _StubTransport({kb_community.INDEX_URL: TORN_JSON_INDEX})

    rc = kb_cli._cmd_community_install("example", transport=transport)

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err
    lines = captured.err.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("community index is not valid JSON: ")
    assert transport.calls == [kb_community.INDEX_URL]
    _assert_nothing_installed(home)


def test_cli_install_healthy_path_rc0_pack_written_verbatim(home, fresh_keyring, capsys):
    """Control: a healthy install is byte-identical — rc 0, the success
    line on stdout, nothing on stderr, and the pack file written with
    the body bytes verbatim. This passes unchanged on base and head.
    """
    from krellbot import cli as kb_cli
    from krellbot import community as kb_community

    body = _healthy_pack_bytes()
    transport = _StubTransport({kb_community.INDEX_URL: INDEX_BODY, EXAMPLE_URL: body})

    rc = kb_cli._cmd_community_install("example", transport=transport)

    assert rc == 0
    target = _community_dir(home) / "example.json"
    captured = capsys.readouterr()
    assert captured.out == f"installed example to {target}\n"
    assert captured.err == ""
    assert target.read_bytes() == body
    assert transport.calls == [kb_community.INDEX_URL, EXAMPLE_URL]
