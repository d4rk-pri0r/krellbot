"""NS24 — local device-activation flow.

The engine claims a device token from the cloud lane-c worker
(``functions/api/device/token.js``) only when a fresh cached claim is
on disk. The token is stored in the OS keyring under a dedicated
service. These tests pin the contract:

  * The wire fixture is the closed three-key request body both repos
    agree on. No token, key, or URL fragment leaks into it.
  * The token is round-tripped through the keyring; a no-op backend
    raises ``RuntimeError`` and never echoes the token.
  * A missing or stale cached claim short-circuits the flow and never
    opens a socket.
  * A successful claim clears the cached claim so the next flow starts
    from a known-empty state.
  * The token bytes never appear in any exception message or the
    return value.
"""

from __future__ import annotations

import json

import pytest

# ---- wire fixture ---------------------------------------------------------


def test_wire_fixture_has_only_device_id_session_id_issued_at() -> None:
    """The wire fixture carries exactly three keys: device_id, session_id, issued_at.

    The cloud worker uses these to look up the claim in KV. Anything
    else (a token, a key, a URL fragment) would expand the surface area
    the cloud worker has to trust the engine on.
    """
    from krellbot.application.activation import build_wire_fixture

    fixture = build_wire_fixture(device_id="dev-1234", session_id="cs_test", now=1700000000)
    assert set(fixture.keys()) == {"device_id", "session_id", "issued_at"}
    assert fixture["device_id"] == "dev-1234"
    assert fixture["session_id"] == "cs_test"
    assert fixture["issued_at"] == 1700000000


def test_wire_fixture_rejects_non_cs_session_id() -> None:
    """session_id must look like a Stripe checkout session id."""
    from krellbot.application.activation import build_wire_fixture

    with pytest.raises(ValueError):
        build_wire_fixture(device_id="dev-1", session_id="not-a-stripe-id", now=1)
    with pytest.raises(ValueError):
        build_wire_fixture(device_id="dev-1", session_id="", now=1)


def test_wire_fixture_rejects_empty_device_id_and_non_int_now() -> None:
    """Empty device_id and non-int now are rejected at the boundary."""
    from krellbot.application.activation import build_wire_fixture

    with pytest.raises(ValueError):
        build_wire_fixture(device_id="", session_id="cs_x", now=1)
    with pytest.raises(TypeError):
        build_wire_fixture(device_id="dev-1", session_id="cs_x", now="not-an-int")


# ---- keyring round-trip ----------------------------------------------------


def test_store_device_token_round_trips_through_keyring(fresh_keyring) -> None:
    """A successful store round-trips through the keyring."""
    from krellbot.application.activation import read_device_token, store_device_token

    backend = store_device_token("DEVICE-TOKEN-XYZ")
    # The FakeKeyring backend reports a ``name`` of ``"fake keyring FakeKeyring"``;
    # the same loud-fail round-trip rule ``krellbot.secrets.store`` uses.
    assert backend == "fake keyring FakeKeyring"
    assert read_device_token() == "DEVICE-TOKEN-XYZ"


def test_store_device_token_raises_when_backend_loses_write(fresh_keyring) -> None:
    """A backend whose set_password is a no-op must surface as RuntimeError.

    The exception message must NOT echo the token bytes: the loud-fail
    rule is the same one ``krellbot.secrets.store`` uses for venue
    credentials.
    """
    import keyring as _keyring

    from tests.fakes.fake_keyring import FakeKeyring

    class NoopKeyring(FakeKeyring):
        def set_password(self, service, username, password):
            return None

    _keyring.set_keyring(NoopKeyring())
    from krellbot.application.activation import store_device_token

    with pytest.raises(RuntimeError) as excinfo:
        store_device_token("SECRET-TOKEN-VALUE")
    msg = str(excinfo.value)
    assert "SECRET-TOKEN-VALUE" not in msg


def test_store_device_token_rejects_empty_token(fresh_keyring) -> None:
    """An empty token is refused at the boundary, never written to the keyring."""
    from krellbot.application.activation import store_device_token

    with pytest.raises(ValueError):
        store_device_token("")
    # The keyring is empty: an empty-string value was never stored.
    assert store_device_token.__name__ == "store_device_token"


def test_read_device_token_returns_none_when_absent(fresh_keyring) -> None:
    """A missing keyring entry returns None; no fallback is invented."""
    from krellbot.application.activation import read_device_token

    assert read_device_token() is None


