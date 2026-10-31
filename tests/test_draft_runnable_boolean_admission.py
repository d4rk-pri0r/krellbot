"""Draft runnable boolean admission — only literal JSON ``true`` arms.

COORDINATOR CONTRACT: the persisted draft metadata's ``runnable`` field
is admitted as runnable ONLY when it is the exact JSON boolean ``true``.
Missing, ``null``, ``false``, and truthy-looking non-boolean forms
(strings like ``"false"``/``"true"``, numbers like ``1``/``0``, arrays
like ``[false]``/``[true]``, objects) are ``False`` at every
read-conversion boundary: ``get``, ``list_owned_summaries``,
``is_runnable``, and ``pack_for_arm`` (the authenticated arm-by-revision
path). A refused arm keeps the exact prior honest-false refusal
code/status (HTTP 403 ``draft_not_runnable``) and mutates no armed-pack
config, draft bytes, or meta bytes.

Healthy controls preserved end to end: ``validate`` -> literal ``true``
-> arm succeeds and the revision becomes ``deployed``; a ``deployed``
revision keeps its literal-true projection across every read boundary.

Fixture provenance: the corrupted-metadata cases are SYNTHETIC LOCAL
data written directly against the on-disk ``<rev>.meta.json`` to
reproduce a locally corrupted record. They are not normal
service-generated records, not a security-exploit claim, and not a
TCP/browser/native/live qualification. All arm traffic goes through the
authenticated production ASGI app with the full session/Origin/CSRF
gates, exactly like the NS08a tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from krellbot.application.strategy import DraftNotRunnable, StrategyDraftService
from tests.test_ns06_api import TEST_PORT, _build_app, asgi_call
from tests.test_ns08_strategy_drafts import _arm_by_rev as _arm_by_revision
from tests.test_ns08_strategy_drafts import (
    _bootstrap_via_test,
    _get_drafts_list,
    _post_draft,
    _valid_pack_dict,
    _validate_draft,
)

# ---------------------------------------------------------------------------
# synthetic local corruption helpers
# ---------------------------------------------------------------------------

_MISSING = object()

# Non-boolean forms for the persisted ``runnable`` meta field. Every one
# of these is False under the coordinator contract, including the
# truthy-looking ones that ``bool()`` would admit today.
MALFORMED_RUNNABLE_FORMS = [
    pytest.param("false", id="string-false"),
    pytest.param("true", id="string-true"),
    pytest.param(1, id="number-1"),
    pytest.param(0, id="number-0"),
    pytest.param(1.0, id="number-1.0"),
    pytest.param([False], id="array-false"),
    pytest.param([True], id="array-true"),
    pytest.param({"runnable": True}, id="object"),
    pytest.param(None, id="null"),
    pytest.param(_MISSING, id="missing"),
]

ALL_FALSE_FORMS = MALFORMED_RUNNABLE_FORMS + [pytest.param(False, id="honest-false")]


def _paths_for(home: Path, revision_id: str) -> tuple[Path, Path]:
    rev_path = home / "drafts" / "trend-follow" / f"{revision_id}.json"
    meta_path = home / "drafts" / "trend-follow" / f"{revision_id}.meta.json"
    assert rev_path.exists(), rev_path
    assert meta_path.exists(), meta_path
    return rev_path, meta_path


def _rewrite_runnable(meta_path: Path, form: object) -> bytes:
    """SYNTHETIC LOCAL corruption: rewrite the persisted ``runnable`` meta
    value into ``form`` (or remove the key for ``_MISSING``) and return the
    exact on-disk meta bytes after the rewrite."""

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if form is _MISSING:
        meta.pop("runnable", None)
    else:
        meta["runnable"] = form
    meta_path.write_text(json.dumps(meta, sort_keys=True) + "\n", encoding="utf-8")
    return meta_path.read_bytes()


def _config_bytes(home: Path) -> bytes:
    config_path = home / "config.json"
    if not config_path.exists():
        return b""
    return config_path.read_bytes()


def _create_draft(app, csrf: str, session: str) -> str:
    status, body = _post_draft(app, csrf, session, _valid_pack_dict())
    assert status == 200, body
    return json.loads(body)["revision_id"]


# ---------------------------------------------------------------------------
# 1. authenticated ASGI arm-by-revision refuses every non-boolean form
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("form", ALL_FALSE_FORMS)
def test_paper_arm_refuses_non_boolean_runnable_metadata(home: Path, form: object) -> None:
    """A persisted ``runnable`` that is not the literal JSON boolean
    ``true`` refuses arm-by-revision with the exact prior honest-false
    refusal (HTTP 403 ``draft_not_runnable``, ``ok: false``,
    ``effect: refused``) and mutates nothing: no armed-pack config is
    written, the draft bytes and the corrupted meta bytes are
    byte-identical, and the revision stays in ``draft`` state."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)
    revision_id = _create_draft(app, csrf, session)

    rev_path, meta_path = _paths_for(home, revision_id)
    rev_before = rev_path.read_bytes()
    meta_before = _rewrite_runnable(meta_path, form)

    status, body = _arm_by_revision(app, csrf, session, revision_id)
    assert status == 403, (status, body)
    decoded = json.loads(body)
    assert decoded["code"] == "draft_not_runnable", decoded
    assert decoded["ok"] is False
    assert decoded["effect"] == "refused"

    # No armed-pack config was persisted; nothing else moved.
    assert _config_bytes(home) == b""
    assert rev_path.read_bytes() == rev_before
    assert meta_path.read_bytes() == meta_before
    assert json.loads(meta_path.read_text(encoding="utf-8"))["state"] == "draft"


