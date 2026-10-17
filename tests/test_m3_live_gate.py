"""M3-GATE: operator-owned live authorization gate and kill switch.

Twelve contract bullets, each pinned by at least one test. Every test uses
``tmp_path`` as the krellbot home so ``~/.krellbot`` is never touched.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

from krellbot.application import live_gate

# ---------------------------------------------------------------------------
# Shared constants and fixture-style helpers
# ---------------------------------------------------------------------------

NOW = 1_700_000_000
GRANTED_VENUE = "kraken"
GRANTED_PAIR = "BTC/USD"


def _valid_payload(now: int = NOW) -> dict:
    """A minimally-valid authorization payload with one grant and a future expiry."""
    return {
        "schema_version": "1",
        "granted_by": "operator",
        "expires_at": now + 10_000,
        "grants": [{"venue": GRANTED_VENUE, "pair": GRANTED_PAIR}],
    }


def _write_auth(tmp_path: Path, payload: dict | None = None, *, raw: bytes | None = None) -> Path:
    """Write ``payload`` (as JSON) or ``raw`` bytes to the auth file under tmp_path."""
    path = live_gate.auth_path(tmp_path)
    if raw is not None:
        path.write_bytes(raw)
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_valid_auth(tmp_path: Path, now: int = NOW) -> Path:
    return _write_auth(tmp_path, _valid_payload(now))


def _enable_env() -> dict:
    return {"KRELLBOT_ENABLE_LIVE": "1"}


# ---------------------------------------------------------------------------
# Test 1: missing auth file with env "1" => live_not_authorized
# ---------------------------------------------------------------------------


def test_missing_auth_file_returns_live_not_authorized(tmp_path: Path) -> None:
    assert not live_gate.auth_path(tmp_path).exists()
    result = live_gate.check_live_send(
        tmp_path,
        venue=GRANTED_VENUE,
        pair=GRANTED_PAIR,
        env=_enable_env(),
        now=NOW,
    )
    assert result.code == live_gate.CODE_LIVE_NOT_AUTHORIZED
    assert result.ok is False


# ---------------------------------------------------------------------------
# Test 2: live_disabled under various env values, with a valid grant on disk
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({}, id="env_empty"),
        pytest.param({"KRELLBOT_ENABLE_LIVE": "0"}, id="env_zero"),
        pytest.param({"KRELLBOT_ENABLE_LIVE": "true"}, id="env_true_string"),
        pytest.param({"KRELLBOT_ENABLE_LIVE": " 1"}, id="env_padded_space"),
        pytest.param({"KRELLBOT_ENABLE_LIVE": "01"}, id="env_leading_zero"),
    ],
)
def test_live_disabled_under_non_one_env(tmp_path: Path, env: dict) -> None:
    _write_valid_auth(tmp_path)
    result = live_gate.check_live_send(
        tmp_path,
        venue=GRANTED_VENUE,
        pair=GRANTED_PAIR,
        env=env,
        now=NOW,
    )
    assert result.code == live_gate.CODE_LIVE_DISABLED
    assert result.ok is False


# ---------------------------------------------------------------------------
# Test 3: valid grant + env "1" => ok; mismatches => live_not_authorized
# ---------------------------------------------------------------------------


def test_valid_grant_and_env_returns_ok(tmp_path: Path) -> None:
    _write_valid_auth(tmp_path)
    result = live_gate.check_live_send(
        tmp_path,
        venue=GRANTED_VENUE,
        pair=GRANTED_PAIR,
        env=_enable_env(),
        now=NOW,
    )
    assert result.code == live_gate.CODE_OK
    assert result.ok is True
    assert result.message == "live send authorized"


@pytest.mark.parametrize(
    "venue,pair",
    [
        pytest.param("kraken", "ETH/USD", id="different_pair"),
        pytest.param("coinbase", "BTC/USD", id="different_venue"),
        pytest.param("kraken", "btc/usd", id="case_changed_pair"),
    ],
)
def test_mismatched_grant_returns_live_not_authorized(tmp_path: Path, venue: str, pair: str) -> None:
    _write_valid_auth(tmp_path)
    result = live_gate.check_live_send(
        tmp_path,
        venue=venue,
        pair=pair,
        env=_enable_env(),
        now=NOW,
    )
    assert result.code == live_gate.CODE_LIVE_NOT_AUTHORIZED


# ---------------------------------------------------------------------------
# Test 4: every malformed auth case => read_authorization == [] and
# check_live_send returns live_not_authorized.
# ---------------------------------------------------------------------------


def _assert_malformed_auth_yields_nothing(tmp_path: Path) -> None:
    """Common assertion: empty grants + live_not_authorized on check_live_send."""
    grants = live_gate.read_authorization(tmp_path, now=NOW)
    assert grants == [], f"expected empty grants, got {grants}"
    result = live_gate.check_live_send(
        tmp_path,
        venue=GRANTED_VENUE,
        pair=GRANTED_PAIR,
        env=_enable_env(),
        now=NOW,
    )
    assert result.code == live_gate.CODE_LIVE_NOT_AUTHORIZED


@pytest.mark.parametrize(
    "case",
    [
        "expires_true",
        "expires_float",
        "expires_str",
        "expires_none",
        "expires_now",
        "expires_past",
        "schema_int",
        "granted_by_product",
        "grants_dict",
        "grant_pair_nonstr",
        "non_json",
    ],
)
def test_malformed_auth_yields_empty_grants(tmp_path: Path, case: str) -> None:
    if case == "expires_true":
        p = _valid_payload()
        p["expires_at"] = True
        _write_auth(tmp_path, p)
    elif case == "expires_float":
        p = _valid_payload()
        p["expires_at"] = 1.0
        _write_auth(tmp_path, p)
    elif case == "expires_str":
        p = _valid_payload()
        p["expires_at"] = "1893456000"
        _write_auth(tmp_path, p)
    elif case == "expires_none":
        p = _valid_payload()
        p["expires_at"] = None
        _write_auth(tmp_path, p)
    elif case == "expires_now":
        p = _valid_payload()
        p["expires_at"] = NOW
        _write_auth(tmp_path, p)
    elif case == "expires_past":
        p = _valid_payload()
        p["expires_at"] = NOW - 1
        _write_auth(tmp_path, p)
    elif case == "schema_int":
        p = _valid_payload()
        p["schema_version"] = 1
        _write_auth(tmp_path, p)
    elif case == "granted_by_product":
        p = _valid_payload()
        p["granted_by"] = "product"
        _write_auth(tmp_path, p)
    elif case == "grants_dict":
        p = _valid_payload()
        p["grants"] = {}
        _write_auth(tmp_path, p)
    elif case == "grant_pair_nonstr":
        p = _valid_payload()
        p["grants"] = [{"venue": "kraken", "pair": 123}]
        _write_auth(tmp_path, p)
    elif case == "non_json":
        _write_auth(tmp_path, raw=b"{not json")
    else:
        pytest.fail(f"unknown case {case}")

    _assert_malformed_auth_yields_nothing(tmp_path)


# ---------------------------------------------------------------------------
# Test 5: kill switch beats everything; release restores OK.
# ---------------------------------------------------------------------------


def test_kill_switch_beats_authorization_then_release_restores_ok(
    tmp_path: Path,
) -> None:
    _write_valid_auth(tmp_path)
    live_gate.engage_kill(tmp_path, reason="halt", now=NOW)

    blocked = live_gate.check_live_send(
        tmp_path,
        venue=GRANTED_VENUE,
        pair=GRANTED_PAIR,
        env=_enable_env(),
        now=NOW + 1,
    )
    assert blocked.code == live_gate.CODE_KILL_SWITCH
    assert blocked.ok is False

    released = live_gate.release_kill(tmp_path)
    assert released.engaged is False

    allowed = live_gate.check_live_send(
        tmp_path,
        venue=GRANTED_VENUE,
        pair=GRANTED_PAIR,
        env=_enable_env(),
        now=NOW + 2,
    )
    assert allowed.code == live_gate.CODE_OK
    assert allowed.ok is True


# ---------------------------------------------------------------------------
# Test 6: corrupt kill file => engaged=True (fail closed).
# ---------------------------------------------------------------------------


def test_corrupt_kill_file_engages_kill_switch(tmp_path: Path) -> None:
    kill_file = live_gate.kill_path(tmp_path)
    kill_file.parent.mkdir(parents=True, exist_ok=True)
    kill_file.write_bytes(b"{not json")

    state = live_gate.kill_state(tmp_path)
    assert state.engaged is True

    result = live_gate.check_live_send(
        tmp_path,
        venue=GRANTED_VENUE,
        pair=GRANTED_PAIR,
        env=_enable_env(),
        now=NOW,
    )
    assert result.code == live_gate.CODE_KILL_SWITCH


# ---------------------------------------------------------------------------
# Test 7: engage_kill validates reason and now; nothing written on rejection.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason,now_arg",
    [
        pytest.param("", 1_000_000, id="reason_empty"),
        pytest.param("x" * 201, 1_000_000, id="reason_too_long"),
        pytest.param("a\nb", 1_000_000, id="reason_newline"),
        pytest.param(None, 1_000_000, id="reason_non_str"),
        pytest.param("valid", True),
        pytest.param("valid", 1.0),
    ],
)
def test_engage_kill_rejects_invalid_inputs(tmp_path: Path, reason: object, now_arg: object) -> None:
    with pytest.raises(ValueError):
        live_gate.engage_kill(tmp_path, reason=reason, now=now_arg)  # type: ignore[arg-type]
    assert not live_gate.kill_path(tmp_path).exists()


# ---------------------------------------------------------------------------
# Test 8: kill file mode (POSIX) and bytes format.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_engage_kill_file_mode_is_0600_on_posix(tmp_path: Path) -> None:
    live_gate.engage_kill(tmp_path, reason="test", now=NOW)
    path = live_gate.kill_path(tmp_path)
    assert path.stat().st_mode & 0o777 == 0o600


def test_engage_kill_file_bytes_format(tmp_path: Path) -> None:
    reason = "test"
    now = 1_700_000_000
    live_gate.engage_kill(tmp_path, reason=reason, now=now)
    path = live_gate.kill_path(tmp_path)
    expected = json.dumps(
        {"engaged": True, "reason": reason, "engaged_at": now},
        sort_keys=True,
        separators=(",", ":"),
    )
    assert path.read_bytes() == expected.encode("utf-8")


# ---------------------------------------------------------------------------
# Test 9: check_promotion owner-deferred matrix.
# ---------------------------------------------------------------------------


def test_check_promotion_owner_deferred_when_fully_authorized(tmp_path: Path) -> None:
    _write_valid_auth(tmp_path)
    result = live_gate.check_promotion(
        tmp_path,
        venue=GRANTED_VENUE,
        pair=GRANTED_PAIR,
        revision_id="rev-abc",
        env=_enable_env(),
        now=NOW,
    )
    assert result.code == live_gate.CODE_PROMOTION_DEFERRED
    assert result.ok is False


def test_check_promotion_live_disabled_when_env_not_one(tmp_path: Path) -> None:
    _write_valid_auth(tmp_path)
    result = live_gate.check_promotion(
        tmp_path,
        venue=GRANTED_VENUE,
        pair=GRANTED_PAIR,
        revision_id="rev-abc",
        env={},
        now=NOW,
    )
    assert result.code == live_gate.CODE_LIVE_DISABLED


def test_check_promotion_kill_switch_when_engaged(tmp_path: Path) -> None:
    _write_valid_auth(tmp_path)
    live_gate.engage_kill(tmp_path, reason="halt", now=NOW)
    result = live_gate.check_promotion(
        tmp_path,
        venue=GRANTED_VENUE,
        pair=GRANTED_PAIR,
        revision_id="rev-abc",
        env=_enable_env(),
        now=NOW + 1,
    )
    assert result.code == live_gate.CODE_KILL_SWITCH


def test_check_promotion_requires_nonempty_revision_id(tmp_path: Path) -> None:
    _write_valid_auth(tmp_path)
    result = live_gate.check_promotion(
        tmp_path,
        venue=GRANTED_VENUE,
        pair=GRANTED_PAIR,
        revision_id="",
        env=_enable_env(),
        now=NOW,
    )
    assert result.code == live_gate.CODE_LIVE_NOT_AUTHORIZED
    assert "revision_id" in result.message


# ---------------------------------------------------------------------------
# Test 10: live_status shape under three states.
# ---------------------------------------------------------------------------


def test_live_status_shape_with_no_files(tmp_path: Path) -> None:
    result = live_gate.live_status(tmp_path, env={}, now=NOW)
    assert result == {
        "schema_version": "1",
        "live_enabled": False,
        "authorized": [],
        "kill_switch": {"engaged": False, "reason": None, "engaged_at": None},
        "promotion_available": False,
        "promotion_code": live_gate.CODE_PROMOTION_DEFERRED,
    }


def test_live_status_shape_with_grant(tmp_path: Path) -> None:
    _write_valid_auth(tmp_path)
    result = live_gate.live_status(tmp_path, env=_enable_env(), now=NOW)
    assert result["schema_version"] == "1"
    assert result["live_enabled"] is True
    assert result["authorized"] == [{"venue": GRANTED_VENUE, "pair": GRANTED_PAIR}]
    assert result["kill_switch"] == {
        "engaged": False,
        "reason": None,
        "engaged_at": None,
    }
    assert result["promotion_available"] is False
    assert result["promotion_code"] == live_gate.CODE_PROMOTION_DEFERRED


def test_live_status_shape_with_kill_engaged(tmp_path: Path) -> None:
    live_gate.engage_kill(tmp_path, reason="halt", now=NOW)
    result = live_gate.live_status(tmp_path, env=_enable_env(), now=NOW + 1)
    assert result["kill_switch"] == {
        "engaged": True,
        "reason": "halt",
        "engaged_at": NOW,
    }
    assert result["live_enabled"] is True


# ---------------------------------------------------------------------------
# Test 11: auth file is read-only for the product. bytes + mtime unchanged.
# ---------------------------------------------------------------------------


def test_auth_file_unchanged_when_present_and_every_function_invoked(
    tmp_path: Path,
) -> None:
    auth_file = live_gate.auth_path(tmp_path)
    original_bytes = (
        b'{"schema_version":"1","granted_by":"operator",'
        b'"expires_at":1893456000,"grants":[{"venue":"kraken","pair":"BTC/USD"}]}'
    )
    auth_file.write_bytes(original_bytes)
    original_mtime_ns = auth_file.stat().st_mtime_ns

    # Exercise every public function.
    live_gate.auth_path(tmp_path)
    live_gate.kill_path(tmp_path)
    live_gate.read_authorization(tmp_path, now=NOW)
    live_gate.kill_state(tmp_path)
    live_gate.engage_kill(tmp_path, reason="engage-probe", now=NOW)
    live_gate.release_kill(tmp_path)
    live_gate.check_live_send(
        tmp_path,
        venue=GRANTED_VENUE,
        pair=GRANTED_PAIR,
        env=_enable_env(),
        now=NOW,
    )
    live_gate.check_promotion(
        tmp_path,
        venue=GRANTED_VENUE,
        pair=GRANTED_PAIR,
        revision_id="rev-abc",
        env=_enable_env(),
        now=NOW,
    )
    live_gate.live_status(tmp_path, env=_enable_env(), now=NOW)

    assert auth_file.read_bytes() == original_bytes
    assert auth_file.stat().st_mtime_ns == original_mtime_ns


def test_auth_file_not_created_when_absent_and_every_function_invoked(
    tmp_path: Path,
) -> None:
    assert not live_gate.auth_path(tmp_path).exists()

    live_gate.read_authorization(tmp_path, now=NOW)
    live_gate.kill_state(tmp_path)
    live_gate.engage_kill(tmp_path, reason="engage-probe", now=NOW)
    live_gate.release_kill(tmp_path)
    live_gate.check_live_send(
        tmp_path,
        venue=GRANTED_VENUE,
        pair=GRANTED_PAIR,
        env=_enable_env(),
        now=NOW,
    )
    live_gate.check_promotion(
        tmp_path,
        venue=GRANTED_VENUE,
        pair=GRANTED_PAIR,
        revision_id="rev-abc",
        env=_enable_env(),
        now=NOW,
    )
    live_gate.live_status(tmp_path, env=_enable_env(), now=NOW)

    assert not live_gate.auth_path(tmp_path).exists()


# ---------------------------------------------------------------------------
# Test 12: AST tripwire + "live-authorization.json" appears nowhere else.
# ---------------------------------------------------------------------------


BANNED_TOP_LEVEL = {
    "krellbot.venues",
    "krellbot.cli",
    "krellbot.run",
    "krellbot.api",
    "urllib",
    "http",
    "socket",
    "requests",
    "httpx",
    "ssl",
}


def _check_import_name(name: str) -> None:
    if name in BANNED_TOP_LEVEL:
        raise AssertionError(f"banned import: {name}")
    top = name.split(".")[0]
    if top in BANNED_TOP_LEVEL:
        raise AssertionError(f"banned import: {name}")


def test_no_banned_imports_in_live_gate() -> None:
    source_path = Path(live_gate.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for sub in node.names:
                _check_import_name(sub.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            _check_import_name(node.module)


def test_live_authorization_filename_not_referenced_elsewhere() -> None:
    source_path = Path(live_gate.__file__).resolve()
    src_root = source_path.parent.parent  # src/krellbot/application -> src/krellbot
    literal = "live-authorization.json"
    offenders: list[str] = []
    for py_file in src_root.rglob("*.py"):
        if py_file.resolve() == source_path:
            continue
        text = py_file.read_text(encoding="utf-8", errors="replace")
        if literal in text:
            offenders.append(str(py_file))
    assert offenders == [], f"files referencing {literal!r}: {offenders}"
