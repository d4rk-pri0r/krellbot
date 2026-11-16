"""Offline license cache + entries-allowed gate.

The cache file lives at `$KRELLBOT_HOME/catalog/license-cache.json`. The
shape is `{status, period_end, grace_until}`. Status is one of `active`,
`past_due`, `lapsed`, `dead`. `refresh` verifies a signed payload and writes
that cache. It does not open a socket; the caller injects the transport.
`tick` only reads the cache. The gate is fail-closed:
a missing cache refuses entries. Exits are not gated.

The gate applies ONLY to packs whose armed record says `requires_license:
true`. Fixture and community packs do not require a license.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_CACHE_FILENAME = "license-cache.json"
_CATALOGUE_CACHE_FILENAME = "catalogue.json"
_KEYS_DIR = Path(__file__).resolve().parent / "keys"
_REJECT_MSG = "license signature rejected"
_DEV_MARKER = "# DEV"
_VALID_CATALOGUE_TIERS = frozenset({"free", "paid"})


def cache_path(home: Path) -> Path:
    """Return the path to the license-cache.json file under <home>/catalog."""
    return Path(home) / "catalog" / _CACHE_FILENAME


def catalogue_cache_path(home: Path) -> Path:
    """Return the path to the verified catalogue cache under <home>/catalog."""
    return Path(home) / "catalog" / _CATALOGUE_CACHE_FILENAME


def read_cache(home: Path) -> dict | None:
    """Return the parsed cache, or None if the file does not exist."""
    path = cache_path(home)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def write_cache(home: Path, *, status: str, period_end: int, grace_until: int) -> Path:
    """Write the license cache atomically. Returns the file path."""
    from krellbot import paths

    path = cache_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        {"status": status, "period_end": period_end, "grace_until": grace_until},
        sort_keys=True,
    )
    paths.atomic_write(path, body.encode("utf-8"))
    return path


def entries_allowed(cache: dict | None, *, now: int) -> bool:
    """True iff entries are allowed right now.

    Rule:
      * `cache is None` => False (fail-closed).
      * `status not in {"active", "past_due"}` => False.
      * `now > grace_until` => False.
      * else True.

    Exits are always allowed; this gate is entries only.
    """
    if not isinstance(cache, dict):
        return False
    status = cache.get("status")
    if status not in {"active", "past_due"}:
        return False
    try:
        grace_until = int(cache.get("grace_until", 0))
    except (TypeError, ValueError):
        return False
    return int(now) <= grace_until


def load(home: Path) -> dict | None:
    """Alias for `read_cache`. Kept for the module's public surface."""
    return read_cache(home)


def _b64url_decode(data: str) -> bytes:
    """Decode unpadded base64url. Raises ValueError on malformed input."""
    pad = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + pad)
    except (binascii.Error, ValueError, TypeError):
        raise ValueError(_REJECT_MSG) from None


def verify_signed(payload: bytes, sig: str, *, release: bool = False) -> dict:
    """Verify an ed25519 signature over canonical JSON; return the parsed object.

    `payload` is canonical JSON (sorted keys, no spaces). `sig` is unpadded
    base64url of a 64-byte ed25519 signature. Every `*.pub` under
    `src/krellbot/keys/` is tried in sorted order. A file whose first line
    is `# DEV` is refused when `release` is true or `KRELLBOT_RELEASE=1`.

    Raises `ValueError("license signature rejected")` on a bad signature,
    a malformed key file, a DEV key encountered in release, a malformed
    signature string, or a non-dict payload. The fixed message never
    includes the payload bytes, so a payload that contains a key-shaped
    string never leaks through the exception text.
    """
    release = release or os.environ.get("KRELLBOT_RELEASE") == "1"

    sig_bytes = _b64url_decode(sig)
    if len(sig_bytes) != 64:
        raise ValueError(_REJECT_MSG)

    try:
        payload_text = payload.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        raise ValueError(_REJECT_MSG) from None
    try:
        parsed = json.loads(payload_text)
    except json.JSONDecodeError:
        raise ValueError(_REJECT_MSG) from None
    if not isinstance(parsed, dict):
        raise TypeError(_REJECT_MSG)

    if not _KEYS_DIR.is_dir():
        raise ValueError(_REJECT_MSG)
    pub_files = sorted(p for p in _KEYS_DIR.glob("*.pub") if p.is_file())
    if not pub_files:
        raise ValueError(_REJECT_MSG)

    for pub_path in pub_files:
        try:
            raw = pub_path.read_text(encoding="utf-8")
        except OSError:
            raise ValueError(_REJECT_MSG) from None
        lines = raw.splitlines()
        if lines and lines[0].strip() == _DEV_MARKER and release:
            continue
        if len(lines) < 2:
            raise ValueError(_REJECT_MSG)
        pub_bytes = _b64url_decode(lines[1].strip())
        if len(pub_bytes) != 32:
            raise ValueError(_REJECT_MSG)
        try:
            key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        except ValueError:
            raise ValueError(_REJECT_MSG) from None
        try:
            key.verify(sig_bytes, payload)
            return parsed
        except InvalidSignature:
            continue

    raise ValueError(_REJECT_MSG)


