"""NS08a — strategy drafts (post, edit, validate, arm-by-revision_id).

Tests-first. The draft routes and ``StrategyDraftService`` do not exist
before this NS lands; the import lines below must fail with
``ModuleNotFoundError`` in the RED phase.

Behavior under test (brief: ``.superpowers/sdd/krellbot-2027/NS08/NS08a-brief.md``):

  1. The canonical revision id is the sha256 of UTF-8 JSON with sorted
     keys and ``(",", ":")`` separators. Editor-only keys named ``editor``
     are excluded from the hash and from the stored bytes.
  2. ``POST /api/v1/strategies/drafts`` carries the same session, Origin,
     Host, and ``X-Krellbot-CSRF`` gates as ``POST /api/v1/commands``.
     It returns ``strategy_id``, ``revision_id``, and ``state: "draft"``.
  3. ``PUT /api/v1/strategies/drafts/{revision_id}`` edits that draft
     into a new revision. The parent revision's bytes do not change.
     If the parent state is ``deployed``, the edit still creates a new
     draft and leaves the deployed bytes unchanged.
  4. ``POST /api/v1/strategies/drafts/{revision_id}/validate`` calls
     ``krellbot.pack.lint.check``. A clean pack becomes ``validated``;
     errors are returned including a field path. Do not re-implement
     lint.
  5. A legacy pack (``id`` + ``public_label`` only) stores as a draft
     but validation does not mark it runnable. ``paper.arm`` of that
     revision returns 403 and does not change ``config.json``.
  6. An invalid draft cannot arm. A validated draft can be armed through
     the existing ``paper.arm`` payload by ``revision_id`` without
     rewriting the draft file.
  7. Storing the same revision JSON twice returns the same
     ``revision_id``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.test_ns06_api import (
    TEST_PORT,
    _build_app,
    _default_origin_header,
    _post_json,
    _session_from_cookies,
    asgi_call,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _valid_pack_dict() -> dict:
    """Return the same DSL object the NS06a tests use."""

    return {
        "schema_version": 1,
        "id": "trend-follow",
        "version": "1.0.0",
        "label": "Trend follow",
        "author": "krellbot ns08a tests",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }


def _bad_pack_dict() -> dict:
    """A pack that fails lint (operand is not a price field or indicator)."""

    pack = _valid_pack_dict()
    pack["entry"] = ["close", ">", "ghost_indicator"]
    return pack


def _legacy_pack_dict() -> dict:
    """A legacy pack: id + public_label, no schema_version."""

    return {
        "id": "old-style",
        "public_label": "Old Reliable",
        "rule": "Plain English.",
        "timeframe": "1h",
    }


def _auth_headers(csrf: str, session: str, port: int = TEST_PORT) -> list[tuple[str, str]]:
    return [
        ("Origin", f"http://127.0.0.1:{port}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]


def _bootstrap_via_test(app) -> tuple[str, str]:
    """Bootstrap a fresh app and return (csrf, session_value)."""

    token = app.state.krellbot.bootstrap_token
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    assert status == 200, (status, body)
    csrf = json.loads(body)["csrf_token"]
    session = _session_from_cookies(cookies)
    return csrf, session


def _post_draft(
    app,
    csrf: str,
    session: str,
    pack: dict,
) -> tuple[int, bytes]:
    body = json.dumps({"pack": pack}).encode("utf-8")
    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _hdrs, resp_body, _cookies = asgi_call(
        app, method="POST", path="/api/v1/strategies/drafts", body=body, headers=headers
    )
    return status, resp_body


def _put_draft(
    app,
    csrf: str,
    session: str,
    revision_id: str,
    pack: dict,
) -> tuple[int, bytes]:
    body = json.dumps({"pack": pack}).encode("utf-8")
    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _hdrs, resp_body, _cookies = asgi_call(
        app,
        method="PUT",
        path=f"/api/v1/strategies/drafts/{revision_id}",
        body=body,
        headers=headers,
    )
    return status, resp_body


def _validate_draft(app, csrf: str, session: str, revision_id: str) -> tuple[int, bytes]:
    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", "2"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _hdrs, resp_body, _cookies = asgi_call(
        app,
        method="POST",
        path=f"/api/v1/strategies/drafts/{revision_id}/validate",
        body=b"{}",
        headers=headers,
    )
    return status, resp_body


def _canonical_hash(pack: dict) -> str:
    """Compute the canonical hash the service must use.

    Sorts keys, strips ``editor``, encodes UTF-8 with (",", ":")
    separators, sha256s the bytes.
    """

    cleaned = {k: v for k, v in pack.items() if k != "editor"}
    canonical = json.dumps(cleaned, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 1. canonical revision id — sha256 of canonical JSON, editor excluded
# ---------------------------------------------------------------------------


def test_canonical_revision_id_is_sha256_of_sorted_key_json(home: Path) -> None:
    """The revision id matches sha256 of UTF-8 JSON with sorted keys and
    ``(",", ":")`` separators. Editor-only keys are excluded."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)

    pack = _valid_pack_dict()
    pack["editor"] = {"cursor": 42, "pane": "raw"}
    expected = _canonical_hash(pack)
    assert len(expected) == 64

    status, body = _post_draft(app, csrf, session, pack)
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["revision_id"] == expected
    assert decoded["schema_version"] == "1"


