"""Release channel honesty — version string and prerelease vs signing.

Pins:

1. ``GET /api/v1/version`` surfaces the engine version and channel.
2. Unsigned builds may only claim prerelease (never GA).
3. While ``ARTIFACTS_SIGNED`` is False, ``release-frozen.yml`` still
   publishes with ``--prerelease`` (GA would be dishonest).
4. ``PAPER_ONLY_RELEASE`` is untouched by this module.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-frozen.yml"
TEST_PORT = 8080


def _default_host_header(port: int = TEST_PORT) -> list[tuple[str, str]]:
    return [("Host", f"127.0.0.1:{port}")]


def asgi_call(
    app,
    *,
    method: str,
    path: str,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, bytes]:
    import asyncio

    body = b""
    headers = list(headers or [])
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    captured: dict[str, object] = {"status": 500, "body": bytearray()}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.start":
            captured["status"] = int(message["status"])
        elif message["type"] == "http.response.body":
            captured["body"] = captured["body"] + message.get("body", b"")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("latin-1"),
        "query_string": b"",
        "root_path": "",
        "headers": [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in headers],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", TEST_PORT),
    }

    async def run() -> None:
        await app(scope, receive, send)

    asyncio.run(run())
    return int(captured["status"]), bytes(captured["body"])


def _build_app(home: Path):
    from krellbot.api.app import create_app

    return create_app(home=home, port=TEST_PORT, bootstrap_token="boot-version")


def test_version_payload_surfaces_engine_version_and_prerelease() -> None:
    from krellbot import __version__, release_channel

    payload = release_channel.version_payload()
    assert payload["schema_version"] == "1"
    assert payload["version"] == __version__
    assert payload["channel"] == "prerelease"
    assert payload["artifacts_signed"] is False


def test_unsigned_ga_claim_is_dishonest(monkeypatch: pytest.MonkeyPatch) -> None:
    from krellbot import release_channel

    monkeypatch.setattr(release_channel, "ARTIFACTS_SIGNED", False)
    monkeypatch.setattr(release_channel, "RELEASE_CHANNEL", "ga")
    with pytest.raises(release_channel.ReleaseChannelHonestyError):
        release_channel.version_payload()
    assert not release_channel.channel_matches_signing(
        channel="ga",
        artifacts_signed=False,
    )


def test_signed_ga_claim_is_honest(monkeypatch: pytest.MonkeyPatch) -> None:
    from krellbot import release_channel

    monkeypatch.setattr(release_channel, "ARTIFACTS_SIGNED", True)
    monkeypatch.setattr(release_channel, "RELEASE_CHANNEL", "ga")
    payload = release_channel.version_payload()
    assert payload["channel"] == "ga"
    assert payload["artifacts_signed"] is True


def test_api_version_endpoint_returns_closed_honesty_body(home: Path) -> None:
    from krellbot import __version__

    app = _build_app(home)
    status, body = asgi_call(
        app,
        method="GET",
        path="/api/v1/version",
        headers=_default_host_header(),
    )
    assert status == 200, body
    decoded = json.loads(body)
    assert set(decoded.keys()) == {
        "schema_version",
        "version",
        "channel",
        "artifacts_signed",
    }
    assert decoded["schema_version"] == "1"
    assert decoded["version"] == __version__
    assert decoded["channel"] == "prerelease"
    assert decoded["artifacts_signed"] is False


def test_unsigned_release_workflow_stays_prerelease() -> None:
    """While artifacts are unsigned, GitHub releases must stay prerelease."""

    from krellbot import release_channel

    assert release_channel.ARTIFACTS_SIGNED is False
    assert release_channel.RELEASE_CHANNEL == "prerelease"

    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "--prerelease" in text, "release-frozen.yml must pass --prerelease while ARTIFACTS_SIGNED is False"
    # Notes must not claim a signed / GA ship while unsigned.
    assert re.search(r"Unsigned|Not notarized|Not Authenticode", text), (
        "release notes must stay honest about unsigned artifacts"
    )
    assert "--latest" not in text


def test_release_channel_module_does_not_flip_paper_only() -> None:
    """Channel honesty must not touch the paper-only release gate."""

    from krellbot import release_policy
    from krellbot.release_channel import version_payload

    before = release_policy.PAPER_ONLY_RELEASE
    version_payload()
    assert release_policy.PAPER_ONLY_RELEASE is True
    assert release_policy.PAPER_ONLY_RELEASE is before
