"""Release-scoped trading policy.

Owner decision for v0.9.6: the release is paper-only regardless of
environment variables, stored venue keys, operator authorization files, or
live state armed before an upgrade. Live order submission is preserved in
the codebase for a future release, but this build must not let any
supported entry point (CLI arm/tick, workstation/application commands, or
the venue adapters themselves) place, cancel, or edit a real order.

The policy is deliberately temporary. Re-enabling live trading is an
owner-approved code/release change: set ``PAPER_ONLY_RELEASE`` to
``False``, update the release notes, and run the live-path suites. There is
intentionally no environment variable, config file, or UI control that can
turn live orders back on in this release.
"""

from __future__ import annotations

PAPER_ONLY_RELEASE = True
CODE_PAPER_ONLY_RELEASE = "live_disabled_paper_only_release"


class PaperOnlyReleaseError(RuntimeError):
    """A real-venue order mutation was attempted in a paper-only release."""

    code = CODE_PAPER_ONLY_RELEASE


def paper_only_release_active() -> bool:
    return PAPER_ONLY_RELEASE


def paper_only_message() -> str:
    return (
        "v0.9.6 is a paper-only release: live order send is disabled regardless of "
        "environment, stored keys, or authorization. This is temporary; an "
        "owner-approved code change can re-enable live trading."
    )


def ensure_live_orders_allowed() -> None:
    """Fail closed before any credential read or network write."""
    if PAPER_ONLY_RELEASE:
        raise PaperOnlyReleaseError(paper_only_message())