def test_editor_keys_are_excluded_from_stored_bytes(home: Path) -> None:
    """Editor layout state is not persisted on disk with the draft."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)

    pack = _valid_pack_dict()
    pack["editor"] = {"cursor": 42}

    status, body = _post_draft(app, csrf, session, pack)
    assert status == 200, body
    revision_id = json.loads(body)["revision_id"]

    from krellbot.application.strategy import StrategyDraftService

    service = StrategyDraftService(home=home)
    snap = service.get(revision_id)
    assert snap is not None
    stored_pack = snap["pack"]
    assert "editor" not in stored_pack
    assert stored_pack["id"] == pack["id"]


def test_same_revision_json_stored_twice_returns_same_revision_id(home: Path) -> None:
    """Two POSTs of identical canonical JSON return identical revision ids."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)

    pack = _valid_pack_dict()
    pack["editor"] = {"pane": "form"}

    status1, body1 = _post_draft(app, csrf, session, pack)
    assert status1 == 200, body1
    rev1 = json.loads(body1)["revision_id"]

    status2, body2 = _post_draft(app, csrf, session, pack)
    assert status2 == 200, body2
    rev2 = json.loads(body2)["revision_id"]

    assert rev1 == rev2


# ---------------------------------------------------------------------------
# 2. POST /api/v1/strategies/drafts — gates and response
# ---------------------------------------------------------------------------


def test_post_drafts_requires_full_auth(home: Path) -> None:
    """POST without session + Origin + CSRF is 403 even on the drafts route."""

    app = _build_app(home)
    body = json.dumps({"pack": _valid_pack_dict()}).encode("utf-8")
    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    status, _hdrs, _body, _cookies = asgi_call(
        app, method="POST", path="/api/v1/strategies/drafts", body=body, headers=headers
    )
    assert status == 403, status


def test_post_drafts_requires_loopback_origin(home: Path) -> None:
    """POST with a non-loopback Origin is 403 even when the session is good."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)

    body = json.dumps({"pack": _valid_pack_dict()}).encode("utf-8")
    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
        ("Origin", "http://evil.example.com"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _hdrs, _body, _cookies = asgi_call(
        app, method="POST", path="/api/v1/strategies/drafts", body=body, headers=headers
    )
    assert status == 403, status


def test_post_drafts_requires_csrf_header(home: Path) -> None:
    """POST with the right session + Origin but the wrong CSRF is 403."""

    app = _build_app(home)
    _csrf, session = _bootstrap_via_test(app)

    body = json.dumps({"pack": _valid_pack_dict()}).encode("utf-8")
    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", "wrong-csrf"),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _hdrs, _body, _cookies = asgi_call(
        app, method="POST", path="/api/v1/strategies/drafts", body=body, headers=headers
    )
    assert status == 403, status


def test_post_drafts_non_loopback_host_is_403(home: Path) -> None:
    """POST with a non-loopback Host is 403 before any route runs."""

    app = _build_app(home)
    body = json.dumps({"pack": _valid_pack_dict()}).encode("utf-8")
    headers = [
        ("Host", "evil.example.com"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    status, _hdrs, _body, _cookies = asgi_call(
        app, method="POST", path="/api/v1/strategies/drafts", body=body, headers=headers
    )
    assert status == 403, status


def test_post_drafts_returns_strategy_id_revision_id_and_state(home: Path) -> None:
    """A successful POST returns strategy_id, revision_id, state: 'draft'."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)

    status, body = _post_draft(app, csrf, session, _valid_pack_dict())
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["schema_version"] == "1"
    assert decoded["strategy_id"] == "trend-follow"
    assert decoded["state"] == "draft"
    assert len(decoded["revision_id"]) == 64


