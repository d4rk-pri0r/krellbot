"""Authoritative paper facts: real gated GETs, local fake-keyring state only."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot import config as kb_config
from krellbot.application.paper import PaperService
from tests.test_ns06_api import TEST_PORT, _build_app, _do_bootstrap, _write_dsl_pack, asgi_call

pytestmark = pytest.mark.usefixtures("fresh_keyring")
DETAILS_PATH = "/api/v1/paper/details"


def _arm(home: Path) -> None:
    # Reuse the existing known-valid DSL config, changing only its allowed cap.
    pack = _write_dsl_pack(home)
    body = json.loads(pack.read_text(encoding="utf-8"))
    body["risk"]["max_account_pct"] = 100
    pack.write_text(json.dumps(body), encoding="utf-8")
    result = PaperService(home=home).arm(
        pack, venue="kraken", mode="paper", paper_balance=Decimal(2500), correlation_id="details-arm"
    )
    assert result.ok, result
    assert kb_config.load_config(home).armed[0].starting_cash == Decimal(2500)


def _session(app) -> str:
    _do_bootstrap(app, token="boot-test-token")
    return next(iter(app.state.krellbot.sessions))


def _get(app, session: str, *, path: str = DETAILS_PATH):
    return asgi_call(
        app,
        method="GET",
        path=path,
        headers=[("Host", f"127.0.0.1:{TEST_PORT}"), ("Cookie", f"krellbot_session={session}")],
    )


def _snapshot(home: Path) -> dict:
    """Bytes + nanosecond mtimes, including directories and file absence."""
    return {
        str(path.relative_to(home)): (path.read_bytes() if path.is_file() else None, path.stat().st_mtime_ns)
        for path in [home, *sorted(home.rglob("*"))]
    }


def _expected(*, starting_cash="2500", risk_cap_pct="100", resting_stop=None) -> dict:
    return {
        "schema_version": "1",
        "armed": True,
        "venue": "kraken",
        "pair": "SUIUSD",
        "pack_id": "trend-follow",
        "starting_cash": starting_cash,
        "risk_cap_pct": risk_cap_pct,
        "resting_stop": resting_stop,
    }


def _assert_repeated_reads(app, home: Path, session: str, expected: dict) -> None:
    before = _snapshot(home)
    for _ in range(3):
        status, headers, raw, cookies = _get(app, session)
        assert status == 200, (status, raw)
        assert json.loads(raw) == expected
        assert [v for k, v in headers if k.lower() == "cache-control"] == ["no-store"]
        assert cookies == []
        assert _snapshot(home) == before
    assert app.state.krellbot.paper_service is None
    assert app.state.krellbot.rehearsal_service is None


def _write_state(home: Path, state, *, venue="kraken") -> Path:
    path = home / "run" / f"paper-{venue}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def _order(pair="SUIUSD", stop="3.8000") -> dict:
    return {"coid": "synthetic-stop", "pair": pair, "side": "sell", "qty": "5", "stop_price": stop}


def test_fresh_arm_reports_deposit_and_percent_without_materialising_state(home: Path, monkeypatch) -> None:
    _arm(home)
    assert not (home / "run" / "paper-kraken.json").exists()
    # Arming creates the standard layout, but no tick/journal records.
    assert list((home / "journal").iterdir()) == []
    app = _build_app(home)
    session = _session(app)

    def forbidden(*args, **kwargs):
        pytest.fail("read endpoint constructed a trading service/adapter or performed network I/O")

    # These are tripwires, not replacements for the read projection under test.
    monkeypatch.setattr("krellbot.venues.paper.PaperVenue.__init__", forbidden)
    monkeypatch.setattr("krellbot.application.paper.PaperService.__init__", forbidden)
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    _assert_repeated_reads(app, home, session, _expected())
    assert not (home / "run" / "paper-kraken.json").exists()
    assert list((home / "journal").iterdir()) == []

    # Do not "fix" the separate, existing closed position/status contracts.
    status, _, raw, _ = _get(app, session, path="/api/v1/paper/position")
    assert status == 200
    assert json.loads(raw) == {
        "schema_version": "1",
        "armed": True,
        "venue": "kraken",
        "pair": "SUIUSD",
        "mode": "paper",
        "free_cash": "0",
        "holdings": [],
        "as_of_run": None,
    }
    status, _, raw, _ = _get(app, session, path="/api/v1/paper/status")
    assert status == 200
    assert json.loads(raw) == {
        "schema_version": "1",
        "armed": True,
        "venue": "kraken",
        "pair": "SUIUSD",
        "mode": "paper",
        "pack_id": "trend-follow",
        "entries_paused": False,
    }


def test_no_armed_pack_is_closed_and_does_not_write(home: Path) -> None:
    app = _build_app(home)
    session = _session(app)
    _assert_repeated_reads(app, home, session, {"schema_version": "1", "armed": False})
    assert not (home / "config.json").exists()
    assert not (home / "run").exists()


@pytest.mark.parametrize("mode", ["live", "sandbox", ""])
def test_nonpaper_first_record_hides_all_facts_even_with_later_paper(home: Path, mode: str) -> None:
    _arm(home)
    config = kb_config.load_config(home)
    first = config.armed[0]
    config.armed = [replace(first, mode=mode, pack_id="private-live-record"), replace(first, pair="BTCUSD")]
    kb_config.save_config(home, config)
    _write_state(home, {"open_orders": [_order()]})
    app = _build_app(home)
    session = _session(app)
    _assert_repeated_reads(app, home, session, {"schema_version": "1", "armed": False})


def test_only_first_armed_pair_and_venue_contribute_a_stop(home: Path) -> None:
    _arm(home)
    config = kb_config.load_config(home)
    first = config.armed[0]
    config.armed.append(replace(first, pair="BTCUSD", starting_cash=Decimal(9000)))
    kb_config.save_config(home, config)
    _write_state(home, {"open_orders": [_order("BTCUSD", "60000"), _order("SUIUSD", "3.8000")]})
    _write_state(home, {"open_orders": [_order("SUIUSD", "9")]}, venue="coinbase")
    app = _build_app(home)
    session = _session(app)
    _assert_repeated_reads(app, home, session, _expected(resting_stop="3.8"))

    _write_state(home, {"open_orders": [_order("BTCUSD", "60000")]})
    _assert_repeated_reads(app, home, session, _expected())


@pytest.mark.parametrize(
    "state",
    [
        None,
        [],
        "bad",
        1,
        {},
        {"open_orders": None},
        {"open_orders": {}},
        {"open_orders": "bad"},
        {"open_orders": [None, [], 4, {}, {"pair": "SUIUSD"}]},
        {"open_orders": []},
    ],
)
def test_missing_or_malformed_state_has_no_guessed_stop(home: Path, state) -> None:
    _arm(home)
    _write_state(home, state)
    app = _build_app(home)
    session = _session(app)
    _assert_repeated_reads(app, home, session, _expected())


@pytest.mark.parametrize("raw", [b"{torn", b"\xff\xfe", b""])
def test_unreadable_json_or_encoding_is_null_without_repair(home: Path, raw: bytes) -> None:
    _arm(home)
    path = _write_state(home, {})
    path.write_bytes(raw)
    app = _build_app(home)
    session = _session(app)
    _assert_repeated_reads(app, home, session, _expected())


@pytest.mark.parametrize(
    "stop", [None, "", "not-a-stop", "NaN", "sNaN", "Infinity", "-Infinity", float("nan"), float("inf"), True, [], {}]
)
def test_malformed_or_nonfinite_matching_stop_is_null(home: Path, stop) -> None:
    _arm(home)
    _write_state(home, {"open_orders": [_order("BTCUSD", "60000"), _order(stop=stop)]})
    app = _build_app(home)
    session = _session(app)
    _assert_repeated_reads(app, home, session, _expected())


@pytest.mark.parametrize(
    "stop, canonical",
    [
        ("3.8000", "3.8"),
        ("3.8E+1", "38"),
        (4, "4"),
        (3.125, "3.125"),
        ("0.00000001", "0.00000001"),
        ("3.123456789012345678901234567890", "3.12345678901234567890123456789"),
    ],
)
def test_stop_decimal_serialization_is_canonical_and_exact(home: Path, stop, canonical: str) -> None:
    _arm(home)
    _write_state(home, {"balances": {"USD": "42", "SUI": "999"}, "open_orders": [_order(stop=stop)]})
    app = _build_app(home)
    session = _session(app)
    _assert_repeated_reads(app, home, session, _expected(resting_stop=canonical))


@pytest.mark.parametrize(
    "starting_cash, cap, cash_wire, cap_wire",
    [
        (None, "12.5000", None, "12.5"),
        ("2.500E+3", "1.00E+2", "2500", "100"),
    ],
)
def test_configured_deposit_and_percent_are_not_balances_or_currency(
    home: Path, starting_cash, cap: str, cash_wire, cap_wire: str
) -> None:
    _arm(home)
    config = kb_config.load_config(home)
    config.armed[0].starting_cash = Decimal(starting_cash) if starting_cash is not None else None
    config.armed[0].cap = Decimal(cap)
    kb_config.save_config(home, config)
    _write_state(home, {"balances": {"USD": "42", "SUI": "999"}, "open_orders": []})
    app = _build_app(home)
    session = _session(app)
    _assert_repeated_reads(app, home, session, _expected(starting_cash=cash_wire, risk_cap_pct=cap_wire))


@pytest.mark.parametrize(
    "case, detail",
    [
        ("missing", "session required"),
        ("invented", "session required"),
        ("revoked", "session required"),
        ("foreign-origin", "origin not loopback"),
        ("wrong-origin-port", "origin not loopback"),
        ("foreign-host", "loopback only"),
        ("missing-host", "loopback only"),
        ("wrong-host-port", "loopback only"),
    ],
)
def test_details_uses_existing_read_security_gate_without_writes(home: Path, case: str, detail: str) -> None:
    _arm(home)
    app = _build_app(home)
    session = _session(app)
    headers = {"Host": f"127.0.0.1:{TEST_PORT}", "Cookie": f"krellbot_session={session}"}
    if case == "missing":
        del headers["Cookie"]
    elif case == "invented":
        headers["Cookie"] = "krellbot_session=invented"
    elif case == "revoked":
        app.state.krellbot.sessions.pop(session)
    elif case == "foreign-origin":
        headers["Origin"] = "http://evil.example"
    elif case == "wrong-origin-port":
        headers["Origin"] = "http://127.0.0.1:9999"
    elif case == "foreign-host":
        headers["Host"] = "evil.example"
    elif case == "missing-host":
        del headers["Host"]
    elif case == "wrong-host-port":
        headers["Host"] = "127.0.0.1:9999"
    before = _snapshot(home)
    for _ in range(3):
        status, _, raw, _ = asgi_call(app, method="GET", path=DETAILS_PATH, headers=list(headers.items()))
        assert status == 403, (status, raw)
        assert json.loads(raw) == {"detail": detail}
        assert _snapshot(home) == before


def test_loopback_origin_and_irrelevant_csrf_are_allowed(home: Path) -> None:
    app = _build_app(home)
    session = _session(app)
    status, headers, raw, _ = asgi_call(
        app,
        method="GET",
        path=DETAILS_PATH,
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
            ("Cookie", f"krellbot_session={session}"),
            ("X-Krellbot-CSRF", "irrelevant"),
        ],
    )
    assert status == 200, (status, raw)
    assert json.loads(raw) == {"schema_version": "1", "armed": False}
    assert ("cache-control", "no-store") in headers


@pytest.mark.parametrize(
    "raw_stop, expected",
    [
        pytest.param("9" * 5000, None, id="edge-oversized-json-integer"),
        pytest.param(
            "3.123456789012345678901234567890",
            "3.12345678901234567890123456789",
            id="json-fraction-precision",
        ),
        pytest.param("1e-1000", "0." + "0" * 999 + "1", id="json-fraction-underflow"),
    ],
)
def test_rejected_raw_json_numeric_stop_rows(home: Path, raw_stop: str, expected: str | None) -> None:
    """Reviewer rows F1/F2: raw tokens must not pass through binary float."""
    _arm(home)
    path = _write_state(home, {})
    # Do not json.dumps a Python float: the persisted token itself is the
    # reviewer reproducer, including precision unavailable to binary float.
    path.write_text(
        '{"open_orders":[{"pair":"SUIUSD","stop_price":' + raw_stop + "}]}",
        encoding="utf-8",
    )
    app = _build_app(home)
    session = _session(app)
    _assert_repeated_reads(app, home, session, _expected(resting_stop=expected))
