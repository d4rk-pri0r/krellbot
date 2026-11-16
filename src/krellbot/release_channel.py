"""Release channel honesty for version and signing state.

Public non-prerelease (GA) releases require signed artifacts. Until the
owner configures signing secrets, cuts a signed release, and flips
``ARTIFACTS_SIGNED``, this build is an unsigned prerelease and must say
so. ``release-frozen.yml`` may produce signed macOS/Windows artifacts
when secrets are present; that alone does not flip this module.
``PAPER_ONLY_RELEASE`` is unrelated and stays owned by ``release_policy``.
"""

from __future__ import annotations

from typing import Literal

CHANNEL_PRERELEASE = "prerelease"
CHANNEL_GA = "ga"
ReleaseChannel = Literal["prerelease", "ga"]

# Owner signing (M12.1) flips these together: unsigned builds stay
# prerelease; GA is only honest when artifacts_signed is True.
ARTIFACTS_SIGNED = False
RELEASE_CHANNEL: ReleaseChannel = CHANNEL_PRERELEASE

SCHEMA_VERSION = "1"


class ReleaseChannelHonestyError(RuntimeError):
    """Channel claim does not match artifact signing state."""


def channel_matches_signing(
    *,
    channel: str,
    artifacts_signed: bool,
) -> bool:
    """Return True when the channel claim is honest for the signing state.

    Unsigned artifacts may only claim prerelease. Signed artifacts may claim
    prerelease or GA.
    """

    if channel not in (CHANNEL_PRERELEASE, CHANNEL_GA):
        return False
    if not artifacts_signed:
        return channel == CHANNEL_PRERELEASE
    return True


def ensure_channel_honesty(
    *,
    channel: str | None = None,
    artifacts_signed: bool | None = None,
) -> None:
    """Fail closed when the configured channel lies about signing."""

    resolved_channel = RELEASE_CHANNEL if channel is None else channel
    resolved_signed = ARTIFACTS_SIGNED if artifacts_signed is None else artifacts_signed
    if not channel_matches_signing(
        channel=resolved_channel,
        artifacts_signed=resolved_signed,
    ):
        raise ReleaseChannelHonestyError(
            f"release channel {resolved_channel!r} is dishonest when artifacts_signed={resolved_signed}"
        )


def version_payload() -> dict[str, object]:
    """Closed JSON body for ``GET /api/v1/version`` and UI about."""

    from krellbot import __version__

    ensure_channel_honesty()
    return {
        "schema_version": SCHEMA_VERSION,
        "version": __version__,
        "channel": RELEASE_CHANNEL,
        "artifacts_signed": ARTIFACTS_SIGNED,
    }