def test_post_drafts_bad_body_is_400(home: Path) -> None:
    """A POST whose body is not JSON or not a {pack: ...} dict is 400."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)
    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", "2"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _hdrs, _body, _cookies = asgi_call(
        app, method="POST", path="/api/v1/strategies/drafts", body=b"{}", headers=headers
    )
    assert status == 400, status

    bad = json.dumps(["not", "a", "dict"]).encode("utf-8")
    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(bad))),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _hdrs, _body, _cookies = asgi_call(
        app, method="POST", path="/api/v1/strategies/drafts", body=bad, headers=headers
    )
    assert status == 400, status


# ---------------------------------------------------------------------------
# 3. PUT edit — new revision, parent bytes preserved, deployed-parent safe
# ---------------------------------------------------------------------------


def _create_revision(app, csrf: str, session: str, pack: dict) -> dict:
    """Helper: POST a draft and assert 200; return the decoded response."""

    status, body = _post_draft(app, csrf, session, pack)
    assert status == 200, body
    return json.loads(body)


def test_put_drafts_creates_new_revision_and_preserves_parent_bytes(home: Path) -> None:
    """PUT edits a draft into a new revision. The parent's stored bytes
    do not change."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)

    parent = _create_revision(app, csrf, session, _valid_pack_dict())
    parent_revision_id = parent["revision_id"]

    from krellbot.application.strategy import StrategyDraftService

    service = StrategyDraftService(home=home)
    parent_bytes_before = service.canonical_bytes(parent_revision_id)

    edited = _valid_pack_dict()
    edited["label"] = "Trend follow (edited)"
    status, body = _put_draft(app, csrf, session, parent_revision_id, edited)
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["revision_id"] != parent_revision_id
    assert decoded["strategy_id"] == "trend-follow"
    assert decoded["state"] == "draft"
    assert decoded["parent_revision_id"] == parent_revision_id

    parent_bytes_after = service.canonical_bytes(parent_revision_id)
    assert parent_bytes_before == parent_bytes_after


def test_put_drafts_unknown_revision_is_404(home: Path) -> None:
    """PUT against an unknown revision id is 404."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)
    status, body = _put_draft(app, csrf, session, "0" * 64, _valid_pack_dict())
    assert status == 404, (status, body)


def test_put_drafts_against_deployed_parent_creates_a_new_draft(home: Path) -> None:
    """Editing a deployed revision creates a new draft and the on-disk
    config bytes are not touched."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)

    parent = _create_revision(app, csrf, session, _valid_pack_dict())
    parent_revision_id = parent["revision_id"]

    _status, _validate_body = _validate_draft(app, csrf, session, parent_revision_id)

    arm_payload = {
        "schema_version": "1",
        "command": "paper.arm",
        "correlation_id": "ns08a-arm",
        "expected_revision": None,
        "payload": {
            "revision_id": parent_revision_id,
            "venue": "kraken",
            "paper_balance": "1000",
        },
    }
    auth = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _h, body, _c = _post_json(app, "/api/v1/commands", arm_payload, headers=auth)
    assert status == 200, (status, body)
    assert json.loads(body)["code"] == "armed"

    deployed_on_disk = (home / "config.json").read_bytes()

    edited = _valid_pack_dict()
    edited["label"] = "Trend follow (edit of deployed)"
    status, body = _put_draft(app, csrf, session, parent_revision_id, edited)
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["state"] == "draft"
    assert decoded["parent_revision_id"] == parent_revision_id

    assert (home / "config.json").read_bytes() == deployed_on_disk


