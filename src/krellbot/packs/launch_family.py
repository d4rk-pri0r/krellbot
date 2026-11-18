"""One launch pack family — honesty contract (M21.2).

Paid 1.0 ships a **single** launch pack family. The default family is the
DCA mode pack family (SKU ``paid-launch-dca``), built from the same
long-only DCA mode shape as ``mode-dca``. This module documents and
enforces honesty copy:

  * no returns promises
  * fixture / backtest labeled (never live market performance)
  * packs are tools — not personalized advice
  * signed catalogue entry ``pack_sha256`` matches installed bytes

Package data lives under ``krellbot.packs.launch``. The module never
opens a socket, never touches exchange credentials, and never flips
``PAPER_ONLY_RELEASE``. Catalogue metadata validation here is additive
to ``krellbot.license`` (which stays untouched — risk path).
"""

from __future__ import annotations

import hashlib
import json
import re
from importlib import resources
from pathlib import Path
from typing import Any

from krellbot import paths as kb_paths
from krellbot.pack import lint as pack_lint

FAMILY_ID = "dca"
FAMILY_LABEL = "DCA mode pack family"
SKU_ID = "paid-launch-dca"
PACK_FILENAME = "paid-launch-dca.json"
_LAUNCH_PACKAGE = "krellbot.packs.launch"

NOT_PERSONALIZED_ADVICE = "not personalized advice"
FIXTURE_BACKTEST_LABEL = "backtest or pinned fixture — not live market performance"
NO_RETURNS_PROMISES = "No returns promises."

CATALOGUE_DESCRIPTION = (
    "Launch DCA pack family. Tools only — not personalized advice. "
    "Research/fixture results are backtest or pinned fixture — not live "
    "market performance. No returns promises."
)

UI_HONESTY = (
    "Launch pack family (DCA): tools only — not personalized advice. "
    "Fixture and backtest results stay labeled; no returns promises. "
    "Installed bytes must match the signed catalogue pack_sha256."
)

# Case-insensitive substrings that must never appear in launch-family copy.
_RETURNS_PROMISE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"guaranteed\s+returns?",
        r"guaranteed\s+profit",
        r"profit\s+guaranteed",
        r"will\s+profit",
        r"promised?\s+returns?",
        r"risk[- ]free\s+returns?",
        r"\bdouble\s+your\s+money\b",
        r"\bget\s+rich\b",
    )
)

_REQUIRED_PHRASES: tuple[str, ...] = (
    NOT_PERSONALIZED_ADVICE,
    "fixture",
    "backtest",
)


