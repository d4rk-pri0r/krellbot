"""Second venue product path for the distribution gate (M23.4).

Pins Coinbase as the second qualified live venue beyond Kraken:

* Registry claims exactly ``{kraken, coinbase}``; ``binance``, ``gate``, and ``okx`` stay paper-only.
* Preflight factory already admits coinbase (aligned with the registry).
* Paper-only release still refuses Coinbase live send before grant I/O.
* Under the test-only live-capable fence, a Coinbase grant authorizes send.
* ``live.preflight`` with FakeCoinbaseTransport never posts orders.

CI uses fakes only. Does not flip ``PAPER_ONLY_RELEASE``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fakes.fake_coinbase import FakeCoinbaseTransport
from fakes.live_grant import write_grant

from krellbot import release_policy
from krellbot.application import live_gate
from krellbot.application.distribution_venues import (
    PAPER_ONLY_VENUES,
    QUALIFIED_LIVE_VENUES,
    SECOND_DISTRIBUTION_VENUE,
    SECOND_DISTRIBUTION_WAVE_PAIR,
    is_paper_only_venue,
    is_qualified_live_venue,
)
from krellbot.application.live_preflight import (
    CODE_OK,
    CODE_PREFLIGHT_BLOCKED,
    SUPPORTED_PREFLIGHT_VENUES,
    SandboxTransport,
    VenueBackedPreflightTransport,
    build_venue_preflight_transport,
    evaluate,
)
from krellbot.data.instruments import PAPER_WAVE_COINBASE_BTC_USD

VENUE = SECOND_DISTRIBUTION_VENUE
PAIR = SECOND_DISTRIBUTION_WAVE_PAIR
TEST_PORT = 8080
COINBASE_TEST_KEY = "organizations/fake-org/apiKeys/fake-coinbase-key-001"
COINBASE_TEST_SECRET = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQGKiOPddAnxlf1S2y08ul1yymcJvx2UEhvzdIgBtA9vXA=="

TRADE_ONLY_PERMS = [
    {"scope": "view", "can_view": True, "can_transfer": False},
    {"scope": "trade", "can_trade": True, "can_transfer": False},
    {"scope": "transfer", "can_transfer": False},
]


def _accounts(*, usd: str = "1000", btc: str = "0") -> dict:
    accounts = [
        {
            "uuid": "usd-acct",
            "currency": "USD",
            "available_balance": {"value": usd, "currency": "USD"},
        }
    ]
    if btc != "0":
        accounts.append(
            {
                "uuid": "btc-acct",
                "currency": "BTC",
                "available_balance": {"value": btc, "currency": "BTC"},
            }
        )
    return {"accounts": accounts}


class _LiveCoinbaseTransport(FakeCoinbaseTransport):
    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("key_permissions", list(TRADE_ONLY_PERMS))
        kwargs.setdefault("accounts", _accounts())
        super().__init__(**kwargs)


def _store_coinbase_key(fresh_keyring) -> None:
    fresh_keyring.set_password("krellbot:coinbase", "key", COINBASE_TEST_KEY)
    fresh_keyring.set_password("krellbot:coinbase", "secret", COINBASE_TEST_SECRET)


def _ascii_headers(headers: list[tuple[str, str]]) -> list[tuple[bytes, bytes]]:
    return [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in headers]


def asgi_call(
    app,
    *,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes, list[str]]:
    body = body if body is not None else b""
    headers = list(headers or [])
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    captured: dict[str, object] = {"status": 500, "headers": [], "body": bytearray()}

    async def send(message: dict[str, object]) -> None:
        mtype = message["type"]
        if mtype == "http.response.start":
            captured["status"] = int(message["status"])
            captured["headers"] = list(message.get("headers", []))
        elif mtype == "http.response.body":
            captured["body"] = captured["body"] + message.get("body", b"")

    raw_path = path.encode("latin-1")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": raw_path,
        "query_string": b"",
        "server": ("127.0.0.1", 0),
        "client": ("127.0.0.1", 12345),
        "headers": _ascii_headers(headers),
        "root_path": "",
    }

    asyncio.run(app(scope, receive, send))

    flat: list[tuple[str, str]] = []
    set_cookies: list[str] = []
    for name_b, value_b in captured["headers"]:
        name = name_b.decode("latin-1")
        value = value_b.decode("latin-1")
        if name.lower() == "set-cookie":
            set_cookies.append(value)
        else:
            flat.append((name, value))
    return int(captured["status"]), flat, bytes(captured["body"]), set_cookies


def _build_app(home: Path, *, bootstrap_token: str = "boot-second-venue"):
    from krellbot.api.app import create_app

    return create_app(home=home, port=TEST_PORT, bootstrap_token=bootstrap_token)


def _post_json(app, path: str, payload: dict, headers: list[tuple[str, str]] | None = None):
    body = json.dumps(payload).encode("utf-8")
    base = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="POST", path=path, body=body, headers=base)


def _bootstrap(app, token: str = "boot-second-venue") -> list[tuple[str, str]]:
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 200, body
    decoded = json.loads(body)
    csrf = decoded["csrf_token"]
    cookie = next(c for c in cookies if c.startswith("krellbot_session="))
    session_value = cookie.split(";", 1)[0].split("=", 1)[1]
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session_value}"),
    ]


def _order_posts(transport: FakeCoinbaseTransport) -> list:
    return [c for c in transport.calls if c.method == "POST" and c.url.rstrip("/").endswith("/orders")]


# ---------------------------------------------------------------------------
# Registry / product claim
# ---------------------------------------------------------------------------


def test_distribution_qualified_live_venues_are_kraken_and_coinbase():
    assert QUALIFIED_LIVE_VENUES == frozenset({"kraken", "coinbase"})
    assert SECOND_DISTRIBUTION_VENUE == "coinbase"
    assert SECOND_DISTRIBUTION_WAVE_PAIR == "BTC-USD"
    assert SECOND_DISTRIBUTION_WAVE_PAIR == PAPER_WAVE_COINBASE_BTC_USD
    assert is_qualified_live_venue("kraken")
    assert is_qualified_live_venue("coinbase")
    assert not is_qualified_live_venue("binance")
    assert PAPER_ONLY_VENUES == frozenset({"binance", "gate", "pionex", "okx"})
    assert is_paper_only_venue("binance")
    assert is_paper_only_venue("gate")
    assert is_paper_only_venue("pionex")
    assert is_paper_only_venue("okx")
    assert not is_qualified_live_venue("gate")
    assert not is_qualified_live_venue("pionex")
    assert not is_qualified_live_venue("okx")
    assert not is_paper_only_venue("coinbase")


def test_preflight_supported_venues_match_distribution_registry():
    assert SUPPORTED_PREFLIGHT_VENUES == QUALIFIED_LIVE_VENUES
    assert "binance" not in SUPPORTED_PREFLIGHT_VENUES
    assert "pionex" not in SUPPORTED_PREFLIGHT_VENUES
    assert "okx" not in SUPPORTED_PREFLIGHT_VENUES


# ---------------------------------------------------------------------------
# Live gate honesty (paper-only + live-capable fence)
# ---------------------------------------------------------------------------


def test_coinbase_paper_only_release_refuses_live_send(home, monkeypatch):
    assert release_policy.PAPER_ONLY_RELEASE is True
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    result = live_gate.check_live_send(home, venue=VENUE, pair=PAIR)
    assert result.ok is False
    assert result.code == live_gate.CODE_PAPER_ONLY_RELEASE


@pytest.mark.usefixtures("live_capable_release")
def test_coinbase_grant_authorizes_send_under_live_capable_fence(home, monkeypatch):
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    result = live_gate.check_live_send(home, venue=VENUE, pair=PAIR)
    assert result.ok is True, result


@pytest.mark.usefixtures("live_capable_release")
def test_coinbase_wrong_pair_grant_refuses_send(home, monkeypatch):
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    result = live_gate.check_live_send(home, venue=VENUE, pair="ETH-USD")
    assert result.ok is False
    assert result.code == live_gate.CODE_LIVE_NOT_AUTHORIZED


# ---------------------------------------------------------------------------
# Preflight with FakeCoinbaseTransport
# ---------------------------------------------------------------------------


def test_build_venue_preflight_transport_admits_coinbase(fresh_keyring) -> None:
    _store_coinbase_key(fresh_keyring)
    http = _LiveCoinbaseTransport()
    transport = build_venue_preflight_transport(venue=VENUE, http_transport=http)
    assert not isinstance(transport, SandboxTransport)
    assert isinstance(transport, VenueBackedPreflightTransport)
    assert transport.account == VENUE


def test_coinbase_preflight_evaluate_never_posts_orders(fresh_keyring) -> None:
    _store_coinbase_key(fresh_keyring)
    http = _LiveCoinbaseTransport(accounts=_accounts(usd="250.00", btc="0.01"))
    transport = build_venue_preflight_transport(venue=VENUE, http_transport=http)
    result = evaluate(
        account_id=VENUE,
        revision_id="rev-second-venue",
        mode="sandbox",
        transport=transport,
    )
    assert result.ok is True, result
    assert result.code == CODE_OK
    assert result.permissions == {"can_trade": True, "can_withdraw": False}
    assert result.balances is not None
    assert result.balances["USD"] == "250.00"
    assert result.balances["BTC"] == "0.01"
    assert _order_posts(http) == []


def test_binance_preflight_factory_stays_blocked(fresh_keyring) -> None:
    del fresh_keyring
    transport = build_venue_preflight_transport(venue="binance", http_transport=object())
    result = evaluate(
        account_id="binance",
        revision_id="rev-binance",
        mode="sandbox",
        transport=transport,
    )
    assert result.ok is False
    assert result.code == CODE_PREFLIGHT_BLOCKED
    assert "unsupported" in (result.message or "").lower()


def test_live_preflight_api_accepts_coinbase_with_fake_transport(home, fresh_keyring) -> None:
    _store_coinbase_key(fresh_keyring)
    http = _LiveCoinbaseTransport(accounts=_accounts(usd="10.00", btc="0.002"))
    app = _build_app(home)
    app.state.krellbot.keys_transport = http
    app.state.krellbot.keys_allow_fake_backend = True

    session = _bootstrap(app)
    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        {
            "schema_version": "1",
            "command": "live.preflight",
            "correlation_id": "second-venue-preflight-1",
            "payload": {
                "venue": VENUE,
                "account_id": VENUE,
                "revision_id": "rev-api",
                "mode": "sandbox",
            },
        },
        headers=session,
    )
    assert status == 200, body
    verdict = json.loads(body)
    assert verdict["ok"] is True, verdict
    assert verdict["code"] == CODE_OK
    assert verdict["permissions"] == {"can_trade": True, "can_withdraw": False}
    assert verdict["balances"]["USD"] == "10.00"
    assert verdict["balances"]["BTC"] == "0.002"
    assert _order_posts(http) == []
