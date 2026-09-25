"""krellbot.tls supplies a CA file that exists; it never disables verification."""

from __future__ import annotations

import ssl
from types import SimpleNamespace

from krellbot import tls


def _assert_verifying(ctx: ssl.SSLContext) -> None:
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_ssl_cert_file_env_is_used(tmp_path, monkeypatch):
    seen = {}
    real = ssl.create_default_context

    def spy(*a, **kw):
        seen.update(kw)
        return real()

    ca = tmp_path / "ca.pem"
    ca.write_text("x")
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    monkeypatch.setattr(tls.ssl, "create_default_context", spy)
    _assert_verifying(tls.ssl_context())
    assert seen.get("cafile") == str(ca)


def test_missing_default_cafile_falls_back_to_existing_candidate(tmp_path, monkeypatch):
    seen = {}
    real = ssl.create_default_context

    def spy(*a, **kw):
        seen.update(kw)
        return real()

    cand = tmp_path / "cert.pem"
    cand.write_text("x")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(
        tls.ssl,
        "get_default_verify_paths",
        lambda: SimpleNamespace(openssl_cafile=str(tmp_path / "missing.pem")),
    )
    monkeypatch.setattr(tls, "_CA_CANDIDATES", (str(tmp_path / "nope.pem"), str(cand)))
    monkeypatch.setattr(tls.ssl, "create_default_context", spy)
    _assert_verifying(tls.ssl_context())
    assert seen.get("cafile") == str(cand)


def test_no_ca_anywhere_still_verifies(tmp_path, monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(
        tls.ssl,
        "get_default_verify_paths",
        lambda: SimpleNamespace(openssl_cafile=str(tmp_path / "missing.pem")),
    )
    monkeypatch.setattr(tls, "_CA_CANDIDATES", (str(tmp_path / "nope.pem"),))
    _assert_verifying(tls.ssl_context())


def test_urlopen_passes_the_verifying_context(monkeypatch):
    import urllib.request

    seen = {}

    def fake(req, timeout, context):
        seen["ctx"] = context
        seen["timeout"] = timeout
        return "resp"

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert tls.urlopen("req", timeout=7) == "resp"
    assert seen["timeout"] == 7
    _assert_verifying(seen["ctx"])