def test_paper_arm_honest_false_revision_refuses_identically(home: Path) -> None:
    """An unvalidated draft (honest ``runnable: false`` written by the
    service itself) refuses arm-by-revision with 403 and no config write —
    the pre-existing refusal this change must preserve exactly."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)
    revision_id = _create_draft(app, csrf, session)

    status, body = _arm_by_revision(app, csrf, session, revision_id)
    assert status == 403, (status, body)
    decoded = json.loads(body)
    assert decoded["code"] == "draft_not_runnable", decoded
    assert decoded["ok"] is False
    assert _config_bytes(home) == b""


# ---------------------------------------------------------------------------
# 2. healthy literal-true controls still arm and deploy
# ---------------------------------------------------------------------------


def test_validated_true_control_arms_and_becomes_deployed(home: Path) -> None:
    """Healthy control: create -> validate (persists literal ``true``) ->
    arm succeeds with HTTP 200 ``armed`` and the revision becomes
    ``deployed`` with ``runnable`` still the literal boolean."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)
    revision_id = _create_draft(app, csrf, session)

    status, body = _validate_draft(app, csrf, session, revision_id)
    assert status == 200, body
    assert json.loads(body)["runnable"] is True

    status, body = _arm_by_revision(app, csrf, session, revision_id)
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded["code"] == "armed"
    assert decoded["ok"] is True

    assert (home / "config.json").exists()
    service = StrategyDraftService(home=home)
    snap = service.get(revision_id)
    assert snap is not None
    assert snap["state"] == "deployed"
    assert snap["runnable"] is True


def test_deployed_true_control_keeps_literal_true_projection(home: Path) -> None:
    """Healthy control: a deployed revision keeps its literal-true
    projection across every read boundary, so re-arm addressing stays
    consistent with the validate path."""

    service = StrategyDraftService(home=home)
    revision_id = service.create(_valid_pack_dict())["revision_id"]
    service.validate(revision_id)
    service.mark_deployed(revision_id)

    snap = service.get(revision_id)
    assert snap is not None
    assert snap["state"] == "deployed"
    assert snap["runnable"] is True
    assert service.is_runnable(revision_id) is True
    path, pack = service.pack_for_arm(revision_id)
    assert path.name == f"{revision_id}.json"
    assert pack["id"] == "trend-follow"
    row = next(r for r in service.list_owned_summaries() if r["revision_id"] == revision_id)
    assert row["state"] == "deployed"
    assert row["runnable"] is True