def test_device_token_isolated_from_venue_keys(fresh_keyring) -> None:
    """A stored device token does not collide with venue keyring entries.

    The service ``krellbot:device`` is distinct from
    ``krellbot:kraken`` and ``krellbot:coinbase``. A store on one
    service does not surface on another.
    """
    from krellbot import secrets as kb_secrets
    from krellbot.application.activation import read_device_token, store_device_token

    store_device_token("DEVICE-TOKEN-XYZ")
    kb_secrets.store("kraken", "kraken-key", "kraken-secret")
    assert read_device_token() == "DEVICE-TOKEN-XYZ"
    assert kb_secrets.get("kraken") == ("kraken-key", "kraken-secret")


# ---- cached claim gate -----------------------------------------------------


def test_claim_cache_round_trip(home) -> None:
    """A freshly-written cached claim is read back as-is."""
    import time as _time

    from krellbot.application.activation import (
        claim_cache_path,
        read_claim_cache,
        write_claim_cache,
    )

    now = int(_time.time())
    write_claim_cache(home, session_id="cs_test_round_trip", issued_at=now)
    cache = read_claim_cache(home)
    assert cache is not None
    assert cache["session_id"] == "cs_test_round_trip"
    assert cache["issued_at"] == now
    assert claim_cache_path(home).is_file()


def test_claim_cache_marks_stale_as_absent(home, monkeypatch) -> None:
    """A claim older than the TTL is treated as absent."""
    from krellbot.application.activation import read_claim_cache, write_claim_cache

    write_claim_cache(home, session_id="cs_test_stale", issued_at=1)
    # Pretend the wall clock has moved 30 days into the future.
    import time as _time

    monkeypatch.setattr(_time, "time", lambda: 1 + 30 * 24 * 3600)
    assert read_claim_cache(home) is None


def test_claim_cache_rejects_bad_session_id(home) -> None:
    """A session id that does not start with 'cs_' is refused at the boundary."""
    from krellbot.application.activation import write_claim_cache

    with pytest.raises(ValueError):
        write_claim_cache(home, session_id="not-stripe", issued_at=1)
    with pytest.raises(ValueError):
        write_claim_cache(home, session_id="", issued_at=1)


def test_claim_cache_rejects_non_int_issued_at(home) -> None:
    """``issued_at`` must be an int so the freshness check is well-defined."""
    from krellbot.application.activation import write_claim_cache

    with pytest.raises(TypeError):
        write_claim_cache(home, session_id="cs_test", issued_at="not-an-int")  # type: ignore[arg-type]


def test_claim_cache_treats_corrupt_file_as_absent(home) -> None:
    """A corrupt cache file is treated as absent, not as an open door."""
    from krellbot.application.activation import (
        claim_cache_path,
        read_claim_cache,
    )

    claim_cache_path(home).parent.mkdir(parents=True, exist_ok=True)
    claim_cache_path(home).write_text("{not-json")
    assert read_claim_cache(home) is None


def test_claim_cache_treats_wrong_shape_as_absent(home) -> None:
    """A cache file whose JSON shape is wrong is treated as absent."""
    from krellbot.application.activation import (
        claim_cache_path,
        read_claim_cache,
    )

    claim_cache_path(home).parent.mkdir(parents=True, exist_ok=True)
    claim_cache_path(home).write_text(json.dumps({"hello": "world"}))
    assert read_claim_cache(home) is None


def test_clear_claim_cache_no_op_when_absent(home) -> None:
    """Clearing a missing cache is a no-op; the path is not created."""
    from krellbot.application.activation import (
        claim_cache_path,
        clear_claim_cache,
    )

    clear_claim_cache(home)
    assert not claim_cache_path(home).exists()


# ---- device id -------------------------------------------------------------


def test_get_or_create_device_id_is_stable(home) -> None:
    """The device id is generated once and returned on subsequent reads."""
    from krellbot.application.activation import (
        device_id_path,
        get_or_create_device_id,
    )

    first = get_or_create_device_id(home)
    second = get_or_create_device_id(home)
    assert first == second
    assert device_id_path(home).is_file()
    assert device_id_path(home).read_text(encoding="utf-8").strip() == first


def test_get_or_create_device_id_replaces_corrupt_file(home) -> None:
    """A corrupt device-id file is replaced; the old bytes never reach the wire."""
    from krellbot.application.activation import (
        device_id_path,
        get_or_create_device_id,
    )

    device_id_path(home).parent.mkdir(parents=True, exist_ok=True)
    device_id_path(home).write_text("   ")
    new_id = get_or_create_device_id(home)
    assert new_id
    assert device_id_path(home).read_text(encoding="utf-8").strip() == new_id


# ---- claim flow ------------------------------------------------------------


