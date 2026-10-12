"""Starter pack catalogue — the loopback API contract and resource loading.

The route is ``GET /api/v1/packs/starters``. It serves the shipped
read-only catalogue of free educational starter packs from package
resources (``importlib.resources``), so a fresh user can pick a starter
in the Editor, save it through the existing draft flow, and get an
owned editable copy without hand-writing JSON.

The contract:

  1. The route exists in the OpenAPI document.
  2. It is a read endpoint gated by ``_gate_get`` exactly like
     ``GET /api/v1/packs``: session cookie required, non-loopback
     Origin 403, non-loopback Host 403, no CSRF header needed.
  3. The body is the frozen catalogue document:
     ``{"schema_version": "1", "catalogue_version": "1", "examples":
     [{"id", "label", "description", "pack"}, ...]}`` in manifest order.
  4. Every example pack is a real ordinary DSL pack: the existing
     validator (``krellbot.pack.lint.check``) passes it and it is not a
     legacy pack.
  5. The catalogue loads through real ``importlib.resources`` from a
     fresh interpreter-visible package — not from a filesystem path in
     the checkout.
  6. The route is read-only: no file under the app's home changes, and
     the returned packs are fresh objects (mutating one never mutates
     what the next call returns).
  7. The goal-linked capability: a starter ``pack`` POSTed through the
     existing draft route becomes a real owned revision that validates
     to ``runnable`` — the whole user path works.

Every test uses an isolated ``KRELLBOT_HOME`` via ``tmp_path``; no real
``~/.krellbot`` is read and no network transport is touched.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from krellbot.pack.lint import check, is_legacy
from krellbot.packs import catalogue as starter_catalogue
from tests.test_ns06_api import (
    TEST_PORT,
    _build_app,
    _post_json,
    asgi_call,
)

STARTERS_PATH = "/api/v1/packs/starters"
ROW_KEYS = {"id", "label", "description", "pack"}


# ---- helpers --------------------------------------------------------------


def _get_starters(
    app,
    *,
    headers: list[tuple[str, str]] | None = None,
    host: str | None = None,
) -> tuple[int, list[tuple[str, str]], bytes, list[str]]:
    """Issue ``GET /api/v1/packs/starters`` against ``app``."""

    base = [("Host", host or f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="GET", path=STARTERS_PATH, headers=base)


def _session_headers(app) -> list[tuple[str, str]]:
    """Bootstrap a session on ``app`` and return the gate-passing headers."""

    token = app.state.krellbot.bootstrap_token
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 200, (status, body)
    session = next(c for c in cookies if c.startswith("krellbot_session=")).split("=", 1)[1]
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session}"),
    ]


def _authenticated_doc(tmp_path: Path) -> dict:
    """Build an app over an isolated home and return the catalogue body."""

    app = _build_app(tmp_path)
    status, _h, body, _c = _get_starters(app, headers=_session_headers(app))
    assert status == 200, (status, body)
    return json.loads(body)


# ---- 1. the route exists --------------------------------------------------


def test_starters_route_exists(tmp_path: Path) -> None:
    """The route is registered on the versioned API surface."""

    app = _build_app(tmp_path)
    status, _h, body, _c = asgi_call(
        app,
        method="GET",
        path="/openapi.json",
        headers=[("Host", f"127.0.0.1:{TEST_PORT}")],
    )
    assert status == 200, status
    paths = json.loads(body).get("paths") or {}
    assert STARTERS_PATH in paths, sorted(paths.keys())


# ---- 2. session gate parity -----------------------------------------------


def test_starters_without_session_cookie_is_403(tmp_path: Path) -> None:
    """No session cookie → 403, the same gate as every other read route."""

    app = _build_app(tmp_path)
    status, _h, body, _c = _get_starters(
        app,
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, (status, body)
    assert json.loads(body) == {"detail": "session required"}


def test_starters_refuses_session_with_non_loopback_origin(tmp_path: Path) -> None:
    """A non-loopback Origin is 403 even with a live session cookie."""

    app = _build_app(tmp_path)
    headers = _session_headers(app)
    headers[0] = ("Origin", "http://evil.example.com")
    status, _h, body, _c = _get_starters(app, headers=headers)
    assert status == 403, (status, body)
    assert json.loads(body) == {"detail": "origin not loopback"}


def test_starters_refuses_non_loopback_host(tmp_path: Path) -> None:
    """A non-loopback Host is 403; the gate checks Host, not just Origin."""

    app = _build_app(tmp_path)
    headers = _session_headers(app)
    status, _h, body, _c = _get_starters(app, headers=headers, host="evil.example.com")
    assert status == 403, (status, body)


def test_starters_does_not_require_csrf_header(tmp_path: Path) -> None:
    """A read endpoint: a bogus ``X-Krellbot-CSRF`` header still passes."""

    app = _build_app(tmp_path)
    headers = [
        *_session_headers(app),
        ("X-Krellbot-CSRF", "not-the-real-csrf"),
    ]
    status, _h, body, _c = _get_starters(app, headers=headers)
    assert status == 200, (status, body)
    assert json.loads(body)["schema_version"] == "1"


def test_starters_missing_or_unknown_session_cookie_is_403(tmp_path: Path) -> None:
    """An invented or revoked cookie is 403; presence alone is not enough."""

    app = _build_app(tmp_path)
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", "krellbot_session=made-up-value"),
    ]
    status, _h, body, _c = _get_starters(app, headers=headers)
    assert status == 403, (status, body)
    assert json.loads(body) == {"detail": "session required"}


# ---- 3. the frozen body ---------------------------------------------------


def test_starters_body_matches_frozen_contract(tmp_path: Path) -> None:
    """schema_version/catalogue_version/examples shape, manifest order."""

    doc = _authenticated_doc(tmp_path)
    assert doc["schema_version"] == "1"
    assert doc["catalogue_version"] == "1"

    examples = doc["examples"]
    assert isinstance(examples, list) and len(examples) >= 3, examples

    ids = [row["id"] for row in examples]
    assert len(ids) == len(set(ids)), ids
    assert ids == [row["id"] for row in starter_catalogue.list_examples()], ids

    for row in examples:
        assert set(row.keys()) == ROW_KEYS, row
        assert isinstance(row["id"], str) and row["id"]
        assert isinstance(row["label"], str) and row["label"]
        assert isinstance(row["description"], str) and row["description"]
        assert isinstance(row["pack"], dict)
        assert row["pack"]["id"] == row["id"], row["id"]


def test_starters_examples_are_labeled_educational_without_claims(tmp_path: Path) -> None:
    """Every example is an educational example with no claim language.

    The pack label carries the ``educational example`` marker, the
    description carries the ``no profit or return claim`` disclaimer,
    and profit/return words appear *only* inside that disclaimer.
    """

    doc = _authenticated_doc(tmp_path)
    claim_words = ("profit", "return", "roi", "alpha", "yield", "win rate", "gain")
    disclaimer = "no profit or return claim"
    for row in doc["examples"]:
        label = row["pack"].get("label", "")
        assert "educational example" in label.lower(), (row["id"], label)

        description = row["description"].lower()
        assert "educational example" in description, row["id"]
        assert disclaimer in description, (row["id"], description)

        combined = f"{row['label']} {description} {label}".lower()
        # Strip every disclaimer occurrence; what is left must be clean.
        remainder = combined.replace(disclaimer, "")
        for word in claim_words:
            assert word not in remainder, (row["id"], word, combined)


# ---- 4. every example is a valid ordinary pack -----------------------------


def test_every_starters_example_passes_the_existing_validator(tmp_path: Path) -> None:
    """``krellbot.pack.lint.check`` returns [] on every example pack."""

    doc = _authenticated_doc(tmp_path)
    for row in doc["examples"]:
        pack = row["pack"]
        assert check(pack) == [], (row["id"], check(pack))
        assert not is_legacy(pack), row["id"]
        # Real packs carry real predicates, indicators, and positions.
        assert pack["indicators"], row["id"]
        assert pack["entry"], row["id"]
        assert pack["exit"], row["id"]
        assert pack["risk"]["stop"], row["id"]
        assert pack["markets"], row["id"]


def test_starters_examples_cover_realistic_strategy_types(tmp_path: Path) -> None:
    """Trend-following crossover, mean-reversion band, and breakout."""

    doc = _authenticated_doc(tmp_path)
    ids = {row["id"] for row in doc["examples"]}
    assert {
        "starter-dual-ma-crossover",
        "starter-mean-reversion-band",
        "starter-range-breakout",
    } <= ids, ids


# ---- 5. resource loading through importlib.resources -----------------------


def test_catalogue_loads_through_real_importlib_resources(tmp_path: Path) -> None:
    """``files('krellbot.packs')`` resolves and lists every example."""

    from importlib.resources import files

    examples_dir = files("krellbot.packs").joinpath("examples")
    listed = sorted(
        item.name for item in examples_dir.iterdir() if item.name.endswith(".json") and item.name != "catalogue.json"
    )
    rows = starter_catalogue.list_examples()
    expected_files = sorted(f"{row['id']}.json" for row in rows)
    assert listed == expected_files, (listed, expected_files)


def test_catalogue_survives_a_fresh_interpreter(tmp_path: Path) -> None:
    """A brand-new python process lists the examples from package data."""

    code = (
        "from importlib.resources import files\n"
        "from krellbot.packs import catalogue\n"
        "print(catalogue.list_examples())\n"
    )
    env = {"KRELLBOT_HOME": str(tmp_path), "PATH": __import__("os").environ.get("PATH", "")}
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        check=True,
    )
    out = proc.stdout.strip()
    assert "starter-dual-ma-crossover" in out, (out, proc.stderr)
    assert "'id'" in out, out


def test_list_examples_returns_fresh_objects_each_call() -> None:
    """Mutating a returned row never leaks into the catalogue."""

    first = starter_catalogue.list_examples()
    first[0]["pack"]["id"] = "mutated"
    first[0]["label"] = "mutated"
    second = starter_catalogue.list_examples()
    assert second[0]["id"] != "mutated"
    assert second[0]["label"] != "mutated"
    assert second[0]["pack"]["id"] == second[0]["id"]


# ---- 6. the route is read-only ---------------------------------------------


def test_starters_route_writes_nothing_under_home(tmp_path: Path) -> None:
    """Serving the catalogue leaves the app's home byte-identical."""

    app = _build_app(tmp_path)
    headers = _session_headers(app)

    def snapshot(root: Path) -> dict[str, bytes]:
        out: dict[str, bytes] = {}
        if not root.exists():
            return out
        for path in sorted(root.rglob("*")):
            if path.is_file():
                out[str(path.relative_to(root))] = path.read_bytes()
        return out

    before = snapshot(tmp_path)
    status, _h, body, _c = _get_starters(app, headers=headers)
    assert status == 200, (status, body)
    after = snapshot(tmp_path)
    assert before == after, (sorted(before), sorted(after))


