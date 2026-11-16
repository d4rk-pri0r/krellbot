"""Coinbase live gate + preflight parity with the Kraken M1 spine (M11.3).

Covers live authorization, obligations, venue-backed preflight, and
documented-response classification — all against ``FakeCoinbaseTransport``.
``PAPER_ONLY_RELEASE`` stays ``True`` in production; live-mechanics cases use
the test-only ``live_capable_release`` fixture.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fakes.fake_coinbase import FakeCoinbaseTransport, RecordedCall
from fakes.live_grant import write_grant

from krellbot import release_policy
from krellbot.application import live_gate
from krellbot.application.live_preflight import (
    CODE_OK,
    CODE_PREFLIGHT_BLOCKED,
    CODE_VENUE_UNREACHABLE,
    SandboxTransport,
    VenueBackedPreflightTransport,
    build_venue_preflight_transport,
    evaluate,
)
from krellbot.config import ArmedPack, Config, load_config, save_config
from krellbot.pack.model import Candle
from krellbot.storage.database import OperationalStore
from krellbot.venues.coinbase import (
    CoinbaseDocumentedOutcome,
    CoinbaseVenue,
    classify_documented_response,
)

VENUE = "coinbase"
PAIR = "BTC-USD"
COINBASE_TEST_KEY = "organizations/fake-org/apiKeys/fake-coinbase-key-001"
COINBASE_TEST_SECRET = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQGKiOPddAnxlf1S2y08ul1yymcJvx2UEhvzdIgBtA9vXA=="

TRADE_ONLY_PERMS = [
    {"scope": "view", "can_view": True, "can_transfer": False},
    {"scope": "trade", "can_trade": True, "can_transfer": False},
    {"scope": "transfer", "can_transfer": False},
]

WITHDRAW_PERMS = [
    {"scope": "view", "can_view": True, "can_transfer": False},
    {"scope": "trade", "can_trade": True, "can_transfer": False},
    {"scope": "transfer", "can_transfer": True},
]

BTC_USD_PRODUCT = {
    "product_id": PAIR,
    "base_increment": "0.00000001",
    "quote_increment": "0.01",
    "base_min_size": "0.00000001",
    "quote_min_size": "1",
    "price": "12",
}

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "venues" / "coinbase"
PROVENANCE_MARKER = "derived from Coinbase's Advanced Trade REST documentation, not recorded from a real account"
DOCUMENTED_CASES = (
    ("order_accepted", CoinbaseDocumentedOutcome.ORDER_ACCEPTED),
    ("insufficient_funds", CoinbaseDocumentedOutcome.INSUFFICIENT_FUNDS),
    ("order_minimum_not_met", CoinbaseDocumentedOutcome.ORDER_MINIMUM_NOT_MET),
    ("rate_limit", CoinbaseDocumentedOutcome.RATE_LIMIT),
    ("invalid_nonce", CoinbaseDocumentedOutcome.INVALID_NONCE),
    ("no_response", CoinbaseDocumentedOutcome.NO_RESPONSE),
    ("partially_filled", CoinbaseDocumentedOutcome.PARTIALLY_FILLED),
    ("stop_triggered", CoinbaseDocumentedOutcome.STOP_TRIGGERED),
    ("cancel_accepted", CoinbaseDocumentedOutcome.CANCEL_ACCEPTED),
)

TEST_PORT = 8080


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _accounts(*, usd: str = "1000", btc: str = "0") -> dict:
    accounts = [
        {
            "uuid": "usd-acct",
            "currency": "USD",
            "available_balance": {"value": usd, "currency": "USD"},
        }
    ]
    if Decimal(btc) != 0:
        accounts.append(
            {
                "uuid": "btc-acct",
                "currency": "BTC",
                "available_balance": {"value": btc, "currency": "BTC"},
            }
        )
    return {"accounts": accounts}


def _filled_order(*, order_id: str, side: str = "BUY") -> dict:
    return {
        "success": True,
        "success_response": {
            "order_id": order_id,
            "product_id": PAIR,
            "side": side,
            "status": "FILLED",
            "filled_size": "0.1",
        },
    }


def _accepted_order(*, order_id: str, side: str = "SELL") -> dict:
    return {
        "success": True,
        "success_response": {
            "order_id": order_id,
            "product_id": PAIR,
            "side": side,
        },
    }


class _LiveCoinbaseTransport(FakeCoinbaseTransport):
    """Fake with stable product / permissions for live obligation ticks."""

    def __init__(
        self,
        post_responses: list[dict] | None = None,
        *,
        accounts: dict | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            post_responses=post_responses,
            key_permissions=kwargs.pop("key_permissions", list(TRADE_ONLY_PERMS)),
            product=kwargs.pop("product", dict(BTC_USD_PRODUCT)),
            accounts=accounts if accounts is not None else _accounts(),
            orders=kwargs.pop("orders", {"orders": [], "has_next": False}),
            fills=kwargs.pop("fills", {"fills": []}),
            **kwargs,
        )


def _write_pack(home: Path, *, pack_id: str, pair: str = PAIR, cap_pct: int = 100) -> Path:
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Coinbase live obligations",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": cap_pct, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": VENUE, "pair": pair}],
    }
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm_live(
    home: Path,
    pack_path: Path,
    *,
    pack_id: str,
    pair: str = PAIR,
    cap: Decimal = Decimal(100),
    entries_paused: bool = False,
    owned_qty: Decimal = Decimal(0),
    starting_cash: Decimal | None = None,
) -> None:
    save_config(
        home,
        Config(
            armed=[
                ArmedPack(
                    pack_path=str(pack_path),
                    pack_sha256="0" * 64,
                    pack_id=pack_id,
                    pack_version="1.0.0",
                    venue=VENUE,
                    pair=pair,
                    cap=cap,
                    stop=Decimal(5),
                    mode="live",
                    starting_cash=starting_cash,
                    requires_license=False,
                    armed_at_ts=1,
                    owned_qty=owned_qty,
                    entries_paused=entries_paused,
                )
            ]
        ),
    )


def _candle(ts_ms: int, close: str) -> Candle:
    c = Decimal(close)
    return Candle(
        ts_ms=ts_ms,
        open=c,
        high=c + Decimal(1),
        low=c - Decimal(1),
        close=c,
        volume=Decimal(100),
    )


def _entry_candles() -> list[Candle]:
    return [_candle(0, "10"), _candle(3_600_000, "10"), _candle(7_200_000, "12")]


def _exit_candles() -> list[Candle]:
    return [_candle(0, "12"), _candle(3_600_000, "12"), _candle(7_200_000, "8")]


def _coinbase_venue(transport: FakeCoinbaseTransport) -> CoinbaseVenue:
    return CoinbaseVenue(
        COINBASE_TEST_KEY,
        COINBASE_TEST_SECRET,
        transport,
        product_id=PAIR,
        now_fn=lambda: 1_700_000_000,
        nonce_fn=lambda: "aa" * 16,
    )


def _seed_journal_owned(home: Path, *, pack_id: str, owned_qty: Decimal, pair: str = PAIR) -> None:
    from krellbot import journal as kb_journal

    kb_journal.append(
        {
            "ts": 1,
            "kind": "tick",
            "venue": VENUE,
            "pack": pack_id,
            "bar_ts": 0,
            "detail": {
                "pair": pair,
                "entry_qty": str(owned_qty),
                "exit_qty": "0",
                "stop_qty": "0",
            },
        }
    )


def _order_posts(transport: FakeCoinbaseTransport) -> list[RecordedCall]:
    return [c for c in transport.calls if c.method == "POST" and c.url.rstrip("/").endswith("/orders")]


def _enable_live(home: Path, monkeypatch: pytest.MonkeyPatch, *, pair: str = PAIR) -> None:
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=pair)


def _load_fixture(name: str) -> object:
    path = FIXTURES / f"{name}.json"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines, f"empty fixture: {path}"
    assert lines[0].startswith("#"), f"fixture must start with a comment: {path}"
    assert PROVENANCE_MARKER.lower() in lines[0].lower(), f"fixture missing provenance comment: {path}"
    body = "\n".join(lines[1:]).strip()
    return json.loads(body)


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


def _build_app(home: Path, *, bootstrap_token: str = "boot-coinbase-preflight"):
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


def _bootstrap(app, token: str = "boot-coinbase-preflight") -> list[tuple[str, str]]:
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


def _store_coinbase_key(fresh_keyring) -> None:
    fresh_keyring.set_password("krellbot:coinbase", "key", COINBASE_TEST_KEY)
    fresh_keyring.set_password("krellbot:coinbase", "secret", COINBASE_TEST_SECRET)


def _preflight_payload(
    *,
    account_id: str = VENUE,
    revision_id: str = "rev-coinbase-preflight-1",
    mode: str = "sandbox",
    venue: str = VENUE,
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "command": "live.preflight",
        "correlation_id": "coinbase-preflight-1",
        "payload": {
            "account_id": account_id,
            "revision_id": revision_id,
            "mode": mode,
            "venue": venue,
        },
    }


def _enable_keys(app, transport: FakeCoinbaseTransport) -> None:
    app.state.krellbot.keys_transport = transport
    app.state.krellbot.keys_allow_fake_backend = True


# ---------------------------------------------------------------------------
# A. Live authorization (venue-agnostic gate, coinbase strings pinned)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("live_capable_release")
def test_coinbase_grant_and_env_authorizes_send(home, monkeypatch):
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    result = live_gate.check_live_send(home, venue=VENUE, pair=PAIR)
    assert result.ok is True, result


@pytest.mark.usefixtures("live_capable_release")
def test_coinbase_wrong_pair_refused(home, monkeypatch):
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    result = live_gate.check_live_send(home, venue=VENUE, pair="ETH-USD")
    assert result.ok is False
    assert result.code == live_gate.CODE_LIVE_NOT_AUTHORIZED


def test_coinbase_paper_only_still_refuses_without_reading_grant(home, monkeypatch):
    """Shipped paper-only policy refuses Coinbase live send before grant I/O."""
    assert release_policy.PAPER_ONLY_RELEASE is True
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    result = live_gate.check_live_send(home, venue=VENUE, pair=PAIR)
    assert result.ok is False
    assert result.code == live_gate.CODE_PAPER_ONLY_RELEASE


# ---------------------------------------------------------------------------
# B. Preflight (M10.2 pattern with FakeCoinbaseTransport)
# ---------------------------------------------------------------------------


def test_build_venue_preflight_transport_supports_coinbase(fresh_keyring) -> None:
    _store_coinbase_key(fresh_keyring)
    http = _LiveCoinbaseTransport()
    transport = build_venue_preflight_transport(venue=VENUE, http_transport=http)
    assert not isinstance(transport, SandboxTransport)
    assert isinstance(transport, VenueBackedPreflightTransport)
    assert transport.account == VENUE


def test_coinbase_preflight_trade_only_returns_balances_never_posts_orders(fresh_keyring) -> None:
    _store_coinbase_key(fresh_keyring)
    http = _LiveCoinbaseTransport(accounts=_accounts(usd="100.50", btc="0.01"))
    transport = build_venue_preflight_transport(venue=VENUE, http_transport=http)
    result = evaluate(
        account_id=VENUE,
        revision_id="rev-1",
        mode="sandbox",
        transport=transport,
    )
    assert result.ok is True, result
    assert result.code == CODE_OK
    assert result.permissions == {"can_trade": True, "can_withdraw": False}
    assert result.balances is not None
    assert result.balances["USD"] == "100.50"
    assert result.balances["BTC"] == "0.01"
    assert any("key_permissions" in c.url for c in http.calls)
    assert any("/brokerage/accounts" in c.url for c in http.calls)
    assert _order_posts(http) == []


def test_coinbase_preflight_blocks_transfer_capable_key(home: Path, fresh_keyring) -> None:
    _store_coinbase_key(fresh_keyring)
    http = _LiveCoinbaseTransport(key_permissions=list(WITHDRAW_PERMS))
    app = _build_app(home)
    _enable_keys(app, http)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _preflight_payload(),
        headers=session,
    )
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["ok"] is False, decoded
    assert decoded["code"] == CODE_PREFLIGHT_BLOCKED
    assert _order_posts(http) == []
    assert not any("/brokerage/accounts" in c.url for c in http.calls)


def test_coinbase_preflight_unreachable_on_accounts_failure(home: Path, fresh_keyring) -> None:
    _store_coinbase_key(fresh_keyring)
    http = _LiveCoinbaseTransport(raise_on_get={"/brokerage/accounts"})
    app = _build_app(home)
    _enable_keys(app, http)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _preflight_payload(),
        headers=session,
    )
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["ok"] is False, decoded
    assert decoded["code"] == CODE_VENUE_UNREACHABLE
    assert any("key_permissions" in c.url for c in http.calls)
    assert _order_posts(http) == []


def test_coinbase_preflight_missing_key_blocked(home: Path, fresh_keyring) -> None:
    del fresh_keyring
    http = _LiveCoinbaseTransport()
    app = _build_app(home)
    _enable_keys(app, http)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _preflight_payload(),
        headers=session,
    )
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["ok"] is False, decoded
    assert decoded["code"] == CODE_PREFLIGHT_BLOCKED
    assert http.calls == []


# ---------------------------------------------------------------------------
# C. Four live obligations (Coinbase / BTC-USD)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("live_capable_release")
def test_coinbase_entry_pause_survives_restart(home, monkeypatch):
    from krellbot.run import tick

    _enable_live(home, monkeypatch)
    pack_id = "cb-live-pause-restart"
    pack_path = _write_pack(home, pack_id=pack_id)
    _arm_live(home, pack_path, pack_id=pack_id, entries_paused=True)

    reloaded = load_config(home)
    assert reloaded.armed[0].entries_paused is True

    transport_entry = _LiveCoinbaseTransport(
        post_responses=[_filled_order(order_id="TX-ENTRY-SHOULD-NOT")],
        accounts=_accounts(usd="1000"),
    )
    venue_entry = _coinbase_venue(transport_entry)
    rc_entry = tick(
        venue=VENUE,
        venue_obj=venue_entry,
        reader=lambda v, p: _entry_candles(),
        home=home,
    )
    assert rc_entry == 0
    buys = [c for c in _order_posts(transport_entry) if (c.body or {}).get("side") == "BUY"]
    assert buys == [], f"paused live entry must not POST buy; got {_order_posts(transport_entry)}"

    for jf in (home / "journal").glob("*.jsonl"):
        jf.unlink()
    cfg = load_config(home)
    cfg.armed[0].owned_qty = Decimal(5)
    cfg.armed[0].entries_paused = True
    save_config(home, cfg)
    _seed_journal_owned(home, pack_id=pack_id, owned_qty=Decimal(5))

    transport_exit = _LiveCoinbaseTransport(
        post_responses=[_accepted_order(order_id="TX-EXIT", side="SELL")],
        accounts=_accounts(usd="1000", btc="5"),
        product={**BTC_USD_PRODUCT, "price": "8"},
    )
    venue_exit = _coinbase_venue(transport_exit)
    rc_exit = tick(
        venue=VENUE,
        venue_obj=venue_exit,
        reader=lambda v, p: _exit_candles(),
        home=home,
    )
    assert rc_exit == 0
    sells = [c for c in _order_posts(transport_exit) if (c.body or {}).get("side") == "SELL"]
    assert sells, f"paused live tick must still exit owned qty; posts={_order_posts(transport_exit)}"


@pytest.mark.usefixtures("live_capable_release")
def test_coinbase_pack_never_touches_external_inventory(home, monkeypatch):
    from krellbot.run import tick

    _enable_live(home, monkeypatch)
    pack_id = "cb-live-ownership"
    reserved_cash = Decimal(100)
    pack_path = _write_pack(home, pack_id=pack_id, cap_pct=100)
    _arm_live(
        home,
        pack_path,
        pack_id=pack_id,
        cap=Decimal(100),
        starting_cash=reserved_cash,
    )

    transport_entry = _LiveCoinbaseTransport(
        post_responses=[
            _filled_order(order_id="TX-ENTRY"),
            _accepted_order(order_id="TX-STOP", side="SELL"),
        ],
        accounts=_accounts(usd="100000"),
        product={**BTC_USD_PRODUCT, "price": "12"},
    )
    venue_entry = _coinbase_venue(transport_entry)
    rc_entry = tick(
        venue=VENUE,
        venue_obj=venue_entry,
        reader=lambda v, p: _entry_candles(),
        home=home,
    )
    assert rc_entry == 0
    entry_buys = [c for c in _order_posts(transport_entry) if (c.body or {}).get("side") == "BUY"]
    assert len(entry_buys) == 1, entry_buys
    cfg_box = (entry_buys[0].body or {}).get("order_configuration") or {}
    market = cfg_box.get("market_market_ioc") or {}
    entry_qty = Decimal(str(market["base_size"]))
    entry_cost = entry_qty * Decimal(12)
    assert entry_cost <= reserved_cash + Decimal("0.01"), (
        f"entry must size against reserved cash {reserved_cash}, not account balance; qty={entry_qty} cost={entry_cost}"
    )

    for jf in (home / "journal").glob("*.jsonl"):
        jf.unlink()
    pack_id_exit = "cb-live-ownership-exit"
    pack_path_exit = _write_pack(home, pack_id=pack_id_exit)
    _arm_live(
        home,
        pack_path_exit,
        pack_id=pack_id_exit,
        owned_qty=Decimal(5),
        starting_cash=reserved_cash,
    )
    _seed_journal_owned(home, pack_id=pack_id_exit, owned_qty=Decimal(5))

    transport_exit = _LiveCoinbaseTransport(
        post_responses=[_accepted_order(order_id="TX-EXIT", side="SELL")],
        accounts=_accounts(usd="100000", btc="50"),
        product={**BTC_USD_PRODUCT, "price": "8"},
    )
    venue_exit = _coinbase_venue(transport_exit)
    rc_exit = tick(
        venue=VENUE,
        venue_obj=venue_exit,
        reader=lambda v, p: _exit_candles(),
        home=home,
    )
    assert rc_exit == 0
    sell_posts = [c for c in _order_posts(transport_exit) if (c.body or {}).get("side") == "SELL"]
    assert sell_posts, f"exit must place a sell; calls={transport_exit.calls}"
    sell_cfg = (sell_posts[0].body or {}).get("order_configuration") or {}
    sold = Decimal(str((sell_cfg.get("market_market_ioc") or {})["base_size"]))
    assert sold == Decimal(5), f"exit must not sell external inventory; sold={sold}"


@pytest.mark.usefixtures("live_capable_release")
def test_coinbase_unknown_outcome_reconciles_without_resubmit(home, monkeypatch):
    from krellbot.run import coid_for, tick
    from krellbot.storage.outbox import Outbox

    _enable_live(home, monkeypatch)
    pack_id = "cb-live-unknown-outcome"
    pack_path = _write_pack(home, pack_id=pack_id)
    _arm_live(home, pack_path, pack_id=pack_id)

    bar_ts = 7_200_000
    expected_coid = coid_for(
        pack_id=pack_id,
        pack_version="1.0.0",
        venue=VENUE,
        pair=PAIR,
        bar_ts=bar_ts,
        intent="entry",
    )

    store = OperationalStore(home / "ops.sqlite")
    body = json.dumps(
        {"kind": "entry", "qty": "10", "stop": "5", "pair": PAIR},
        separators=(",", ":"),
        sort_keys=True,
    )

    def _boom(coid: str, _body: str) -> None:
        raise RuntimeError("killed between commit and ack")

    with pytest.raises(RuntimeError, match="killed between commit and ack"):
        Outbox(store).dispatch(expected_coid, body, _boom, mode="live", venue=VENUE)
    rows = store.read_ledger()
    outbox_rows = [json.loads(p) for _i, k, p in rows if k == "outbox"]
    assert outbox_rows, rows
    assert outbox_rows[-1]["coid"] == expected_coid
    assert outbox_rows[-1]["sent"] is False

    transport = _LiveCoinbaseTransport(
        post_responses=[_filled_order(order_id="TX-RESUBMIT-FORBIDDEN")],
        accounts=_accounts(usd="1000"),
    )
    venue = _coinbase_venue(transport)

    rc = tick(
        venue=VENUE,
        venue_obj=venue,
        reader=lambda v, p: _entry_candles(),
        home=home,
    )
    assert rc == 0

    assert _order_posts(transport) == [], f"must not resubmit unknown outcome; posts={_order_posts(transport)}"

    ledger = store.read_ledger()
    needs = [json.loads(p) for _i, k, p in ledger if k == "needs_reconcile"]
    assert needs, f"unknown outcome must be audited for reconcile; ledger={ledger}"
    assert any(k == "needs_reconcile" for _i, k, _p in ledger)


@pytest.mark.usefixtures("live_capable_release")
def test_coinbase_restored_home_is_fenced(home, monkeypatch, tmp_path):
    from krellbot.run import tick
    from krellbot.storage import home_backup

    _enable_live(home, monkeypatch)
    pack_id = "cb-live-restore-fence"
    pack_path = _write_pack(home, pack_id=pack_id)
    packs_dir = home / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    installed = packs_dir / f"{pack_id}.json"
    installed.write_text(pack_path.read_text(encoding="utf-8"), encoding="utf-8")
    _arm_live(home, installed, pack_id=pack_id, entries_paused=False)
    OperationalStore(home / "ops.sqlite").connect()

    archive = tmp_path / "home-backup.tar.gz"
    home_backup.create(home, archive, now=1_700_000_000)

    restored = tmp_path / "restored-home"
    home_backup.restore(archive, restored)

    cfg = load_config(restored)
    live_arms = [a for a in cfg.armed if a.mode == "live"]
    assert live_arms, cfg
    assert all(a.entries_paused for a in live_arms), f"restored live arms must be paused; {live_arms}"
    assert live_gate.kill_state(restored).engaged is True

    monkeypatch.setenv("KRELLBOT_HOME", str(restored))
    write_grant(restored, venue=VENUE, pair=PAIR)

    transport = _LiveCoinbaseTransport(
        post_responses=[_filled_order(order_id="TX-FENCE-LEAK")],
        accounts=_accounts(usd="1000"),
    )
    venue = _coinbase_venue(transport)
    rc = tick(
        venue=VENUE,
        venue_obj=venue,
        reader=lambda v, p: _entry_candles(),
        home=restored,
    )
    assert rc == 0
    assert _order_posts(transport) == [], "fenced restored home must not send"


# ---------------------------------------------------------------------------
# D. Documented responses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("fixture_name", "expected"), DOCUMENTED_CASES)
def test_documented_coinbase_fixture_maps_to_typed_outcome(fixture_name: str, expected: str) -> None:
    payload = _load_fixture(fixture_name)
    assert classify_documented_response(payload) == expected
    assert expected in CoinbaseDocumentedOutcome.values()
