"""`krellbot keys check` reads an exchange key and verifies it is trade-only.

`cmd_keys_check` returns 0 when the venue reports trade on and withdraw off,
and 1 otherwise. stdout and stderr never contain the key or the secret.

`_probe` returns a `KeyProbeResult` (typed taxonomy) so the CLI can tell
refusal reasons apart:

    trade_only        -> canonical success (exit 0)
    withdraw_capable  -> venue confirmed withdraw rights (refusal)
    trade_off         -> missing required trade permission (refusal)
    invalid           -> key cannot be verified / permission denied (refusal)
    malformed         -> venue response shape unknown (refusal)
    unreachable       -> transport failure (refusal)

The engine never weakens `WithdrawCapableError`: each refusal subclass
remains `isinstance(WithdrawCapableError)` so existing engine `except`
blocks keep refusing refused keys.
"""

from __future__ import annotations

import sys
from typing import Any

from krellbot import secrets as kb_secrets


def cmd_keys_check(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in kb_secrets.VENUES:
        print(
            f"usage: krellbot keys check <{'|'.join(sorted(kb_secrets.VENUES))}>",
            file=sys.stderr,
        )
        return 2
    venue = argv[0]
    try:
        api_key, api_secret = kb_secrets.get(venue)
    except FileNotFoundError:
        print("no key stored", file=sys.stderr)
        return 1
    except (ValueError, PermissionError) as exc:
        print(f"could not read key: {type(exc).__name__}", file=sys.stderr)
        return 1

    result = _probe(venue, api_key, api_secret)
    if result.outcome == "trade_only":
        # The canonical public success line must not change.
        print(f"{venue}: trade on, withdraw off")
        return 0
    # All other outcomes are refusals. The reason is short, secret-free,
    # and tells the user what to do next.
    print(f"{venue}: {result.reason}", file=sys.stderr)
    return 1


def _probe(venue: str, api_key: str, api_secret: str, transport: Any = None) -> Any:
    """Run the venue key check and return a typed `KeyProbeResult`.

    A future wizard key-add must gate on `result.is_trade_only` (or
    `KeyProbeResult.is_trade_only_outcome(outcome)`) before any
    `kb_secrets.store` write; anything else is a refusal and is never
    persisted.
    """
    from krellbot.venues.base import (
        KeyMalformedError,
        KeyProbeOutcome,
        KeyTradeOffError,
        KeyUnverifiableError,
        KrakenKeyUnknownPermissionError,
        WithdrawCapableError,
    )

    if venue == "kraken":
        from krellbot.venues.kraken import HttpTransport, KrakenVenue

        try:
            venue_obj = KrakenVenue(
                api_key,
                api_secret,
                transport or HttpTransport(),
                min_interval_ms=0,
            )
        except WithdrawCapableError:
            # KrakenVenue.__init__ does not raise WithdrawCapableError
            # today, but we keep the guard so a future constructor
            # change cannot bypass the typed refusal path.
            return _result(KeyProbeOutcome.WITHDRAW_CAPABLE, "venue confirmed withdraw rights; refused")
        except (OSError, RuntimeError) as exc:
            # Constructor-time transport failure (e.g. resolv failure).
            return _result(KeyProbeOutcome.UNREACHABLE, _safe_unreachable_reason(exc))
        except (ValueError, TypeError, KeyError):
            # Bad base64 secret, missing field, or any other structural
            # input problem at constructor time is a shape refusal — not
            # a network failure.
            return _result(KeyProbeOutcome.MALFORMED, "stored secret is malformed; refused")
    elif venue == "coinbase":
        from krellbot.venues.coinbase import CoinbaseVenue
        from krellbot.venues.coinbase import HttpTransport as CoinbaseHttp

        try:
            venue_obj = CoinbaseVenue(
                api_key,
                api_secret,
                transport or CoinbaseHttp(),
            )
        except (OSError, RuntimeError) as exc:
            return _result(KeyProbeOutcome.UNREACHABLE, _safe_unreachable_reason(exc))
        except (ValueError, TypeError, KeyError):
            return _result(KeyProbeOutcome.MALFORMED, "stored secret is malformed; refused")
    else:
        return _result(KeyProbeOutcome.MALFORMED, "unsupported venue")

    try:
        perms = venue_obj.check_key()
    except (
        KeyUnverifiableError,
        KeyMalformedError,
        KeyTradeOffError,
        KrakenKeyUnknownPermissionError,
    ) as exc:
        # Distinguish reasons so the CLI can tell invalid / malformed /
        # trade-off / unknown-permission cases apart. Each subclass is
        # still a `WithdrawCapableError`, so the engine refuses all.
        # The reason text is keyed on the exception type, NOT on
        # `str(exc)`: the helper never echoes the venue's exception
        # message because that message could embed credential material
        # in a future maintainer's subclass. `sanitize.register_secret`
        # remains a last-line redaction at the print boundary.
        outcome = _outcome_for(exc)
        return _result(outcome, _reason_for(exc))
    except WithdrawCapableError as exc:
        # Bare `WithdrawCapableError` (e.g. an untyped subclass added
        # by a future venue adapter) is the contract for "venue
        # confirmed withdraw rights". `_reason_for` keys on the type
        # and returns a fixed safe string, so credential material
        # cannot leak through `str(exc)`.
        return _result(KeyProbeOutcome.WITHDRAW_CAPABLE, _reason_for(exc))
    except (OSError, RuntimeError) as exc:
        return _result(KeyProbeOutcome.UNREACHABLE, _safe_unreachable_reason(exc))
    except (ValueError, TypeError, KeyError) as exc:
        # `check_key()` raised a structural error (not network). This is
        # a malformed response, not a connectivity failure.
        return _result(KeyProbeOutcome.MALFORMED, _safe_malformed_reason(exc))
    # `check_key()` returned a `KeyPerms`. Narrow to the typed taxonomy.
    if perms.can_withdraw:
        return _result(KeyProbeOutcome.WITHDRAW_CAPABLE, "venue confirmed withdraw rights; refused")
    if not perms.can_trade:
        return _result(KeyProbeOutcome.TRADE_OFF, "no required trade permission; refused")
    return _result(KeyProbeOutcome.TRADE_ONLY, "trade on, withdraw off")


def _result(outcome: str, reason: str) -> Any:
    from krellbot.venues.base import KeyProbeResult

    return KeyProbeResult(outcome=outcome, reason=reason)


def _outcome_for(exc: BaseException) -> str:
    from krellbot.venues.base import (
        KeyMalformedError,
        KeyProbeOutcome,
        KeyTradeOffError,
        KeyUnverifiableError,
        KrakenKeyUnknownPermissionError,
    )

    if isinstance(exc, KeyUnverifiableError):
        return KeyProbeOutcome.INVALID
    if isinstance(exc, KeyMalformedError):
        return KeyProbeOutcome.MALFORMED
    if isinstance(exc, KeyTradeOffError):
        return KeyProbeOutcome.TRADE_OFF
    if isinstance(exc, KrakenKeyUnknownPermissionError):
        return KeyProbeOutcome.TRADE_OFF
    # Any other typed subclass collapses to trade_off; callers narrow via reason.
    return KeyProbeOutcome.TRADE_OFF


def _reason_for(exc: BaseException) -> str:
    """Return a short, secret-free reason for a typed probe exception.

    The reason is keyed on the exception **type**, never on `str(exc)`.
    `sanitize.register_secret` is not relied on as the catch-all because
    it cannot catch secrets that have not been registered (a future
    subclass that embeds a new credential in its message would leak
    straight through). Per-type fixed strings keep the printed reason
    short, user-actionable, and provably secret-free.

    Any unknown subclass collapses to the generic refusal reason — there
    is no informative message we can safely echo. The `KeyProbeOutcome`
    axis (`_outcome_for`) keeps the refusal taxonomy intact.
    """
    from krellbot.venues.base import (
        KeyMalformedError,
        KeyTradeOffError,
        KeyUnverifiableError,
        KrakenKeyUnknownPermissionError,
        WithdrawCapableError,
    )

    if isinstance(exc, KeyUnverifiableError):
        return "key cannot be verified (invalid or permission denied); refused"
    if isinstance(exc, KeyMalformedError):
        return "venue response shape unknown; refused"
    if isinstance(exc, KeyTradeOffError):
        return "missing required trade permission; refused"
    if isinstance(exc, KrakenKeyUnknownPermissionError):
        return "venue returned an unrecognized permission; refused"
    if isinstance(exc, WithdrawCapableError):
        # Bare `WithdrawCapableError` or unrecognised subclass. The
        # contract is "venue confirmed withdraw rights", regardless of
        # what the message happens to contain. A future maintainer
        # adding a typed subclass cannot bypass the safe-message contract
        # because the typed-subclass branches above match first.
        return "venue confirmed withdraw rights; refused"
    # Any other typed `BaseException` is refused; do not echo `str(exc)`.
    return "key refused"


def _safe_malformed_reason(exc: BaseException) -> str:
    """Build a short `malformed` reason without echoing credentials.

    `ValueError`/`TypeError`/`KeyError` instances can include credential
    material only if a venue deliberately embedded it (none of ours
    do), but we still cap the reason to the exception type so it stays
    short and secret-free. `sanitize.register_secret` further guarantees
    any incidental match is redacted at the print boundary.
    """
    return f"shape error ({type(exc).__name__}); refused"


def _safe_unreachable_reason(exc: BaseException) -> str:
    """Build an `unreachable` reason without echoing credentials.

    The legacy "network required" wording is preserved so existing scripts
    that grep for it continue to work.
    """
    return f"{type(exc).__name__}; check skipped (network required)"