# ---------------------------------------------------------------------------
# 4. validate — uses pack.lint.check; clean → validated; errors returned
# ---------------------------------------------------------------------------


def test_validate_clean_pack_returns_state_validated(home: Path) -> None:
    """Validating a clean pack returns state 'validated'."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)
    rev = _create_revision(app, csrf, session, _valid_pack_dict())
    status, body = _validate_draft(app, csrf, session, rev["revision_id"])
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["state"] == "validated"
    assert decoded["revision_id"] == rev["revision_id"]
    assert decoded["schema_version"] == "1"


def test_validate_invalid_pack_returns_lint_errors_with_field(home: Path) -> None:
    """Validating a pack that fails lint returns the lint errors including
    a field path."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)
    rev = _create_revision(app, csrf, session, _bad_pack_dict())
    status, body = _validate_draft(app, csrf, session, rev["revision_id"])
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["state"] == "draft"
    assert decoded["revision_id"] == rev["revision_id"]
    errors = decoded.get("errors") or []
    assert errors, decoded
    assert any(e.get("field") for e in errors), errors


def test_validate_unknown_revision_is_404(home: Path) -> None:
    """Validating a revision that does not exist is 404."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)
    status, body = _validate_draft(app, csrf, session, "1" * 64)
    assert status == 404, (status, body)


# ---------------------------------------------------------------------------
# 5. legacy pack — stored as draft, validate does not mark runnable
# ---------------------------------------------------------------------------


def test_legacy_pack_stores_as_draft_but_does_not_become_validated(home: Path) -> None:
    """A {id, public_label} legacy pack stores, but validation does not
    mark it runnable. (state stays 'draft'; an explicit runnable flag is
    not flipped to True.)"""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)

    pack = _legacy_pack_dict()
    rev = _create_revision(app, csrf, session, pack)
    assert rev["state"] == "draft"

    status, body = _validate_draft(app, csrf, session, rev["revision_id"])
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["state"] == "draft"
    assert decoded.get("runnable") is False


def test_legacy_draft_arm_is_403_and_leaves_config(home: Path) -> None:
    """``paper.arm`` by ``revision_id`` for a legacy draft is 403 and the
    on-disk config is not touched."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)

    rev = _create_revision(app, csrf, session, _legacy_pack_dict())

    arm_payload = {
        "schema_version": "1",
        "command": "paper.arm",
        "correlation_id": "ns08a-legacy-arm",
        "expected_revision": None,
        "payload": {
            "revision_id": rev["revision_id"],
            "venue": "kraken",
            "paper_balance": "1000",
        },
    }
    auth = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]
    before = _config_bytes(home)
    status, _h, _body, _c = _post_json(app, "/api/v1/commands", arm_payload, headers=auth)
    assert status == 403, status
    assert _config_bytes(home) == before


# ---------------------------------------------------------------------------
# 6. arm — invalid draft cannot arm; validated can arm by revision_id
# ---------------------------------------------------------------------------


def _config_bytes(home: Path) -> bytes:
    config_path = home / "config.json"
    if not config_path.exists():
        return b""
    return config_path.read_bytes()


def _arm_by_rev(app, csrf: str, session: str, revision_id: str) -> tuple[int, bytes]:
    payload = {
        "schema_version": "1",
        "command": "paper.arm",
        "correlation_id": "ns08a-arm-by-rev",
        "expected_revision": None,
        "payload": {
            "revision_id": revision_id,
            "venue": "kraken",
            "paper_balance": "1000",
        },
    }
    auth = _auth_headers(csrf, session)
    status, _h, body, _c = _post_json(app, "/api/v1/commands", payload, headers=auth)
    return status, body


