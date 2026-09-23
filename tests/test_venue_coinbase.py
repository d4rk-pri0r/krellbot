"""Coinbase venue adapter tests.

All HTTP is fake. Tests inject `now_fn`/`nonce_fn` so JWT claims are
deterministic; signature verification uses the public key derived from the
same seed the test key was generated from.
"""

from __future__ import annotations

import base64
import json
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from fakes.fake_coinbase import FakeCoinbaseTransport

from krellbot.venues.base import WithdrawCapableError
from krellbot.venues.coinbase import (
    API_HOST,
    CoinbaseVenue,
    KeyError_,
    build_jwt,
    detect_key,
)

# ---- helpers --------------------------------------------------------------


def _make_ed25519_test_key() -> tuple[str, ed25519.Ed25519PrivateKey]:
    """Build a stable Ed25519 secret (base64 of seed||pubkey, 64 bytes)."""
    seed = b"\x01" * 32
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    pub_raw = priv.public_key().public_bytes_raw()
    secret_64 = base64.b64encode(seed + pub_raw).decode("ascii")
    return secret_64, priv


def _make_ec_test_key() -> tuple[str, ec.EllipticCurvePrivateKey]:
    """Build a stable EC P-256 key as PEM."""
    priv = ec.generate_private_key(ec.SECP256R1())
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return pem, priv


def _decoded_jwt(token: str) -> tuple[dict, dict, bytes]:
    """Split a JWT into (header, claims, signature_bytes). Verifies shape."""
    parts = token.split(".")
    assert len(parts) == 3, f"JWT must have 3 parts, got {len(parts)}"

    def _pad(s):
        return s + "=" * (-len(s) % 4)

    header = json.loads(base64.urlsafe_b64decode(_pad(parts[0])))
    claims = json.loads(base64.urlsafe_b64decode(_pad(parts[1])))
    sig = base64.urlsafe_b64decode(_pad(parts[2]))
    return header, claims, sig


def _jwt_for_record(call, priv: ed25519.Ed25519PrivateKey) -> tuple[dict, dict]:
    """Decode a recorded call's Bearer JWT and verify its Ed25519 signature."""
    auth = call.headers["authorization"]
    assert auth.startswith("Bearer ")
    token = auth.removeprefix("Bearer ")
    header, claims, sig = _decoded_jwt(token)
    header_b64, claims_b64 = token.split(".")[:2]
    signing_input = f"{header_b64}.{claims_b64}".encode("ascii")
    pub = priv.public_key()
    pub.verify(sig, signing_input)  # raises if tampered
    return header, claims


# ---- tests ---------------------------------------------------------------


def test_coinbase_duplicate_coid_is_not_resent():
    """A second `place_entry_with_stop` with the same coid issues zero POSTs."""
    secret, _priv = _make_ed25519_test_key()
    transport = FakeCoinbaseTransport(
        post_responses=[
            {"success": True, "success_response": {"order_id": "ENT-1", "status": "FILLED"}},
            {"success": True, "success_response": {"order_id": "STP-1"}},
        ],
    )
    now = lambda: 1_700_000_000
    nonce = lambda: "aa" * 16
    venue = CoinbaseVenue(
        api_key_name="orgs/abc/keys/xyz",
        api_secret=secret,
        transport=transport,
        product_id="BTC-USD",
        now_fn=now,
        nonce_fn=nonce,
    )
    first = venue.place_entry_with_stop("coid-DUP", Decimal("0.1"), Decimal(100), pair="BTC-USD")
    post_count_after_first = len([c for c in transport.calls if c.method == "POST"])
    assert post_count_after_first == 2

    second = venue.place_entry_with_stop("coid-DUP", Decimal("0.1"), Decimal(100), pair="BTC-USD")
    post_count_total = len([c for c in transport.calls if c.method == "POST"])
    assert post_count_total == 2, "duplicate coid must not be resent"
    assert first.id == second.id
    assert first.stop_price == second.stop_price


