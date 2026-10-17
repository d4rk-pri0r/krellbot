"""Security primitives for the loopback API."""

from __future__ import annotations

import secrets

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})


def is_loopback_host(host_header: str, *, port: int) -> bool:
    if not host_header:
        return False
    parts = host_header.rsplit(":", 1)
    if len(parts) != 2:
        return False
    host_name, host_port = parts
    return host_name in LOOPBACK_HOSTS and host_port == str(port)


def is_loopback_origin(origin_header: str, *, port: int) -> bool:
    if not origin_header:
        return False
    return origin_header in (
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
    )


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)