def test_invalid_draft_cannot_arm(home: Path) -> None:
    """An invalid (lint-failing) draft is not armable through the
    paper.arm payload, even when addressed by revision_id."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)

    rev = _create_revision(app, csrf, session, _bad_pack_dict())
    status, body = _arm_by_rev(app, csrf, session, rev["revision_id"])
    assert status in (403, 422), (status, body)
    assert not (home / "config.json").exists()


def test_validated_draft_can_arm_via_revision_id_without_rewriting_draft(home: Path) -> None:
    """A validated draft is armable by revision_id. The draft file is
    not rewritten and the on-disk config is updated to reflect the
    canonical pack bytes."""

    from krellbot.application.strategy import StrategyDraftService

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)

    pack = _valid_pack_dict()
    rev = _create_revision(app, csrf, session, pack)
    status, body = _validate_draft(app, csrf, session, rev["revision_id"])
    assert status == 200, body
    assert json.loads(body)["state"] == "validated"

    service = StrategyDraftService(home=home)
    pre_arm_bytes = service.canonical_bytes(rev["revision_id"])
    pre_arm_mtime = (service.revision_path(rev["revision_id"])).stat().st_mtime_ns

    status, body = _arm_by_rev(app, csrf, session, rev["revision_id"])
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded["code"] == "armed"

    # On-disk config reflects the draft pack identity and the canonical hash.
    on_disk = json.loads((home / "config.json").read_text())
    armed = next(a for a in on_disk["armed"] if a["venue"] == "kraken")
    assert armed["pack_id"] == "trend-follow"

    # The draft file on disk was not rewritten just because we armed it.
    post_arm_bytes = service.canonical_bytes(rev["revision_id"])
    post_arm_mtime = (service.revision_path(rev["revision_id"])).stat().st_mtime_ns
    assert pre_arm_bytes == post_arm_bytes
    assert pre_arm_mtime == post_arm_mtime


def test_failed_arm_does_not_mark_draft_deployed(home: Path) -> None:
    """A refused paper arm must not flip a validated draft to deployed."""

    from krellbot.application.strategy import StrategyDraftService

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)
    rev = _create_revision(app, csrf, session, _valid_pack_dict())
    status, body = _validate_draft(app, csrf, session, rev["revision_id"])
    assert status == 200, body

    payload = {
        "schema_version": "1",
        "command": "paper.arm",
        "payload": {
            "revision_id": rev["revision_id"],
            "venue": "not-a-venue",
            "paper_balance": "1000",
        },
    }
    status, _h, body, _c = _post_json(app, "/api/v1/commands", payload, headers=_auth_headers(csrf, session))
    assert status == 200, (status, body)
    assert json.loads(body)["ok"] is False
    assert not (home / "config.json").exists()
    snap = StrategyDraftService(home=home).get(rev["revision_id"])
    assert snap is not None
    assert snap["state"] == "validated", snap


def test_arm_by_revision_id_requires_validated_state(home: Path) -> None:
    """After create, an unvalidated draft is not armable; arm must
    follow validation."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)

    rev = _create_revision(app, csrf, session, _valid_pack_dict())
    status, body = _arm_by_rev(app, csrf, session, rev["revision_id"])
    assert status in (403, 422), (status, body)
    assert not (home / "config.json").exists()


# ---------------------------------------------------------------------------
# 7. Drafts are not the armed-pack config and not a file under packs/
# ---------------------------------------------------------------------------


def test_drafts_live_under_home_not_under_packs(home: Path) -> None:
    """The draft store lives under <home>/drafts and never writes
    anything under <home>/packs (which is the deployed-pack location)."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)

    pack = _valid_pack_dict()
    rev = _create_revision(app, csrf, session, pack)

    drafts_root = home / "drafts"
    packs_root = home / "packs"
    assert drafts_root.exists(), sorted(p.rf for p in home.rglob("*"))
    assert rev["revision_id"] in {p.stem for p in drafts_root.rglob("*.json")}
    # Nothing leaked into <home>/packs.
    assert not packs_root.exists() or not list(packs_root.glob("*.json"))
