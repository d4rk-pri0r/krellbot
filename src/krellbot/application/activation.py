"""NS24 — local device-token claim against the cloud worker.

The engine claims a short-lived device token from the cloud lane-c worker
``functions/api/device/token.js`` after a purchase. The wire fixture is
the closed request body both repos agree on:

    {
        "device_id": "<stable per install>",
        "session_id": "<cs_... from the cached claim>",
        "issued_at": <unix seconds>
    }

The cloud response is ``{token, expires_at}``. The engine stores the
token in the OS keychain under the service ``krellbot:device`` so it
sits next to the venue credentials but cannot collide with them. The
token bytes never appear in a URL, config file, environment variable,
or exception message.

The cached claim is the gate. Without a fresh ``claim-cache.json``
under ``<home>/catalog/`` the engine never opens a socket: a stale
cache or a missing one raises ``ClaimCacheMissing`` and the activation
flow aborts before any HTTP request. No legacy cache is migrated, and
no signed envelope is fabricated for an old status flag.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from krellbot import paths as kb_paths

# OS keychain service. Distinct from `krellbot:kraken` and
# `krellbot:coinbase` so the device token cannot collide with venue
# credentials.
_DEVICE_SERVICE = "krellbot:device"
_DEVICE_USERNAME = "token"

_DEVICE_ID_FILENAME = "device-id"
_CLAIM_CACHE_FILENAME = "claim-cache.json"
# A cached claim older than this is treated as absent so the engine
# never reaches out to claim a token the cloud has likely invalidated.
_CLAIM_CACHE_TTL_SECONDS = 24 * 3600
_DEFAULT_API_ORIGIN = "https://krellbot.dev"


class DeviceTransport(Protocol):
    """HTTP-shaped transport for the device-token endpoint."""

    def post(self, url: str, body: dict, headers: dict) -> dict: ...


class ClaimCacheMissing(Exception):
    """Raised when no fresh cached claim is on disk.

    The engine refuses to open a socket when the cached claim is absent
    or stale; this is the closed failure mode the activation flow
    surfaces to its caller.
    """


class DeviceTokenError(Exception):
    """Raised when the cloud worker refuses to issue a device token.

    The message never echoes the device token, the session id, the
    device id, or any URL parameter. Only a generic reason is exposed.
    """


@dataclass(frozen=True)
class ClaimResult:
    """Closed, secret-free outcome of a successful device-token claim."""

    device_id: str
    session_id: str
    expires_at: int
    backend: str


def device_id_path(home: Path) -> Path:
    """Return the on-disk path that holds the stable per-install device id."""
    return Path(home) / _DEVICE_ID_FILENAME


def claim_cache_path(home: Path) -> Path:
    """Return the on-disk path that holds the cached claim used by the flow."""
    return Path(home) / "catalog" / _CLAIM_CACHE_FILENAME


def read_claim_cache(home: Path) -> dict | None:
    """Return the cached claim dict (read-only), or None when absent/stale.

    The cache must carry a ``session_id`` (a ``cs_...`` Stripe identifier)
    and a fresh ``issued_at``. A stale cache is treated as absent so the
    engine does not reach out to claim a token the cloud has likely
    already invalidated. A cache whose ``session_id`` is not a string,
    does not start with ``cs_``, or whose ``issued_at`` is not an int
    is also treated as absent.
    """
    path = claim_cache_path(home)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    session_id = data.get("session_id")
    issued_at = data.get("issued_at")
    if not isinstance(session_id, str) or not session_id.startswith("cs_"):
        return None
    try:
        int_issued = int(issued_at)
    except (TypeError, ValueError):
        return None
    if int(time.time()) - int_issued > _CLAIM_CACHE_TTL_SECONDS:
        return None
    return data


def write_claim_cache(home: Path, *, session_id: str, issued_at: int) -> Path:
    """Atomically write the cached claim used by the activation flow.

    ``session_id`` must start with ``cs_``. The cache file is written
    under ``<home>/catalog/`` with the standard atomic-rename helper,
    so a crash mid-write leaves the previous cache unchanged. This is
    the only artifact the engine reads to decide whether a claim is
    pending; no other file is consulted.
    """
    if not isinstance(session_id, str) or not session_id.startswith("cs_"):
        raise ValueError("session_id must be a string starting with 'cs_'")
    if type(issued_at) is not int:
        raise TypeError("issued_at must be an int (unix seconds)")
    path = claim_cache_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    body = json.dumps(
        {"session_id": session_id, "issued_at": int(issued_at)},
        sort_keys=True,
    )
    kb_paths.atomic_write(path, body.encode("utf-8"))
    return path


def clear_claim_cache(home: Path) -> None:
    """Remove the cached claim if it exists. No-op when absent.

    A successful claim clears the cache so the next activation flow
    starts from a known-empty state. A failure leaves the cache in
    place so a retry can use the same pending claim.
    """
    path = claim_cache_path(home)
    try:
        path.unlink()
    except FileNotFoundError:
        return


def get_or_create_device_id(home: Path) -> str:
    """Return the stable per-install device id, generating it on first read.

    The id is a v4 UUID written atomically to ``<home>/device-id``. It
    survives restarts so the cloud can keep granting tokens to the same
    machine. The id is not a secret; it identifies the install, not the
    user.
    """
    import uuid as _uuid

    path = device_id_path(home)
    if path.is_file():
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            value = ""
        if value:
            return value
    new_id = str(_uuid.uuid4())
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    kb_paths.atomic_write(path, new_id.encode("utf-8"))
    return new_id


def store_device_token(token: str) -> str:
    """Persist the device token to the OS keyring.

    Returns the keyring backend name. Raises ``RuntimeError`` when the
    backend does not round-trip the stored value (the same loud-fail
    rule ``krellbot.secrets.store`` uses for venue credentials). The
    token bytes are never placed in any exception message.
    """
    if not isinstance(token, str) or not token:
        raise ValueError("device token is empty")
    import keyring as _keyring

    _keyring.set_password(_DEVICE_SERVICE, _DEVICE_USERNAME, token)
    rb = _keyring.get_password(_DEVICE_SERVICE, _DEVICE_USERNAME)
    if rb != token:
        raise RuntimeError("keyring backend did not persist device token")
    backend = _keyring.get_keyring()
    name = getattr(backend, "name", None)
    if isinstance(name, str) and name:
        return name
    return type(backend).__name__


def read_device_token() -> str | None:
    """Return the stored device token, or None when absent.

    The token is not echoed to logs or exception messages; callers
    that need it for a downstream request must keep it on the stack
    only.
    """
    import keyring as _keyring

    value = _keyring.get_password(_DEVICE_SERVICE, _DEVICE_USERNAME)
    if isinstance(value, str) and value:
        return value
    return None


def device_token_url() -> str:
    """Return the canonical cloud endpoint URL for device-token issuance.

    Reads ``KRELLBOT_API`` for the origin so a developer pointing the
    engine at a local cloud worker does not have to edit code. Any
    non-https origin falls back to the default so the engine never
    ships a token over plaintext.
    """
    raw = os.environ.get("KRELLBOT_API", _DEFAULT_API_ORIGIN).rstrip("/")
    if not raw.startswith("https://"):
        raw = _DEFAULT_API_ORIGIN
    return raw + "/api/device/token"


def build_wire_fixture(*, device_id: str, session_id: str, now: int) -> dict:
    """Build the request body the cloud worker expects.

    The wire fixture is the closed contract shared with the cloud
    lane-c worker (``functions/api/device/token.js``). Only
    ``device_id``, ``session_id``, and ``issued_at`` are sent; no token,
    no key, no URL fragment, and no catalog data leave the engine
    through this path.
    """
    if not isinstance(device_id, str) or not device_id:
        raise ValueError("device_id is required")
    if not isinstance(session_id, str) or not session_id.startswith("cs_"):
        raise ValueError("session_id must be a string starting with 'cs_'")
    if type(now) is not int:
        raise TypeError("now must be an int (unix seconds)")
    return {
        "device_id": device_id,
        "session_id": session_id,
        "issued_at": int(now),
    }


def _coerce_response(response: Any) -> tuple[str, int]:
    """Validate the cloud response shape and return (token, expires_at)."""
    if not isinstance(response, dict):
        raise DeviceTokenError("device-token endpoint returned a non-dict")
    token = response.get("token")
    expires_at = response.get("expires_at")
    if not isinstance(token, str) or not token:
        raise DeviceTokenError("device-token endpoint did not return a token")
    try:
        return token, int(expires_at)
    except (TypeError, ValueError):
        raise DeviceTokenError("device-token endpoint did not return expires_at")


class UrllibDeviceTransport:
    """POST JSON over HTTPS. Refuses non-HTTPS URLs."""

    def post(self, url: str, body: dict, headers: dict) -> dict:
        if not isinstance(url, str) or not url.startswith("https://"):
            raise DeviceTokenError("device-token endpoint is not HTTPS")
        import urllib.error
        import urllib.request

        from krellbot.tls import urlopen

        payload = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "content-type": "application/json",
                "user-agent": "krellbot/0.1",
                **{k: v for k, v in headers.items() if k.lower() != "content-type"},
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=20) as res:
                parsed = json.loads(res.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            raise DeviceTokenError("device-token endpoint unreachable") from None
        if not isinstance(parsed, dict):
            raise DeviceTokenError("device-token endpoint returned a non-dict")
        return parsed


def claim_device_token(
    home: Path,
    *,
    transport: DeviceTransport | None = None,
    url: str | None = None,
    now: int | None = None,
) -> ClaimResult:
    """Claim and persist a device token. Refuses without a fresh cached claim.

    The cached claim is the gate: without a fresh ``claim-cache.json``
    the function never opens a socket and raises ``ClaimCacheMissing``.
    With a fresh cache the function builds the wire fixture, POSTs it
    to the device-token endpoint, validates the response shape, stores
    the token in the keyring, clears the cached claim, and returns a
    closed, secret-free result. The token bytes never appear in any
    exception message or return value.
    """
    if transport is None:
        transport = UrllibDeviceTransport()
    if url is None:
        url = device_token_url()
    if now is None:
        now = int(time.time())

    cache = read_claim_cache(home)
    if cache is None:
        raise ClaimCacheMissing("no cached claim present")
    session_id = str(cache.get("session_id"))

    device_id = get_or_create_device_id(home)
    body = build_wire_fixture(device_id=device_id, session_id=session_id, now=now)
    headers = {"Content-Type": "application/json"}
    response = transport.post(url, body, headers)
    token, expires_at = _coerce_response(response)
    backend = store_device_token(token)
    clear_claim_cache(home)
    return ClaimResult(
        device_id=device_id,
        session_id=session_id,
        expires_at=expires_at,
        backend=backend,
    )


__all__ = [
    "ClaimCacheMissing",
    "ClaimResult",
    "DeviceTokenError",
    "DeviceTransport",
    "UrllibDeviceTransport",
    "build_wire_fixture",
    "claim_cache_path",
    "claim_device_token",
    "clear_claim_cache",
    "device_id_path",
    "device_token_url",
    "get_or_create_device_id",
    "read_claim_cache",
    "read_device_token",
    "store_device_token",
    "write_claim_cache",
]