# ---------------------------------------------------------------------------
# 3. read-projection consistency: get / list / is_runnable / pack_for_arm
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("form", ALL_FALSE_FORMS)
def test_read_projections_treat_only_literal_true_as_runnable(home: Path, form: object) -> None:
    """For every non-boolean persisted form, all four read projections
    agree the revision is not runnable, and the reads neither repair nor
    rewrite the corrupted record."""

    service = StrategyDraftService(home=home)
    revision_id = service.create(_valid_pack_dict())["revision_id"]

    _rev_path, meta_path = _paths_for(home, revision_id)
    meta_before = _rewrite_runnable(meta_path, form)
    rev_before = service.canonical_bytes(revision_id)

    snap = service.get(revision_id)
    assert snap is not None
    assert snap["runnable"] is False
    assert isinstance(snap["runnable"], bool)

    assert service.is_runnable(revision_id) is False

    with pytest.raises(DraftNotRunnable):
        service.pack_for_arm(revision_id)

    rows = service.list_owned_summaries()
    row = next(r for r in rows if r["revision_id"] == revision_id)
    assert row["runnable"] is False
    assert isinstance(row["runnable"], bool)

    # Reads never repair or rewrite the malformed record.
    assert meta_path.read_bytes() == meta_before
    assert service.canonical_bytes(revision_id) == rev_before


def test_literal_true_projection_consistent_across_reads(home: Path) -> None:
    """After validate, the persisted value is the literal boolean and
    every read projection agrees it is runnable."""

    service = StrategyDraftService(home=home)
    revision_id = service.create(_valid_pack_dict())["revision_id"]
    assert service.is_runnable(revision_id) is False

    validated = service.validate(revision_id)
    assert validated["runnable"] is True
    assert isinstance(validated["runnable"], bool)

    _rev_path, meta_path = _paths_for(home, revision_id)
    assert json.loads(meta_path.read_text(encoding="utf-8"))["runnable"] is True

    assert service.is_runnable(revision_id) is True
    _path, pack = service.pack_for_arm(revision_id)
    assert pack["id"] == "trend-follow"
    row = next(r for r in service.list_owned_summaries() if r["revision_id"] == revision_id)
    assert row["runnable"] is True


# ---------------------------------------------------------------------------
# 4. authenticated ASGI read routes agree for corrupted metadata
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("form", MALFORMED_RUNNABLE_FORMS)
def test_api_read_routes_report_not_runnable_for_corrupted_meta(home: Path, form: object) -> None:
    """GET the draft detail and the drafts inventory through the
    authenticated production routes: a corrupted ``runnable`` renders as
    the JSON boolean ``false`` in both responses and nothing on disk is
    rewritten by the reads."""

    app = _build_app(home)
    csrf, session = _bootstrap_via_test(app)
    revision_id = _create_draft(app, csrf, session)

    _rev_path, meta_path = _paths_for(home, revision_id)
    meta_before = _rewrite_runnable(meta_path, form)

    detail_headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session}"),
    ]

    status, _hdrs, body, _cookies = asgi_call(
        app,
        method="GET",
        path=f"/api/v1/strategies/drafts/{revision_id}",
        headers=detail_headers,
    )
    assert status == 200, (status, body)
    assert json.loads(body)["runnable"] is False

    status, body = _get_drafts_list(app, session)
    assert status == 200, body
    rows = json.loads(body)["drafts"]
    row = next(r for r in rows if r["revision_id"] == revision_id)
    assert row["runnable"] is False

    assert meta_path.read_bytes() == meta_before