def test_coinbase_stop_placed_after_fill():
    """Entry first, then a stop with `STOP_DIRECTION_STOP_DOWN` and limit = 0.995*stop."""
    secret, priv = _make_ed25519_test_key()
    transport = FakeCoinbaseTransport(
        post_responses=[
            {"success": True, "success_response": {"order_id": "ENT-9", "status": "FILLED"}},
            {"success": True, "success_response": {"order_id": "STP-9"}},
        ],
    )
    venue = CoinbaseVenue(
        api_key_name="orgs/abc/keys/xyz",
        api_secret=secret,
        transport=transport,
        product_id="BTC-USD",
        now_fn=lambda: 1_700_000_000,
        nonce_fn=lambda: "bb" * 16,
    )

    ref = venue.place_entry_with_stop("coid-FILL", Decimal("0.5"), Decimal(30000), pair="BTC-USD")
    posts = [c for c in transport.calls if c.method == "POST"]
    assert len(posts) == 2

    entry_body = posts[0].body
    stop_body = posts[1].body

    assert entry_body["product_id"] == "BTC-USD"
    assert entry_body["side"] == "BUY"
    assert entry_body["client_order_id"] == "coid-FILL"
    assert entry_body["order_configuration"]["market_market_ioc"]["base_size"] == "0.50000000"

    stop_cfg = stop_body["order_configuration"]["stop_limit_stop_limit_gtc"]
    assert stop_body["client_order_id"] == "coid-FILL_stop"
    assert stop_body["side"] == "SELL"
    assert stop_cfg["stop_direction"] == "STOP_DIRECTION_STOP_DOWN"
    assert Decimal(stop_cfg["stop_price"]) == Decimal("30000.00000")
    # 0.005 buffer; 30000 * 0.995 = 29850.
    assert Decimal(stop_cfg["limit_price"]) == Decimal("29850.00000")
    assert stop_cfg["base_size"] == "0.50000000"
    assert ref.stop_price == Decimal("30000.00000")

    # Verify each call's JWT bears the correct method/uri/host claims.
    for call, method in zip(posts, ("POST", "POST")):
        header, claims = _jwt_for_record(call, priv)
        assert header["alg"] == "EdDSA"
        assert header["typ"] == "JWT"
        assert header["kid"] == "orgs/abc/keys/xyz"
        assert header["nonce"] == "bb" * 16
        assert claims["iss"] == "cdp"
        assert claims["aud"] == ["cdp_service"]
        assert claims["nbf"] == 1_700_000_000
        assert claims["exp"] == claims["nbf"] + 120
        assert claims["uri"].startswith(method + " ")
        assert API_HOST in claims["uri"]


def test_coinbase_unfilled_entry_does_not_place_stop():
    secret, _priv = _make_ed25519_test_key()
    transport = FakeCoinbaseTransport(
        post_responses=[
            {"success": True, "success_response": {"order_id": "ENT-OPEN", "status": "OPEN"}},
            {"success": True, "success_response": {"order_id": "STP-SHOULD-NOT"}},
        ],
    )
    venue = CoinbaseVenue(
        api_key_name="orgs/abc/keys/xyz",
        api_secret=secret,
        transport=transport,
        product_id="BTC-USD",
        now_fn=lambda: 1_700_000_000,
        nonce_fn=lambda: "cc" * 16,
    )
    with pytest.raises(RuntimeError, match="not filled"):
        venue.place_entry_with_stop("coid-OPEN", Decimal("0.5"), Decimal(30000), pair="BTC-USD")
    posts = [c for c in transport.calls if c.method == "POST"]
    assert len(posts) == 1


def test_coinbase_can_transfer_key_refused():
    """key_permissions with can_transfer=true raises WithdrawCapableError."""
    secret, _priv = _make_ed25519_test_key()
    transport = FakeCoinbaseTransport(
        key_permissions=[
            {"scope": "view", "can_view": True, "can_transfer": False},
            {"scope": "trade", "can_trade": True, "can_transfer": False},
            {"scope": "transfer", "can_transfer": True},
        ],
    )
    venue = CoinbaseVenue(
        api_key_name="orgs/abc/keys/xyz",
        api_secret=secret,
        transport=transport,
        product_id="BTC-USD",
        now_fn=lambda: 1_700_000_000,
        nonce_fn=lambda: "cc" * 16,
    )
    with pytest.raises(WithdrawCapableError):
        venue.check_key()
    # The transport saw the call but the secret/key never appeared.
    for call in transport.calls:
        assert secret not in json.dumps(call.headers)
        assert "orgs/abc/keys/xyz" not in json.dumps(call.headers)


def test_detect_key_rejects_unknown_shape():
    with pytest.raises(KeyError_) as excinfo:
        detect_key("not-a-key-shape-anything")
    msg = str(excinfo.value)
    assert "not-a-key-shape-anything" not in msg


