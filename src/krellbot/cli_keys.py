"""`krellbot keys check` reads an exchange key and verifies it is trade-only.

`cmd_keys_check` returns 0 when the venue reports trade on and withdraw off,
and 1 otherwise. stdout and stderr never contain the key or the secret.
"""

from __future__ import annotations

import sys
from typing import Any

from krellbot import secrets as kb_secrets


def cmd_keys_check(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in kb_secrets.VENUES:
        print(f"usage: krellbot keys check <{'|'.join(sorted(kb_secrets.VENUES))}>", file=sys.stderr)
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

    perms = _probe(venue, api_key, api_secret)
    if perms is None:
        print(f"{venue}: check skipped (network required)", file=sys.stderr)
        return 1
    if perms.can_withdraw or not perms.can_trade:
        print(f"{venue}: withdraw on or trade off", file=sys.stderr)
        return 1
    print(f"{venue}: trade on, withdraw off")
    return 0


def _probe(venue: str, api_key: str, api_secret: str, transport: Any = None) -> Any:
    """Call check_key on the live transport unless a test injects one."""
    from krellbot.venues.base import WithdrawCapableError

    try:
        if venue == "kraken":
            from krellbot.venues.kraken import HttpTransport, KrakenVenue

            venue_obj = KrakenVenue(
                api_key,
                api_secret,
                transport or HttpTransport(),
                min_interval_ms=0,
            )
        elif venue == "coinbase":
            from krellbot.venues.coinbase import CoinbaseVenue
            from krellbot.venues.coinbase import HttpTransport as CoinbaseHttp

            venue_obj = CoinbaseVenue(
                api_key,
                api_secret,
                transport or CoinbaseHttp(),
            )
        else:
            return None
    except WithdrawCapableError as exc:
        print(str(exc), file=sys.stderr)
        from krellbot.venues.base import KeyPerms

        return KeyPerms(can_trade=False, can_withdraw=True)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        return None
    return venue_obj.check_key()
