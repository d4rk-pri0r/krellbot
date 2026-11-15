"""Security primitives for the loopback API."""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from urllib.parse import quote

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})

# Short-lived local re-pair offer for a second browser/profile. Lifetime is
# process-memory only (same as sessions); never written to disk.
RECONNECT_TOKEN_TTL_SECONDS = 300


@dataclass(frozen=True)
class ReconnectOffer:
    """One outstanding reconnect token and its absolute expiry (unix seconds)."""

    token: str
    expires_at: int


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


def generate_reconnect_token() -> str:
    """Mint a short reconnect token (URL-safe; fits a QR / paste field)."""

    return secrets.token_urlsafe(16)


def issue_reconnect_offer(*, now: int, ttl_seconds: int = RECONNECT_TOKEN_TTL_SECONDS) -> ReconnectOffer:
    """Create a new reconnect offer that expires ``ttl_seconds`` after ``now``."""

    ttl = max(1, int(ttl_seconds))
    return ReconnectOffer(token=generate_reconnect_token(), expires_at=int(now) + ttl)


def reconnect_offer_valid(offer: ReconnectOffer | None, *, submitted: str, now: int) -> bool:
    """Return True when ``submitted`` matches the outstanding unexpired offer."""

    if offer is None or not isinstance(submitted, str) or not submitted:
        return False
    if int(now) >= int(offer.expires_at):
        return False
    # Constant-time compare; lengths must match or compare_digest raises.
    if len(submitted) != len(offer.token):
        return False
    return hmac.compare_digest(submitted, offer.token)


def reconnect_redeem_path(token: str) -> str:
    """Relative shell path a second browser opens to redeem ``token``."""

    return f"/?reconnect={quote(token, safe='')}"