def test_detect_key_pem_must_be_ec():
    """A PEM of an unrelated key shape raises with no secret in the message."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    sentinel = "SENTINEL_PEM_BYTES_DO_NOT_LEAK"
    pem_with_sentinel = pem + f"# {sentinel}\n"
    with pytest.raises(KeyError_) as excinfo:
        detect_key(pem_with_sentinel)
    assert sentinel not in str(excinfo.value)


def test_build_jwt_ed25519_signs_and_verifies():
    """Round-trip: build_jwt produces a signature the matching public key verifies."""
    secret, priv = _make_ed25519_test_key()
    alg, key = detect_key(secret)
    token = build_jwt(
        alg,
        key,
        key_name="kid-1",
        nonce_hex="00" * 16,
        method="POST",
        host=API_HOST,
        path="/api/v3/brokerage/orders",
        now=1_700_000_000,
    )
    header, claims, sig = _decoded_jwt(token)
    assert header["alg"] == "EdDSA"
    assert header["typ"] == "JWT"
    assert header["kid"] == "kid-1"
    assert claims["sub"] == "kid-1"
    assert claims["iss"] == "cdp"
    assert claims["aud"] == ["cdp_service"]
    assert claims["nbf"] == 1_700_000_000
    assert claims["exp"] == 1_700_000_120
    assert claims["uri"] == f"POST {API_HOST}/api/v3/brokerage/orders"
    header_b64, claims_b64 = token.split(".")[:2]
    priv.public_key().verify(sig, f"{header_b64}.{claims_b64}".encode("ascii"))


def test_build_jwt_es256_signs_and_verifies():
    """Build a JWT with the EC PEM key and verify the signature with the matching public key."""
    pem, priv = _make_ec_test_key()
    alg, key = detect_key(pem)
    assert alg == "ES256"
    token = build_jwt(
        alg,
        key,
        key_name="kid-2",
        nonce_hex="11" * 16,
        method="GET",
        host=API_HOST,
        path="/api/v3/brokerage/accounts",
        now=1_700_000_100,
    )
    header, claims, sig = _decoded_jwt(token)
    assert header["alg"] == "ES256"
    assert claims["uri"] == f"GET {API_HOST}/api/v3/brokerage/accounts"
    header_b64, claims_b64 = token.split(".")[:2]
    pub = priv.public_key()
    pub.verify(sig, f"{header_b64}.{claims_b64}".encode("ascii"), ec.ECDSA(hashes.SHA256()))


def test_coinbase_rules_reads_product_minimums():
    secret, _priv = _make_ed25519_test_key()
    transport = FakeCoinbaseTransport(
        product={
            "product_id": "SUI-USD",
            "base_increment": "0.1",
            "quote_increment": "0.0001",
            "base_min_size": "5",
            "quote_min_size": "0.5",
            "price": "1",
        }
    )
    venue = CoinbaseVenue("orgs/abc/keys/xyz", secret, transport)
    rules = venue.rules("SUI-USD")
    assert rules.ordermin == Decimal(5)
    assert rules.costmin == Decimal("0.5")
    assert rules.lot_decimals == 1
    assert rules.price_decimals == 4


def test_coinbase_snapshot_sees_open_stop_and_cancel_is_pair_scoped():
    secret, _priv = _make_ed25519_test_key()
    transport = FakeCoinbaseTransport(
        orders={
            "orders": [
                {
                    "order_id": "STOP-BTC",
                    "product_id": "BTC-USD",
                    "side": "SELL",
                    "client_order_id": "c1_stop",
                    "status": "OPEN",
                    "order_configuration": {
                        "stop_limit_stop_limit_gtc": {
                            "base_size": "0.1",
                            "limit_price": "29000",
                            "stop_price": "30000",
                            "stop_direction": "STOP_DIRECTION_STOP_DOWN",
                        }
                    },
                },
                {
                    "order_id": "STOP-ETH",
                    "product_id": "ETH-USD",
                    "side": "SELL",
                    "client_order_id": "c2_stop",
                    "status": "OPEN",
                    "order_configuration": {
                        "stop_limit_stop_limit_gtc": {
                            "base_size": "1",
                            "limit_price": "2000",
                            "stop_price": "2100",
                            "stop_direction": "STOP_DIRECTION_STOP_DOWN",
                        }
                    },
                },
            ],
            "has_next": False,
        }
    )
    venue = CoinbaseVenue("orgs/abc/keys/xyz", secret, transport)
    truth = venue.snapshot()
    assert {o.id for o in truth.open_orders} == {"STOP-BTC", "STOP-ETH"}
    venue.cancel_stops("BTC-USD")
    cancels = [c for c in transport.calls if c.method == "POST" and c.url.endswith("/cancel")]
    assert len(cancels) == 1
    assert cancels[0].body["order_ids"] == ["STOP-BTC"]


def test_coinbase_duplicate_coid_survives_a_new_instance():
    secret, _priv = _make_ed25519_test_key()
    transport = FakeCoinbaseTransport(
        orders={
            "orders": [
                {
                    "order_id": "ENT-OLD",
                    "product_id": "BTC-USD",
                    "side": "BUY",
                    "client_order_id": "coid-OLD",
                    "status": "FILLED",
                    "filled_size": "0.1",
                }
            ],
            "has_next": False,
        }
    )
    venue = CoinbaseVenue("orgs/abc/keys/xyz", secret, transport, product_id="BTC-USD")
    ref = venue.place_entry_with_stop("coid-OLD", Decimal("0.1"), Decimal(100), pair="BTC-USD")
    assert ref.id == "ENT-OLD"
    assert not any(c.method == "POST" for c in transport.calls)


def test_coinbase_view_only_key_is_not_trade():
    secret, _priv = _make_ed25519_test_key()
    transport = FakeCoinbaseTransport(
        key_permissions=[{"scope": "view", "can_view": True, "can_trade": False, "can_transfer": False}]
    )
    venue = CoinbaseVenue("orgs/abc/keys/xyz", secret, transport)
    perms = venue.check_key()
    assert perms.can_trade is False
    assert perms.can_withdraw is False