def test_starters_body_never_leaks_paths_or_tokens(tmp_path: Path) -> None:
    """No filesystem path or bootstrap token crosses the wire."""

    app = _build_app(tmp_path, bootstrap_token="boot-super-secret-token")
    status, _h, body, _c = _get_starters(app, headers=_session_headers(app))
    assert status == 200, (status, body)
    raw = body.decode("utf-8")
    assert str(tmp_path) not in raw, raw
    assert "boot-super-secret-token" not in raw, raw
    assert "src/krellbot" not in raw, raw


def test_broken_package_data_maps_to_500_not_partial_list(tmp_path, monkeypatch) -> None:
    """A broken catalogue surfaces as 500 — never a partial example list."""

    app = _build_app(tmp_path)
    headers = _session_headers(app)

    def broken() -> dict:
        raise starter_catalogue.StarterCatalogueError("synthetic break")

    monkeypatch.setattr(starter_catalogue, "catalogue_document", broken)
    status, _h, body, _c = _get_starters(app, headers=headers)
    assert status == 500, (status, body)
    assert "starter catalogue unavailable" in json.loads(body)["detail"]


# ---- 7. the goal-linked capability ----------------------------------------


def test_starter_becomes_owned_editable_copy_through_existing_draft_flow(
    tmp_path: Path,
) -> None:
    """Pick a starter → POST draft → validate → runnable, all real routes."""

    app = _build_app(tmp_path)

    # A fresh session (Origin + cookie) for GET, plus CSRF for the POSTs.
    token = app.state.krellbot.bootstrap_token
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 200, (status, body)
    csrf = json.loads(body)["csrf_token"]
    session = next(c for c in cookies if c.startswith("krellbot_session=")).split("=", 1)[1]

    get_headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _h, body, _c = asgi_call(app, method="GET", path=STARTERS_PATH, headers=get_headers)
    assert status == 200, (status, body)
    starter = json.loads(body)["examples"][0]
    pack = starter["pack"]

    # Save the starter as an owned draft through the existing route.
    payload = json.dumps({"pack": pack}).encode("utf-8")
    post_headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(payload))),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _h, body, _c = asgi_call(
        app,
        method="POST",
        path="/api/v1/strategies/drafts",
        body=payload,
        headers=post_headers,
    )
    assert status == 200, (status, body)
    created = json.loads(body)
    assert created["outcome"] == "created"
    assert created["strategy_id"] == pack["id"]
    assert created["state"] == "draft"
    revision_id = created["revision_id"]

    # The owned copy is a real file under the user's home.
    stored = list((tmp_path / "drafts").rglob(f"{revision_id}.json"))
    assert len(stored) == 1, stored

    # Validate it through the existing route: it becomes runnable.
    status, _h, body, _c = asgi_call(
        app,
        method="POST",
        path=f"/api/v1/strategies/drafts/{revision_id}/validate",
        body=b"",
        headers=post_headers,
    )
    assert status == 200, (status, body)
    validated = json.loads(body)
    assert validated["state"] == "validated", validated
    assert validated["runnable"] is True, validated
    assert validated["errors"] == [], validated

    # The owned copy is editable: an edit forks a new revision without
    # disturbing the parent bytes.
    edited = {**pack, "label": f"{pack['label']} — my copy"}
    payload = json.dumps({"pack": edited}).encode("utf-8")
    post_headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(payload))),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _h, body, _c = asgi_call(
        app,
        method="PUT",
        path=f"/api/v1/strategies/drafts/{revision_id}",
        body=payload,
        headers=post_headers,
    )
    assert status == 200, (status, body)
    forked = json.loads(body)
    assert forked["outcome"] == "created"
    assert forked["revision_id"] != revision_id
    parent_bytes = (tmp_path / "drafts" / pack["id"] / f"{revision_id}.json").read_bytes()
    assert json.loads(parent_bytes)["label"] == pack["label"]