class LaunchFamilyHonestyError(ValueError):
    """Launch pack family honesty contract refused."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _read_pack_resource() -> str:
    path = resources.files(_LAUNCH_PACKAGE).joinpath(PACK_FILENAME)
    if not path.is_file():
        raise LaunchFamilyHonestyError("pack_missing", f"launch pack {PACK_FILENAME!r} is not shipped")
    return path.read_text(encoding="utf-8")


def load_pack() -> dict[str, Any]:
    """Load the shipped launch DCA pack as a fresh dict."""
    pack = json.loads(_read_pack_resource())
    if not isinstance(pack, dict):
        raise LaunchFamilyHonestyError("pack_invalid", "launch pack must be a JSON object")
    if pack.get("id") != SKU_ID:
        raise LaunchFamilyHonestyError("pack_invalid", f"launch pack id must be {SKU_ID!r}")
    # Launch SKU is not the reserved built-in id ``mode-dca``; it ships the
    # same DCA teaching shape without claiming the reserved mode id.
    if pack.get("mode") is not None:
        raise LaunchFamilyHonestyError(
            "pack_invalid",
            "launch pack must not claim reserved mode metadata; use DCA content shape only",
        )
    errors = pack_lint.check(pack)
    if errors:
        raise LaunchFamilyHonestyError("pack_invalid", f"launch pack failed lint: {errors}")
    origin = str(pack.get("origin") or "")
    if "dca" not in origin.lower():
        raise LaunchFamilyHonestyError("pack_invalid", "launch pack origin must identify the DCA family")
    return json.loads(json.dumps(pack, sort_keys=True, separators=(",", ":")))


def canonical_pack_bytes(pack: dict[str, Any] | None = None) -> bytes:
    """Return canonical UTF-8 JSON bytes for the launch pack."""
    body = pack if pack is not None else load_pack()
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def pack_sha256(pack: dict[str, Any] | None = None) -> str:
    """Hex sha256 of the canonical launch-pack bytes."""
    return hashlib.sha256(canonical_pack_bytes(pack)).hexdigest()


def assert_no_returns_promises(text: str) -> None:
    """Refuse copy that promises returns or guaranteed profit."""
    if not isinstance(text, str) or not text.strip():
        raise LaunchFamilyHonestyError("honesty_copy", "honesty copy must be a non-empty string")
    for pattern in _RETURNS_PROMISE_PATTERNS:
        if pattern.search(text):
            raise LaunchFamilyHonestyError(
                "returns_promise",
                "launch pack family copy must not promise returns or guaranteed profit",
            )


def assert_required_honesty_phrases(text: str) -> None:
    """Require not-advice + fixture/backtest labeling phrases."""
    if not isinstance(text, str) or not text.strip():
        raise LaunchFamilyHonestyError("honesty_copy", "honesty copy must be a non-empty string")
    lowered = text.lower()
    for phrase in _REQUIRED_PHRASES:
        if phrase.lower() not in lowered:
            raise LaunchFamilyHonestyError(
                "honesty_copy",
                f"launch pack family copy must include {phrase!r}",
            )
    assert_no_returns_promises(text)


def catalogue_entry() -> dict[str, Any]:
    """Closed catalogue metadata for the launch pack family SKU.

    Includes ``pack_sha256`` so a signed catalogue entry can be checked
    against installed bytes. ``krellbot.license._normalize_catalogue``
    may drop unknown fields on the wire cache; honesty tests use this
    closed entry (and the shipped fixture) directly.
    """
    pack = load_pack()
    description = CATALOGUE_DESCRIPTION
    assert_required_honesty_phrases(description)
    assert_required_honesty_phrases(str(pack.get("origin") or ""))
    return {
        "id": SKU_ID,
        "label": str(pack.get("label") or "Launch DCA"),
        "version": str(pack.get("version") or "1.0.0"),
        "tier": "paid",
        "permissions": ["catalog"],
        "description": description,
        "family_id": FAMILY_ID,
        "family_label": FAMILY_LABEL,
        "pack_sha256": pack_sha256(pack),
        "disclosures": {
            "not_personalized_advice": True,
            "no_returns_promises": True,
            "fixture_backtest_labeled": True,
        },
    }


def validate_catalogue_entry(entry: dict[str, Any], *, installed_bytes: bytes | None = None) -> dict[str, Any]:
    """Validate a catalogue entry for the launch family honesty contract.

    When ``installed_bytes`` is provided, they must match ``pack_sha256``.
    When omitted, ``pack_sha256`` must still match the shipped package
    pack bytes.
    """
    if not isinstance(entry, dict):
        raise LaunchFamilyHonestyError("catalogue_invalid", "catalogue entry must be an object")
    if entry.get("id") != SKU_ID:
        raise LaunchFamilyHonestyError("catalogue_invalid", f"launch family SKU must be {SKU_ID!r}")
    if entry.get("tier") != "paid":
        raise LaunchFamilyHonestyError("catalogue_invalid", "launch family SKU must be tier paid")
    description = entry.get("description")
    if not isinstance(description, str):
        raise LaunchFamilyHonestyError("honesty_copy", "catalogue description required")
    assert_required_honesty_phrases(description)

    expected = pack_sha256()
    declared = entry.get("pack_sha256")
    if not isinstance(declared, str) or not declared:
        raise LaunchFamilyHonestyError("bytes_mismatch", "catalogue entry must declare pack_sha256")
    if declared != expected:
        raise LaunchFamilyHonestyError(
            "bytes_mismatch",
            "signed catalogue pack_sha256 does not match shipped launch pack bytes",
        )
    if installed_bytes is not None:
        actual = hashlib.sha256(installed_bytes).hexdigest()
        if actual != declared:
            raise LaunchFamilyHonestyError(
                "bytes_mismatch",
                "installed pack bytes do not match signed catalogue pack_sha256",
            )
    disclosures = entry.get("disclosures")
    if isinstance(disclosures, dict):
        if disclosures.get("not_personalized_advice") is not True:
            raise LaunchFamilyHonestyError("honesty_copy", "disclosures.not_personalized_advice must be true")
        if disclosures.get("no_returns_promises") is not True:
            raise LaunchFamilyHonestyError("honesty_copy", "disclosures.no_returns_promises must be true")
        if disclosures.get("fixture_backtest_labeled") is not True:
            raise LaunchFamilyHonestyError("honesty_copy", "disclosures.fixture_backtest_labeled must be true")
    return {
        "id": SKU_ID,
        "tier": "paid",
        "pack_sha256": declared,
        "family_id": FAMILY_ID,
        "ok": True,
    }


def install_pack_bytes(home: Path) -> dict[str, Any]:
    """Write the launch pack under ``<home>/packs/<sku>.json`` and verify hash.

    Does not grant entitlements and does not call the network. Callers
    that gate on paid access should check checkout entitlements first.
    Returns closed metadata including the verified ``pack_sha256``.
    """
    home = Path(home)
    pack = load_pack()
    body = canonical_pack_bytes(pack)
    digest = hashlib.sha256(body).hexdigest()
    entry = catalogue_entry()
    validate_catalogue_entry(entry, installed_bytes=body)

    packs_dir = home / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    target = packs_dir / f"{SKU_ID}.json"
    kb_paths.atomic_write(target, body)
    installed = target.read_bytes()
    if hashlib.sha256(installed).hexdigest() != digest:
        raise LaunchFamilyHonestyError(
            "bytes_mismatch",
            "installed pack bytes do not match signed catalogue pack_sha256",
        )
    return {
        "pack_id": SKU_ID,
        "path": str(target),
        "pack_sha256": digest,
        "family_id": FAMILY_ID,
        "version": str(pack.get("version") or "1.0.0"),
    }


def honesty_document() -> dict[str, Any]:
    """Closed honesty document for docs / UI / tests."""
    entry = catalogue_entry()
    return {
        "schema_version": "1",
        "family_id": FAMILY_ID,
        "family_label": FAMILY_LABEL,
        "sku": SKU_ID,
        "ui_honesty": UI_HONESTY,
        "catalogue_description": CATALOGUE_DESCRIPTION,
        "fixture_backtest_label": FIXTURE_BACKTEST_LABEL,
        "not_personalized_advice": NOT_PERSONALIZED_ADVICE,
        "no_returns_promises": NO_RETURNS_PROMISES,
        "pack_sha256": entry["pack_sha256"],
        "catalogue_entry": entry,
    }


__all__ = [
    "CATALOGUE_DESCRIPTION",
    "FAMILY_ID",
    "FAMILY_LABEL",
    "FIXTURE_BACKTEST_LABEL",
    "NOT_PERSONALIZED_ADVICE",
    "NO_RETURNS_PROMISES",
    "SKU_ID",
    "UI_HONESTY",
    "LaunchFamilyHonestyError",
    "assert_no_returns_promises",
    "assert_required_honesty_phrases",
    "canonical_pack_bytes",
    "catalogue_entry",
    "honesty_document",
    "install_pack_bytes",
    "load_pack",
    "pack_sha256",
    "validate_catalogue_entry",
]
