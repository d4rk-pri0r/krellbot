"""Issue 283 (C46) — only the literal boolean ``true`` may waive gap checks.

The default research runner converts the submitted JSON payload into a
``ResearchRequest``. Before this issue's fix the conversion used
``bool()`` on the ``allow_gaps`` field, so a JSON string (``"false"``),
an array (``[false]``) and an object (``{"enabled": false}``) were all
coerced to a truthy value and silently bypassed the ``gapped_data``
refusal — producing the same receipt and trace as a literal ``true``.

The coordinator API contract: ONLY the actual boolean ``true`` may
enable the ``allow_gaps`` override. Omission, ``false``, ``null``,
strings (including ``"true"``/``"false"``), numbers 0/1, arrays and
objects must NOT bypass the missing-data checks; they are treated as
``false`` at this conversion boundary, not rejected by a new schema.

Every test here drives the REAL default runner
(``JobManager._default_runner`` -> ``ResearchService`` -> the real gap
checker). The gap checker is never stubbed or replaced. All CSVs are
offline synthetic fixtures: no network, no keyring reads, no exchange.

Layout:

  * HTTP proofs submit through the authenticated, guarded
    ``POST /api/v1/research/jobs`` envelope of the real app (loopback
    Origin/Host, session cookie, CSRF header) and follow the job to a
    terminal state, then read ``GET /api/v1/jobs/{id}/result``.
  * The parent synchronous proof calls the production default runner
    directly on the manager: zero jobs, zero worker threads, zero
    network.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from krellbot.api.app import create_app
from krellbot.api.jobs import JobManager, canonical_receipt_bytes
from tests.test_ns06_api import TEST_PORT
from tests.test_ns06_jobs import _bootstrap_session, _submit_job
from tests.test_ns09_research_api import _get_result, _wait_for_terminal
from tests.test_ns04_research_service import PACK_DICT, _write_pack, _write_synthetic_csv

# Sentinel meaning "the allow_gaps key is absent from the payload".
_OMIT = object()

# Every non-``True`` shape that must NOT waive the gapped_data refusal.
GAPPED_MUST_REFUSE = [
    pytest.param(_OMIT, id="omitted"),
    pytest.param(False, id="false"),
    pytest.param(None, id="null"),
    pytest.param("false", id="string-false"),
    pytest.param("true", id="string-true"),
    pytest.param(0, id="number-zero"),
    pytest.param(1, id="number-one"),
    pytest.param([False], id="list-false"),
    pytest.param({"enabled": False}, id="object-enabled-false"),
]

# On a complete (ungapped) CSV every shape above — plus literal True —
# must succeed: malformed values are treated as false, never rejected.
HEALTHY_MUST_SUCCEED = GAPPED_MUST_REFUSE + [pytest.param(True, id="true")]


def _build_default_app(home: Path, tag: str):
    """Build the real app with NO injected runner: the default
    ``JobManager._default_runner`` path runs, exactly as production."""

    token = f"boot-{home.name}-{id(home)}-{tag}"
    return create_app(home=home, port=TEST_PORT, bootstrap_token=token)


def _research_payload(pack_path: Path, csv_path: Path, allow_gaps: Any) -> dict:
    payload: dict = {
        "correlation_id": "gap-bool",
        "pack_path": str(pack_path),
        "venue": "kraken",
        "dataset_csv": str(csv_path),
    }
    if allow_gaps is not _OMIT:
        payload["allow_gaps"] = allow_gaps
    return payload


def _canonical_bytes(receipt: dict) -> bytes:
    return json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# 1. Gapped CSV through the authenticated HTTP roundtrip: every non-True
#    shape refuses with gapped_data; literal True succeeds.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("allow_gaps", GAPPED_MUST_REFUSE)
def test_http_gapped_csv_non_true_allow_gaps_fails_gapped_data(home: Path, tmp_path: Path, allow_gaps: Any) -> None:
    """Omission, false, null, strings, numbers, arrays and objects must
    all keep the gapped_data refusal — job fails, no result is stored."""

    pack_path = _write_pack(tmp_path, PACK_DICT)
    csv_path = _write_synthetic_csv(tmp_path / "gap.csv", gapped=True)
    app = _build_default_app(home, "gap-refuse")
    csrf, session = _bootstrap_session(app)

    status, submitted = _submit_job(app, csrf, session, _research_payload(pack_path, csv_path, allow_gaps))
    assert status == 200, (status, submitted)

    final = _wait_for_terminal(app, csrf, session, submitted["id"])
    assert final["state"] == "failed", (allow_gaps, final)
    assert final["result_ref"] is None, (allow_gaps, final)
    assert final["error"] is not None, (allow_gaps, final)
    assert final["error"]["code"] == "gapped_data", (allow_gaps, final)

    r_status, r_body = _get_result(app, csrf, session, submitted["id"])
    assert r_status == 404, (allow_gaps, r_status, r_body)
    assert r_body == {"code": "result_unavailable"}, (allow_gaps, r_body)


def test_http_gapped_csv_literal_true_succeeds(home: Path, tmp_path: Path) -> None:
    """The one accepted shape: actual boolean true waives the gap check
    and the job succeeds with a stored receipt and trace."""

    pack_path = _write_pack(tmp_path, PACK_DICT)
    csv_path = _write_synthetic_csv(tmp_path / "gap.csv", gapped=True)
    app = _build_default_app(home, "gap-true")
    csrf, session = _bootstrap_session(app)

    status, submitted = _submit_job(app, csrf, session, _research_payload(pack_path, csv_path, True))
    assert status == 200, (status, submitted)

    final = _wait_for_terminal(app, csrf, session, submitted["id"])
    assert final["state"] == "succeeded", final
    assert final["error"] is None, final
    assert final["result_ref"], final

    r_status, r_body = _get_result(app, csrf, session, submitted["id"])
    assert r_status == 200, (r_status, r_body)
    assert set(r_body.keys()) == {"legacy_receipt", "trace"}, sorted(r_body.keys())
    assert r_body["legacy_receipt"]["venue"] == "kraken", r_body["legacy_receipt"]
    assert isinstance(r_body["trace"], list) and r_body["trace"], r_body["trace"]


# ---------------------------------------------------------------------------
# 2. Complete CSV compatibility: every shape succeeds; malformed shapes
#    behave exactly like false (byte-identical receipts), not a new
#    schema rejection.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("allow_gaps", HEALTHY_MUST_SUCCEED)
def test_http_healthy_csv_succeeds_for_every_allow_gaps_shape(home: Path, tmp_path: Path, allow_gaps: Any) -> None:
    """A complete CSV has nothing to waive: false/true/malformed all run
    the backtest to success — malformed values are treated as false at
    the conversion boundary, not refused."""

    pack_path = _write_pack(tmp_path, PACK_DICT)
    csv_path = _write_synthetic_csv(tmp_path / "data.csv")
    app = _build_default_app(home, "healthy-ok")
    csrf, session = _bootstrap_session(app)

    status, submitted = _submit_job(app, csrf, session, _research_payload(pack_path, csv_path, allow_gaps))
    assert status == 200, (status, submitted)

    final = _wait_for_terminal(app, csrf, session, submitted["id"])
    assert final["state"] == "succeeded", (allow_gaps, final)
    assert final["result_ref"], (allow_gaps, final)

    r_status, r_body = _get_result(app, csrf, session, submitted["id"])
    assert r_status == 200, (allow_gaps, r_status, r_body)
    assert r_body["legacy_receipt"]["venue"] == "kraken", (allow_gaps, r_body)


def test_http_healthy_csv_malformed_receipts_match_false_byte_for_byte(home: Path, tmp_path: Path) -> None:
    """On a complete CSV the malformed shapes produce the same canonical
    receipt bytes as an explicit false: the conversion is a boundary
    default, not a behavior change for healthy data."""

    pack_path = _write_pack(tmp_path, PACK_DICT)
    csv_path = _write_synthetic_csv(tmp_path / "data.csv")
    app = _build_default_app(home, "healthy-bytes")
    csrf, session = _bootstrap_session(app)

    receipts: dict[str, bytes] = {}
    for tag, allow_gaps in (
        ("false", False),
        ("string-false", "false"),
        ("string-true", "true"),
        ("list-false", [False]),
        ("object-false", {"enabled": False}),
        ("one", 1),
        ("true", True),
    ):
        payload = _research_payload(pack_path, csv_path, allow_gaps)
        payload["correlation_id"] = f"gap-bool-{tag}"
        status, submitted = _submit_job(app, csrf, session, payload)
        assert status == 200, (tag, status, submitted)

        final = _wait_for_terminal(app, csrf, session, submitted["id"])
        assert final["state"] == "succeeded", (tag, final)

        r_status, r_body = _get_result(app, csrf, session, submitted["id"])
        assert r_status == 200, (tag, r_status, r_body)
        receipts[tag] = _canonical_bytes(r_body["legacy_receipt"])

    for tag in ("string-false", "string-true", "list-false", "object-false", "one", "true"):
        assert receipts[tag] == receipts["false"], tag


# ---------------------------------------------------------------------------
# 3. Parent synchronous proof: the production default runner called
#    directly — zero jobs, zero worker threads, zero network.
# ---------------------------------------------------------------------------


def test_default_runner_synchronous_malformed_bypasses_refuse(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Call ``JobManager._default_runner`` directly, never ``submit``.

    The three malformed bypasses from the report ("false", [false],
    {"enabled": false}) must refuse with gapped_data. Four controls:
    omission refuses, literal false refuses, literal true succeeds with
    a receipt digest, and a complete CSV plus a malformed value still
    succeeds. No worker thread is spawned and any network attempt fails
    the test.
    """

    from urllib import request as _urllib_request

    def _no_urlopen(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted by the default runner")

    monkeypatch.setattr(_urllib_request, "urlopen", _no_urlopen)

    pack_path = _write_pack(tmp_path, PACK_DICT)
    gapped = _write_synthetic_csv(tmp_path / "gap.csv", gapped=True)
    healthy = _write_synthetic_csv(tmp_path / "data.csv")
    base = {"pack_path": str(pack_path), "venue": "kraken", "dataset_csv": str(gapped)}

    mgr = JobManager(home=home)

    # Three malformed bypasses from the reported issue: all refuse.
    for bad in ("false", [False], {"enabled": False}):
        outcome = mgr._default_runner({**base, "allow_gaps": bad})
        assert outcome["ok"] is False, (bad, outcome)
        assert outcome.get("code") == "gapped_data", (bad, outcome)

    # Control 1: omitted -> refuse.
    outcome = mgr._default_runner(dict(base))
    assert outcome["ok"] is False, outcome
    assert outcome.get("code") == "gapped_data", outcome

    # Control 2: literal false -> refuse.
    outcome = mgr._default_runner({**base, "allow_gaps": False})
    assert outcome["ok"] is False, outcome
    assert outcome.get("code") == "gapped_data", outcome

    # Control 3: literal true -> succeeds with receipt + digest.
    outcome = mgr._default_runner({**base, "allow_gaps": True})
    assert outcome["ok"] is True, outcome
    assert isinstance(outcome.get("result_ref"), str) and outcome["result_ref"], outcome
    receipt = outcome.get("legacy_receipt")
    assert isinstance(receipt, dict) and receipt, outcome
    digest = hashlib.sha256(canonical_receipt_bytes(receipt)).hexdigest()
    assert outcome["receipt_canonical_sha256"] == digest, outcome

    # Control 4: complete CSV + malformed value -> treated as false, still runs.
    outcome = mgr._default_runner({**base, "dataset_csv": str(healthy), "allow_gaps": "false"})
    assert outcome["ok"] is True, outcome

    # Zero jobs were created and zero worker threads exist.
    assert mgr.list_jobs() == []
    assert mgr._worker is None
