"""Activation-key redeem for the dashboard wizard.

The wizard's ``POST /<token>/activate`` route calls this module. The
contract is the signed license cache the tick gate already reads, not
the legacy ``cli.check_license`` paid/grace helper:

  * ``refresh_license`` POSTs ``{"key": ...}`` to ``/api/license``. The
    key is never placed in a URL, a redirect, an HTML body, or an
    exception message.
  * A verified ``active`` or in-grace ``past_due`` payload is written to
    ``$KRELLBOT_HOME/catalog/license-cache.json`` by ``license.refresh``.
  * ``install_catalog`` then POSTs the same key to ``/api/catalog``,
    verifies the signature, and writes only the inner DSL pack objects
    under ``packs/catalog/``. It does not eval them and does not copy
    catalog performance fields onto the dashboard.
  * Exchange API keys are not involved and are not sent.

The raw activation key is not written to disk. The signed cache is the
artifact later ticks read.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from krellbot import license as kb_license
from krellbot import paths as kb_paths
from krellbot.pack import lint as pack_lint
from krellbot.tls import urlopen

SAFE_MESSAGES: frozenset[str] = frozenset(
    {
        "license verified",
        "license in grace period",
        "license not accepted",
        "license check unreachable",
    }
)

_PACK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_DEFAULT_ORIGIN = "https://krellbot.dev"


@dataclass(frozen=True)
class ActivateOutcome:
    """Closed, secret-free outcome of an activation-key POST."""

    status: str
    message: str
    catalog_downloaded: bool

    def __post_init__(self) -> None:
        if self.status not in {"paid", "grace", "dead", "unreachable"}:
            raise ValueError(f"ActivateOutcome.status must be one of paid/grace/dead/unreachable; got {self.status!r}")
        if self.message not in SAFE_MESSAGES:
            raise ValueError(f"ActivateOutcome.message must be in SAFE_MESSAGES; got {self.message!r}")


class UrllibJsonTransport:
    """POST JSON. The key must already be in the body, never in the URL."""

    def post(self, url: str, body: dict, headers: dict) -> dict:
        if not isinstance(url, str) or not url.startswith("https://"):
            raise OSError("license check unreachable")
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
        except urllib.error.HTTPError as exc:
            try:
                parsed = json.loads(exc.read().decode("utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise OSError("license check unreachable") from None
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise OSError("license check unreachable") from None
        if not isinstance(parsed, dict):
            raise OSError("license check unreachable")
        return parsed


def _origin() -> str:
    raw = os.environ.get("KRELLBOT_API", _DEFAULT_ORIGIN).rstrip("/")
    if not raw.startswith("https://"):
        return _DEFAULT_ORIGIN
    return raw


def license_url() -> str:
    return _origin() + "/api/license"


def catalog_url() -> str:
    return _origin() + "/api/catalog"


def refresh_license(
    home: Path,
    key: str,
    *,
    now: int,
    transport: Any = None,
    url: str | None = None,
) -> dict:
    """POST the key and write the signed cache. Tests inject ``transport``."""
    target = url or license_url()
    if key and key in target:
        raise ValueError("license signature rejected")
    return kb_license.refresh(
        Path(home),
        key=key,
        url=target,
        transport=transport or UrllibJsonTransport(),
        now=int(now),
    )


def install_catalog(
    home: Path,
    key: str,
    *,
    transport: Any = None,
    url: str | None = None,
) -> bool:
    """Verify the signed catalog and write runnable DSL packs only.

    Returns False when the catalog cannot be verified. Never raises the
    key. A failure here does not erase a license cache that already
    verified.
    """
    target = url or catalog_url()
    if not key or key in target:
        return False
    try:
        response = (transport or UrllibJsonTransport()).post(
            target,
            {"key": key},
            {"Content-Type": "application/json"},
        )
        payload = response.get("payload")
        sig = response.get("sig")
        if not isinstance(payload, str) or not isinstance(sig, str):
            return False
        verified = kb_license.verify_signed(payload.encode("utf-8"), sig)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(verified, dict):
        return False
    entries = verified.get("packs")
    if not isinstance(entries, list):
        return False
    root = Path(home) / "packs" / "catalog"
    root.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(root, 0o700)
    wrote = False
    for entry in entries:
        pack = entry.get("pack") if isinstance(entry, dict) else entry
        if not isinstance(pack, dict):
            continue
        if pack_lint.is_legacy(pack) or pack.get("schema_version") != 1:
            continue
        if pack_lint.check(pack):
            continue
        pack_id = str(pack.get("id", ""))
        if not _PACK_ID.fullmatch(pack_id):
            continue
        path = root / f"{pack_id}.json"
        body = json.dumps(pack, sort_keys=True, separators=(",", ":")).encode("utf-8")
        kb_paths.atomic_write(path, body)
        wrote = True
    return wrote


def _ui_status(verified: dict, *, now: int) -> str:
    status = verified.get("status")
    try:
        grace_until = int(verified.get("grace_until", 0))
    except (TypeError, ValueError):
        return "dead"
    if int(now) > grace_until:
        return "dead"
    if status == "active":
        return "paid"
    if status == "past_due":
        return "grace"
    return "dead"


def _message_for(status: str) -> str:
    if status == "paid":
        return "license verified"
    if status == "grace":
        return "license in grace period"
    if status == "dead":
        return "license not accepted"
    return "license check unreachable"


def redeem(
    activation_key: str,
    *,
    home: Path,
    now: int,
) -> ActivateOutcome:
    """Verify the key and, when it is accepted, install the signed catalog."""
    if not isinstance(activation_key, str) or not activation_key.strip():
        return ActivateOutcome("dead", "license not accepted", catalog_downloaded=False)
    key = activation_key.strip()
    try:
        verified = refresh_license(Path(home), key, now=int(now))
    except OSError:
        return ActivateOutcome("unreachable", "license check unreachable", catalog_downloaded=False)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ActivateOutcome("dead", "license not accepted", catalog_downloaded=False)
    if not isinstance(verified, dict):
        return ActivateOutcome("unreachable", "license check unreachable", catalog_downloaded=False)
    status = _ui_status(verified, now=int(now))
    catalog_downloaded = False
    if status in {"paid", "grace"}:
        catalog_downloaded = bool(install_catalog(Path(home), key))
    return ActivateOutcome(status, _message_for(status), catalog_downloaded)


__all__ = [
    "SAFE_MESSAGES",
    "ActivateOutcome",
    "UrllibJsonTransport",
    "catalog_url",
    "install_catalog",
    "license_url",
    "redeem",
    "refresh_license",
]
