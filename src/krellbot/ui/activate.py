"""Activation-key redeem for the dashboard wizard.

The wizard's ``POST /<token>/activate`` route calls this module. The
contract is intentionally narrow:

  * Reuse :func:`krellbot.cli.check_license` and
    :func:`krellbot.cli.download_catalog` verbatim — we do NOT shell out
    to ``krellbot setup``, do NOT invent a second license format, and do
    NOT swallow the existing ``paid`` / ``grace`` / ``dead`` shape.
  * The activation key is never echoed into HTML, the bootstrap JSON, the
    journal, any header, the redirect query string, or any exception
    message. The :class:`ActivateOutcome.message` is drawn from a closed
    :data:`SAFE_MESSAGES` set; the key is read once and dropped on the
    floor after the helpers return.
  * The caller turns the outcome into a 303 PRG to the wizard's Next
    page; the closed message travels as a ``?status=`` query value.

The brief is explicit that ``cmd_setup`` must not be invoked from the UI:
``cmd_setup`` prints human prose ("Coinbase is not ready.") on stdout,
which has no business in a loopback HTML response. This module composes
the two existing helpers without that prose path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# Closed safe-message set for the wizard's activate POST. Every message is
# short, secret-free, and matches the existing ``paid`` / ``grace`` / ``dead``
# taxonomy from ``cli.check_license``. A 303 PRG query string carries one of
# these — nothing else — so an arbitrary helper message can never reach the
# renderer.
SAFE_MESSAGES: frozenset[str] = frozenset(
    {
        "license verified",
        "license in grace period",
        "license not accepted",
        "license check unreachable",
    }
)


@dataclass(frozen=True)
class ActivateOutcome:
    """Closed, secret-free outcome of an activation-key POST.

    The key itself never appears here. The ``status`` is ``paid``,
    ``grace``, ``dead``, or ``unreachable`` — matching the existing CLI
    taxonomy so the renderer can map closed-set outcomes to closed-set
    messages without composing strings.
    """

    status: str
    message: str
    catalog_downloaded: bool

    def __post_init__(self) -> None:
        if self.status not in {"paid", "grace", "dead", "unreachable"}:
            raise ValueError(f"ActivateOutcome.status must be one of paid/grace/dead/unreachable; got {self.status!r}")
        if self.message not in SAFE_MESSAGES:
            raise ValueError(f"ActivateOutcome.message must be in SAFE_MESSAGES; got {self.message!r}")


def _map_status(result: dict[str, Any]) -> str:
    """Translate a ``check_license`` result into the closed status taxonomy.

    The engine only recognises ``paid``, ``grace``, or ``dead``. Anything
    else (network failure, server error, malformed response) collapses to
    ``unreachable`` so the UI can render an honest refusal without
    inventing fake-success copy.
    """
    status = result.get("status")
    if status == "paid":
        return "paid"
    if status == "grace":
        return "grace"
    if status == "dead":
        return "dead"
    return "unreachable"


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
    home: Any,
    check_license: Any,
    download_catalog: Any,
) -> ActivateOutcome:
    """Verify the key against the existing license endpoint and download
    the catalog when the license is good.

    ``check_license`` and ``download_catalog`` are injected so tests can
    pin the contract without opening a socket. Production wires the real
    functions from :mod:`krellbot.cli`.

    ``home`` is :func:`krellbot.paths.home` (or any callable returning the
    home Path). The key is dropped from the local frame as soon as the
    helpers return; nothing in this function captures it beyond the two
    helper calls.

    The function returns an :class:`ActivateOutcome` whose ``message`` is
    always a member of :data:`SAFE_MESSAGES`. The outcome never echoes
    the key. The caller turns the outcome into a 303 PRG.
    """
    if not isinstance(activation_key, str) or not activation_key:
        return ActivateOutcome("dead", "license not accepted", catalog_downloaded=False)

    try:
        result = check_license(activation_key)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        # The brief: the key is never echoed, not even in the failure path.
        # A network or parse failure collapses to ``unreachable`` so the
        # UI can render the closed refusal message. Anything outside the
        # narrow set of exceptions here is a programming error and
        # deliberately propagates — we never silently swallow a
        # ``BaseException`` (KeyboardInterrupt, SystemExit, etc.).
        return ActivateOutcome("unreachable", "license check unreachable", catalog_downloaded=False)

    if not isinstance(result, dict):
        return ActivateOutcome("unreachable", "license check unreachable", catalog_downloaded=False)

    status = _map_status(result)
    catalog_downloaded = False
    if status in {"paid", "grace"}:
        # Only attempt the catalog download when the license is accepted.
        # The CLI's download helper writes to ``<home>/catalog.json``;
        # we deliberately do NOT print the "Coinbase is not ready." prose
        # that ``cmd_setup`` emits on stdout.
        try:
            catalog_downloaded = bool(download_catalog(activation_key))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            catalog_downloaded = False

    return ActivateOutcome(status, _message_for(status), catalog_downloaded)


__all__ = ["SAFE_MESSAGES", "ActivateOutcome", "redeem"]