def refresh(
    home: Path,
    *,
    key: str,
    url: str,
    transport,
    now: int,
) -> dict:
    """POST `key` to `url`, verify the response, write the cache.

    The key goes in the JSON body; the URL must not already contain the
    key (we refuse before calling `transport`). `transport.post` is the
    injected network call — this module never opens a socket itself.

    Response shape: `{"payload": "<canonical json string>", "sig": "<base64url>"}`.
    The payload is verified with `verify_signed`. The verified object's
    `status`, `period_end`, and `grace_until` are written to the cache via
    `write_cache` regardless of `status` — `entries_allowed` is the gate
    that decides what `status` means. `revoked` is never remapped.

    The key never appears in any exception message or journal line we emit.
    """
    if not isinstance(key, str) or not key:
        raise ValueError(_REJECT_MSG)
    if not isinstance(url, str) or not url:
        raise ValueError(_REJECT_MSG)
    if key in url:
        raise ValueError(_REJECT_MSG)

    body = {"key": key}
    headers = {"Content-Type": "application/json"}

    response = transport.post(url, body, headers)
    if not isinstance(response, dict):
        raise TypeError(_REJECT_MSG)
    payload_str = response.get("payload")
    sig = response.get("sig")
    if not isinstance(payload_str, str) or not isinstance(sig, str):
        raise TypeError(_REJECT_MSG)

    payload_bytes = payload_str.encode("utf-8")
    verified = verify_signed(payload_bytes, sig)

    try:
        status = verified["status"]
        period_end = int(verified["period_end"])
        grace_until = int(verified["grace_until"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(_REJECT_MSG) from None

    write_cache(home, status=status, period_end=period_end, grace_until=grace_until)
    return verified


def _normalize_catalogue(verified: dict) -> dict:
    """Return the closed catalogue metadata document, or raise ValueError.

    Required shape after signature verification:

      * ``catalogue_version`` — non-empty string
      * ``packs`` — list of objects, each with non-empty ``id`` and
        ``tier`` in ``{"free", "paid"}``

    Optional per-entry fields kept when present and well-typed:
    ``label``, ``description``, ``version``, ``permissions`` (list of
    strings). Optional top-level ``updated`` (string). Unknown fields
    are dropped so a verified but hostile payload cannot widen the
    wire contract. The reject message never includes payload bytes.
    """
    if not isinstance(verified, dict):
        raise TypeError(_REJECT_MSG)
    catalogue_version = verified.get("catalogue_version")
    if not isinstance(catalogue_version, str) or not catalogue_version:
        raise ValueError(_REJECT_MSG)
    packs_raw = verified.get("packs")
    if not isinstance(packs_raw, list):
        raise TypeError(_REJECT_MSG)

    packs: list[dict] = []
    for entry in packs_raw:
        if not isinstance(entry, dict):
            raise TypeError(_REJECT_MSG)
        pack_id = entry.get("id")
        tier = entry.get("tier")
        if not isinstance(pack_id, str) or not pack_id:
            raise ValueError(_REJECT_MSG)
        if tier not in _VALID_CATALOGUE_TIERS:
            raise ValueError(_REJECT_MSG)
        row: dict = {"id": pack_id, "tier": tier}
        label = entry.get("label")
        if isinstance(label, str):
            row["label"] = label
        description = entry.get("description")
        if isinstance(description, str):
            row["description"] = description
        version = entry.get("version")
        if isinstance(version, str):
            row["version"] = version
        permissions = entry.get("permissions")
        if isinstance(permissions, list) and all(isinstance(p, str) for p in permissions):
            row["permissions"] = list(permissions)
        else:
            row["permissions"] = []
        packs.append(row)

    out: dict = {
        "catalogue_version": catalogue_version,
        "packs": packs,
    }
    updated = verified.get("updated")
    if isinstance(updated, str):
        out["updated"] = updated
    return out


def verify_catalogue(payload: bytes, sig: str, *, release: bool = False) -> dict:
    """Verify an ed25519-signed catalogue and return closed metadata.

    ``payload`` is canonical JSON; ``sig`` is unpadded base64url of the
    64-byte signature. Verification reuses :func:`verify_signed`, then
    the payload is normalized to free+paid catalogue metadata. Raises
    ``ValueError("license signature rejected")`` on a bad signature or
    a payload that is not a free+paid catalogue document.
    """
    verified = verify_signed(payload, sig, release=release)
    return _normalize_catalogue(verified)


def read_catalogue_cache(home: Path) -> dict | None:
    """Return the cached verified catalogue, or None if absent/unreadable."""
    path = catalogue_cache_path(home)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return _normalize_catalogue(data)
    except ValueError:
        return None


def write_catalogue_cache(home: Path, document: dict) -> Path:
    """Write a verified catalogue document atomically. Returns the path."""
    from krellbot import paths

    normalized = _normalize_catalogue(document)
    path = catalogue_cache_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    paths.atomic_write(path, body.encode("utf-8"))
    return path
