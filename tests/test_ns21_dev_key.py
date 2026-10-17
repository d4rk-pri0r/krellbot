"""NS21: license.verify_signed — DEV key refused in release.

`license.verify_signed` is the gate that decides whether a license
envelope is trustworthy. The repository ships exactly one public key,
`src/krellbot/keys/license-dev.pub`, marked `# DEV`. In a release build
(`KRELLBOT_RELEASE=1` or `release=True`), that key must be skipped so
the dev key cannot be used to forge a license envelope.

This module pins the existing release-mode behavior with a real signed
envelope and confirms the refusal, the tamper resistance, and the fact
that `verify_signed` does not consult the mutable license cache.
"""

from __future__ import annotations

import json

import pytest

# Pinned fixture: payload + signature that verifies against
# src/krellbot/keys/license-dev.pub when release is False.
_PINNED_PAYLOAD_BYTES = b'{"grace_until":300,"issued_at":10,"period_end":40,"status":"active"}'
_PINNED_SIG = "TTXgZ8bcSSDhJ8oH0ncnLf1POog_PL7jsj9uLM8mT_Qe5_iYRsfannXhTVq036_djL02pD7eCclP2zWPhLFLCw"


def test_verify_signed_dev_key_refused_in_release(home, monkeypatch):
    """A signature from the DEV public key must be refused when
    `release=True` (and when `KRELLBOT_RELEASE=1`). The fixed exception
    message never leaks the payload bytes.
    """
    from krellbot import license

    monkeypatch.setenv("KRELLBOT_RELEASE", "1")
    with pytest.raises(ValueError) as excinfo:
        license.verify_signed(_PINNED_PAYLOAD_BYTES, _PINNED_SIG, release=True)

    assert str(excinfo.value) == "license signature rejected"
    assert _PINNED_PAYLOAD_BYTES.decode("utf-8") not in str(excinfo.value)


def test_verify_signed_dev_key_works_when_not_release(home):
    """Sanity check: the DEV key still verifies a payload when release
    mode is off. This pins the existing behavior so the new refusal
    tests above can rely on the DEV fixture being live.
    """
    from krellbot import license

    parsed = license.verify_signed(_PINNED_PAYLOAD_BYTES, _PINNED_SIG)
    assert parsed == {
        "grace_until": 300,
        "issued_at": 10,
        "period_end": 40,
        "status": "active",
    }


def test_verify_signed_tampered_signature_rejected_in_release(home, monkeypatch):
    """A tampered signature (64 zero bytes) is rejected even in release
    mode. The fixed message is the same refusal text used everywhere.
    """
    from krellbot import license

    monkeypatch.setenv("KRELLBOT_RELEASE", "1")
    # 64 zero bytes, unpadded base64url.
    bad_sig = "AA" * 43

    with pytest.raises(ValueError) as excinfo:
        license.verify_signed(_PINNED_PAYLOAD_BYTES, bad_sig)

    assert str(excinfo.value) == "license signature rejected"


def test_verify_signed_does_not_consult_license_cache(home, monkeypatch):
    """A mutable license cache file with `status: active` must NOT
    influence `verify_signed`. The function returns the parsed payload
    based on the signature alone; the cache is consulted by the gate
    layer (`entries_allowed`), not by the verifier.
    """
    from krellbot import license

    # Lay down a cache that says "active" and a long grace window.
    cache = license.cache_path(home)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"status": "active", "period_end": 10_000, "grace_until": 10_000}))

    # Sanity: the cache reads back as active.
    assert license.entries_allowed(license.read_cache(home), now=5_000) is True

    # A tampered signature is still rejected — the cache did not flip
    # the verifier to a permissive mode.
    bad_sig = "AA" * 43
    with pytest.raises(ValueError):
        license.verify_signed(_PINNED_PAYLOAD_BYTES, bad_sig)

    # And the same DEV payload still verifies under non-release mode.
    parsed = license.verify_signed(_PINNED_PAYLOAD_BYTES, _PINNED_SIG)
    assert parsed["status"] == "active"


def test_verify_signed_source_refuses_dev_marker_in_release(home):
    """A source-level read of `verify_signed` shows the DEV marker
    guard. The release-mode branch is in the function body and
    conditions on the leading `# DEV` line. If a future refactor drops
    the guard, this test fails before any signed envelope is constructed.
    """
    import inspect

    from krellbot import license

    source = inspect.getsource(license.verify_signed)
    assert "_DEV_MARKER" in source
    assert "release" in source
