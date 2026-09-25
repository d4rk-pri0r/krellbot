"""TLS for urllib.

python.org macOS builds point OpenSSL at a cert.pem that is not installed.
Verification stays on. This module only supplies a CA file that exists.
"""

from __future__ import annotations

import os
import ssl
from typing import Any

_CA_CANDIDATES = (
    "/private/etc/ssl/cert.pem",
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
)


def ssl_context() -> ssl.SSLContext:
    """Return a verifying context. Never disables certificate checks."""
    env_file = os.environ.get("SSL_CERT_FILE")
    if env_file and os.path.isfile(env_file):
        return ssl.create_default_context(cafile=env_file)
    default = ssl.get_default_verify_paths().openssl_cafile
    if default and os.path.isfile(default):
        return ssl.create_default_context()
    for path in _CA_CANDIDATES:
        if os.path.isfile(path):
            return ssl.create_default_context(cafile=path)
    return ssl.create_default_context()


def urlopen(req: Any, timeout: float):
    """urllib.request.urlopen with ssl_context(). Tests may still patch urlopen."""
    import urllib.request

    return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())