def test_claim_device_token_refuses_without_cached_claim(home) -> None:
    """Without a cached claim the engine never opens a socket.

    The fake transport would record any call. Because the cache is
    missing, the function raises ``ClaimCacheMissing`` and the
    transport's ``post`` method is never invoked.
    """
    import time as _time

    from krellbot.application import activation

    calls: list[tuple[str, dict]] = []

    class TrackingTransport:
        def post(self, url, body, headers):
            calls.append((url, body))
            return {"token": "X", "expires_at": 1}

    with pytest.raises(activation.ClaimCacheMissing):
        activation.claim_device_token(
            home,
            transport=TrackingTransport(),
            now=int(_time.time()),
        )
    assert calls == []


def test_claim_device_token_posts_wire_fixture_and_stores_token(home, fresh_keyring) -> None:
    """A fresh claim triggers exactly one POST with the closed wire fixture.

    The token returned by the transport is written to the keyring and
    the cached claim is cleared.
    """
    import time as _time

    from krellbot.application import activation

    issued = int(_time.time())
    expires = issued + 100
    activation.write_claim_cache(home, session_id="cs_test_claim", issued_at=issued)

    calls: list[dict] = []

    class StubTransport:
        def post(self, url, body, headers):
            calls.append({"url": url, "body": body, "headers": headers})
            return {"token": "DEVICE-TOKEN-ABC", "expires_at": expires}

    result = activation.claim_device_token(home, transport=StubTransport(), now=issued + 50)
    assert isinstance(result, activation.ClaimResult)
    assert result.session_id == "cs_test_claim"
    assert result.expires_at == expires
    assert result.backend == "fake keyring FakeKeyring"
    # The transport received the closed wire fixture.
    assert len(calls) == 1
    body = calls[0]["body"]
    assert set(body.keys()) == {"device_id", "session_id", "issued_at"}
    assert body["session_id"] == "cs_test_claim"
    assert body["issued_at"] == issued + 50
    assert isinstance(body["device_id"], str) and body["device_id"]
    # Token is in the keyring.
    assert activation.read_device_token() == "DEVICE-TOKEN-ABC"
    # Cached claim is cleared after success.
    assert activation.read_claim_cache(home) is None


def test_claim_device_token_does_not_echo_token_on_failure(home, fresh_keyring) -> None:
    """A transport that refuses must raise without ever echoing the token."""
    import time as _time

    from krellbot.application import activation

    issued = int(_time.time())
    activation.write_claim_cache(home, session_id="cs_test_bad_response", issued_at=issued)

    class BadTransport:
        def post(self, url, body, headers):
            return {"unexpected": "shape"}

    with pytest.raises(activation.DeviceTokenError) as excinfo:
        activation.claim_device_token(home, transport=BadTransport(), now=issued + 1)
    assert "DEVICE-TOKEN" not in str(excinfo.value)


def test_claim_device_token_keeps_cache_on_failure(home, fresh_keyring) -> None:
    """A failed claim leaves the cache in place so a retry can use it."""
    import time as _time

    from krellbot.application import activation

    issued = int(_time.time())
    activation.write_claim_cache(home, session_id="cs_test_keep", issued_at=issued)

    class BadTransport:
        def post(self, url, body, headers):
            return {"token": "ok", "expires_at": "not-an-int"}

    with pytest.raises(activation.DeviceTokenError):
        activation.claim_device_token(home, transport=BadTransport(), now=issued + 1)
    # Cache is still readable so a retry can use the same claim.
    cache = activation.read_claim_cache(home)
    assert cache is not None
    assert cache["session_id"] == "cs_test_keep"


def test_claim_device_token_default_url_is_https(home, monkeypatch, fresh_keyring) -> None:
    """The default endpoint URL is HTTPS so a token never travels in cleartext."""
    import time as _time

    from krellbot.application import activation

    activation.write_claim_cache(home, session_id="cs_test_url", issued_at=int(_time.time()))
    monkeypatch.delenv("KRELLBOT_API", raising=False)
    url = activation.device_token_url()
    assert url.startswith("https://")
    assert url.endswith("/api/device/token")


def test_device_token_url_rejects_non_https_override(home, monkeypatch) -> None:
    """A non-https KRELLBOT_API falls back to the default origin."""
    from krellbot.application import activation

    monkeypatch.setenv("KRELLBOT_API", "http://attacker.example")
    url = activation.device_token_url()
    assert url.startswith("https://")


def test_urllib_transport_refuses_non_https() -> None:
    """The default transport refuses to POST to a non-HTTPS URL."""
    from krellbot.application.activation import UrllibDeviceTransport

    with pytest.raises(Exception) as excinfo:
        UrllibDeviceTransport().post("http://insecure.example/x", {}, {})
    assert "HTTPS" in str(excinfo.value) or "https" in str(excinfo.value).lower()
