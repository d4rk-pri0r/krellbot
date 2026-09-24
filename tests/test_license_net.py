"""License signature verification + refresh.

The license cache is local; verification and refresh use ed25519 signatures.
There is no real network in any test — `transport` is a tiny in-memory double
that records the call and returns a pre-cooked response. The pinned dev
public key under `src/krellbot/keys/license-dev.pub` is the only key shipped
in the repo. Production keys live in non-DEV files that are not committed.
"""

from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Pinned fixture: payload + signature that must verify against
# src/krellbot/keys/license-dev.pub when release is false.
_PINNED_PAYLOAD_BYTES = b'{"grace_until":300,"issued_at":10,"period_end":40,"status":"active"}'
_PINNED_SIG = "TTXgZ8bcSSDhJ8oH0ncnLf1POog_PL7jsj9uLM8mT_Qe5_iYRsfannXhTVq036_djL02pD7eCclP2zWPhLFLCw"
_PINNED_OBJECT = {
    "grace_until": 300,
    "issued_at": 10,
    "period_end": 40,
    "status": "active",
}


class _RecordingTransport:
    """Test double for the network transport used by `refresh`.

    Records every call's URL, body, and headers. Returns the configured
    response on `post`. Tests inject one of these so no real HTTP happens.
    """

    def __init__(self, response: dict) -> None:
        self.calls: list[dict] = []
        self._response = response

    def post(self, url: str, body: dict, headers: dict) -> dict:
        self.calls.append({"url": url, "body": dict(body), "headers": dict(headers)})
        return self._response


def test_license_signature_verifies_with_pinned_pubkey(home):
    """The pinned payload/sig verifies against license-dev.pub when release is false."""
    from krellbot import license

    parsed = license.verify_signed(_PINNED_PAYLOAD_BYTES, _PINNED_SIG)
    assert parsed == _PINNED_OBJECT


def test_dev_key_refused_in_release(home, monkeypatch):
    """KRELLBOT_RELEASE=1 must refuse the DEV key and raise ValueError.

    The exception must not return the payload and must not include the
    payload bytes in its message (the fixed message applies even when
    the payload contains a key-shaped string).
    """
    from krellbot import license

    monkeypatch.setenv("KRELLBOT_RELEASE", "1")
    with pytest.raises(ValueError) as excinfo:
        license.verify_signed(_PINNED_PAYLOAD_BYTES, _PINNED_SIG)

    # Fixed message; no payload leak even when the payload contains a
    # key-shaped string (this fixture does not, but the rule is enforced
    # unconditionally by the fixed message).
    assert str(excinfo.value) == "license signature rejected"
    assert _PINNED_PAYLOAD_BYTES.decode("utf-8") not in str(excinfo.value)


def test_refresh_posts_key_in_body_not_url(home):
    """refresh POSTs the key in the JSON body, never in the URL.

    The transport records the call. The URL contains no `kb_` and no
    occurrence of the key. The body is exactly `{"key": <key>}`. The
    cache file matches the signed payload's status, period_end, and
    grace_until.
    """
    from krellbot import license

    key = "kb_" + "a" * 40
    url = "https://api.krellbot.dev/v1/activate"

    transport = _RecordingTransport({"payload": _PINNED_PAYLOAD_BYTES.decode("utf-8"), "sig": _PINNED_SIG})

    parsed = license.refresh(home, key=key, url=url, transport=transport, now=1)

    assert len(transport.calls) == 1
    call = transport.calls[0]

    # Key never appears in the URL.
    assert "kb_" not in call["url"]
    assert key not in call["url"]

    # Key is in the body, exactly once, under the `key` field.
    assert call["body"] == {"key": key}
    assert call["headers"].get("Content-Type") == "application/json"

    # Cache file was written and matches the signed payload.
    cache_path = license.cache_path(home)
    assert cache_path.exists()
    on_disk = json.loads(cache_path.read_text(encoding="utf-8"))
    assert on_disk == {
        "status": "active",
        "period_end": 40,
        "grace_until": 300,
    }

    # Returned parsed object.
    assert parsed["status"] == "active"


def test_refresh_rejects_bad_signature(home):
    """A response whose signature does not verify must NOT write the cache file."""
    from krellbot import license

    key = "kb_" + "b" * 40
    url = "https://api.krellbot.dev/v1/activate"

    # Same payload, but the signature is 64 bytes of zeros — guaranteed
    # not to match any real ed25519 public key.
    bad_sig = "AA" * 43  # unpadded base64url of 64 zero bytes

    transport = _RecordingTransport({"payload": _PINNED_PAYLOAD_BYTES.decode("utf-8"), "sig": bad_sig})

    with pytest.raises(ValueError):
        license.refresh(home, key=key, url=url, transport=transport, now=1)

    # The cache file is absent.
    assert not license.cache_path(home).exists()


def test_release_still_verifies_a_non_dev_key(home, monkeypatch, tmp_path):
    """A release build skips the DEV file and still accepts a non-DEV key."""
    from krellbot import license

    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / "license-dev.pub").write_text("# DEV\n" + "AA" * 16 + "\n", encoding="utf-8")
    (keys / "license-release.pub").write_text(
        "# RELEASE\n" + base64.b64encode(public).decode() + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(license, "_KEYS_DIR", keys)
    monkeypatch.setenv("KRELLBOT_RELEASE", "1")
    sig = private.sign(_PINNED_PAYLOAD_BYTES)
    sig_text = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    parsed = license.verify_signed(_PINNED_PAYLOAD_BYTES, sig_text, release=True)
    assert parsed["status"] == "active"
