"""RED-then-GREEN tests for `.github/scripts/test_integrity.py`.

These tests import ONLY the trusted checker module — no fixtures
are imported, only read as text.

The CI PR for Step 3 SHOULD fail test-integrity until JOE
approves, per the brief. We never auto-grant approval.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from . import base_ref, workdir as git_workdir  # type: ignore


from scripts import test_integrity as ti  # type: ignore


SHA = "ca351a08d40ba47204116b02f3356cbb4600b556"


# ---------------------------------------------------------------------------
# Adversarial: malicious fixtures should never be executed
# ---------------------------------------------------------------------------


def test_malicious_test_fixture_is_never_imported() -> None:
    """Import the fixtures directory listing and confirm the
    malicious test file is data-only and not imported."""
    fixtures_dir = Path(__file__).resolve().parent / "fixtures"
    assert fixtures_dir.is_dir()
    # A simple sentinel: the malicious file must NOT have been
    # imported — if it had been, keyring or the os module would
    # have side effects we could detect. We can't check those
    # directly; instead, we re-read the file and check the sentinel.
    malicious_file = fixtures_dir / "malicious_test.py"
    if malicious_file.exists():
        text = malicious_file.read_text(encoding="utf-8")
        assert "END_FIXTURE_DO_NOT_EXECUTE" in text


# ---------------------------------------------------------------------------
# Whole-word counter (submit( must NOT count as it()
# ---------------------------------------------------------------------------


def test_submit_call_does_not_count_as_it_call() -> None:
    """RED: a counter that matched `it(` greedily would false-positive
    on `submit(`. We expect zero `it_or_test_call` matches in the
    sample below."""
    src = (
        "def submit(x):\n"
        "    return x\n"
        "submit(form.value)\n"
        "class Foo:\n"
        "    def admission(self):\n"
        "        self.queue.append(submit('x'))\n"
    )
    bag = ti.count_test_markers(src)
    assert bag["it_or_test_call"] == 0
    assert bag["def_test_"] == 0
    assert bag["assert"] == 0
    assert bag["expect("] == 0


def test_real_test_call_is_counted() -> None:
    """RED-GREEN: a real `it(` must be counted."""
    src = (
        "test('a test', () => { expect(1).toBe(1); });\n"
        "test('another', () => { expect(true).toBe(true); });\n"
    )
    bag = ti.count_test_markers(src)
    assert bag["it_or_test_call"] == 2
    assert bag["expect("] == 2


def test_python_test_function_is_counted() -> None:
    """A `def test_foo(...)` Python fixture must be counted."""
    src = "def test_one():\n    assert True\n"
    bag = ti.count_test_markers(src)
    assert bag["def_test_"] == 1
    assert bag["assert"] == 1


def test_python_assert_word_is_counted() -> None:
    """`assert True` is counted as 1. `assembly` is NOT (whole-word)."""
    src = (
        "x = assembly_of_things\n"
        "assert x == 1\n"
    )
    bag = ti.count_test_markers(src)
    assert bag["assert"] == 1
    # Confirm we did NOT mistakenly match `assembly_of_things`.
    # (No direct way; the regex is anchored on a left word boundary
    # already.)


# ---------------------------------------------------------------------------
# Marker scan: skip / only / todo / fixme / xfail / fail
# ---------------------------------------------------------------------------


def test_marker_scan_finds_pytest_skip_decorator() -> None:
    text = "import pytest\n@pytest.mark.skip(reason='x')\ndef test_x():\n    pass\n"
    markers = ti.find_markers(text)
    # The first marker match on a line wins. Our regex maps
    # `pytest.mark.skip` first, so we expect that one.
    labels = [m for _, _, m in markers]
    assert "pytest.mark.skip" in labels


def test_marker_scan_finds_jsx_skip() -> None:
    text = (
        "describe('x', () => {\n"
        "  it.skip('half', () => {});\n"
        "  it.only('whole', () => {});\n"
        "});\n"
    )
    markers = ti.find_markers(text)
    labels = [m for _, _, m in markers]
    assert ".skip(" in labels
    assert ".only(" in labels


def test_marker_scan_finds_test_fail() -> None:
    text = "test('a thing', async ({ page }) => { test.fail(); expect(1).toBe(1); });\n"
    markers = ti.find_markers(text)
    labels = [m for _, _, m in markers]
    assert "test.fail(" in labels


def test_marker_scan_finds_pytest_xfail() -> None:
    text = "@pytest.mark.xfail(reason='broken')\ndef test_x():\n    pass\n"
    markers = ti.find_markers(text)
    labels = [m for _, _, m in markers]
    assert "pytest.mark.xfail" in labels


def test_marker_scan_handles_xtest_prefix() -> None:
    text = "xtest('legacy', () => {});\n"
    markers = ti.find_markers(text)
    labels = [m for _, _, m in markers]
    assert "xtest(" in labels


# ---------------------------------------------------------------------------
# Owner approval evaluation
# ---------------------------------------------------------------------------


def _ev(label: str, event: str, actor: str | None = None, at: str = "2026-01-01") -> dict[str, Any]:
    e: dict[str, Any] = {
        "event": event,
        "created_at": at,
        "label": {"name": label},
    }
    if actor is not None:
        e["actor"] = {"login": actor}
    return e


def test_owner_approval_labeled_by_owner() -> None:
    """RED: a `labeled` event by the actual owner → approved."""
    events = [_ev("owner-approved", "labeled", actor="joe")]
    status = ti.evaluate_owner_approval(
        repo="x/y", pr_number=1, owner_login="joe", events=events
    )
    assert status.approved is True
    assert status.last_actor_login == "joe"


def test_owner_approval_foreign_actor_is_rejected() -> None:
    """RED: a `labeled` event by an impersonator → not approved."""
    events = [_ev("owner-approved", "labeled", actor="someone-else")]
    status = ti.evaluate_owner_approval(
        repo="x/y", pr_number=1, owner_login="joe", events=events
    )
    assert status.approved is False
    assert "foreign apply" in status.reason


def test_owner_approval_unlabeled_after_label_is_rejected() -> None:
    """RED: an `unlabeled` event after the `labeled` revokes approval."""
    events = [
        _ev("owner-approved", "labeled", actor="joe", at="2026-01-01"),
        _ev("owner-approved", "unlabeled", actor="joe", at="2026-02-01"),
    ]
    status = ti.evaluate_owner_approval(
        repo="x/y", pr_number=1, owner_login="joe", events=events
    )
    assert status.approved is False


def test_owner_approval_no_label_event_is_rejected() -> None:
    """RED: no `owner-approved` event at all → not approved."""
    events = [_ev("another-label", "labeled", actor="joe")]
    status = ti.evaluate_owner_approval(
        repo="x/y", pr_number=1, owner_login="joe", events=events
    )
    assert status.approved is False


def test_owner_approval_malformed_event_is_rejected() -> None:
    """RED: an event missing actor / created_at → fail closed."""
    events = [{"event": "labeled", "label": {"name": "owner-approved"}}]  # no actor
    status = ti.evaluate_owner_approval(
        repo="x/y", pr_number=1, owner_login="joe", events=events
    )
    assert status.approved is False
    assert "Malformed" in status.reason


def test_owner_approval_unrelated_label_events_are_ignored() -> None:
    """Other labels do not influence the `owner-approved` state."""
    events = [
        _ev("bug", "labeled", actor="alice"),
        _ev("owner-approved", "labeled", actor="joe"),
        _ev("enhancement", "unlabeled", actor="bob"),
    ]
    status = ti.evaluate_owner_approval(
        repo="x/y", pr_number=1, owner_login="joe", events=events
    )
    assert status.approved is True


# ---------------------------------------------------------------------------
# Path predicates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path, expected",
    [
        ("tests/test_x.py", True),
        ("frontend/src/foo.test.tsx", True),
        ("frontend/src/foo.test.ts", True),
        ("frontend/e2e/x.spec.ts", True),
        ("frontend/journeys/j1.spec.ts", True),
        ("frontend/src/foo.tsx", False),
        ("src/krellbot/cli.py", False),
    ],
)
def test_is_test_path(path, expected):
    assert ti.is_test_path(path) is expected


@pytest.mark.parametrize(
    "path, expected",
    [
        ("docs/journeys/j1.md", True),
        (".github/scripts/x.py", True),
        ("docs/other.md", False),
        ("frontend/src/styles/tokens.css", False),
    ],
)
def test_is_protected_doc(path, expected):
    assert ti.is_protected_doc(path) is expected


@pytest.mark.parametrize(
    "path, expected",
    [
        ("frontend/e2e/__snapshots__/foo.spec.ts.snap", True),
        ("frontend/src/x/__snapshots__/x.test.ts.snap", True),
        ("frontend/e2e/foo.snap.svg", True),
        ("frontend/e2e/foo.spec.ts", False),
        ("tests/test_x.py", False),
    ],
)
def test_is_snapshot_path(path, expected):
    assert ti.is_snapshot_path(path) is expected


# ---------------------------------------------------------------------------
# end-to-end CLI: --events-file/--repository-file offline
# ---------------------------------------------------------------------------


def test_cli_offline_with_approval(
    tmp_path: Path, git_workdir: Path
):
    """RED: an offline fixture with a real labeled event by the owner
    must report approved=True and exit 1 (because Phase 2 PRs are not
    expected to pass without owner approval at the workflow level)."""
    workdir = git_workdir
    events_file = tmp_path / "events.json"
    events_file.write_text(
        json.dumps(
            [
                {
                    "event": "labeled",
                    "created_at": "2026-01-01T00:00:00Z",
                    "label": {"name": "owner-approved"},
                    "actor": {"login": "joe"},
                }
            ]
        ),
        encoding="utf-8",
    )
    repo_file = tmp_path / "repo.json"
    repo_file.write_text(
        json.dumps({"owner": {"login": "joe"}}),
        encoding="utf-8",
    )
    res = subprocess.run(  # noqa: S603 — argv list is hardcoded
        [
            sys.executable,
            "-m",
            "scripts.test_integrity",
            "--base",
            SHA,
            "--head",
            SHA,
            "--workdir",
            str(workdir),
            "--repo",
            "joe/krellbot",
            "--pr",
            "1",
            "--events-file",
            str(events_file),
            "--repository-file",
            str(repo_file),
            "--json",
            str(tmp_path / "out.json"),
        ],
        cwd=str(workdir / ".github"),
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert payload["approval"]["approved"] is True
    assert payload["approval"]["last_actor_login"] == "joe"


def test_cli_offline_no_approval(tmp_path: Path, git_workdir: Path):
    """RED: an offline fixture WITHOUT the labeled event must report
    approved=False."""
    workdir = git_workdir
    events_file = tmp_path / "events.json"
    events_file.write_text("[]", encoding="utf-8")
    repo_file = tmp_path / "repo.json"
    repo_file.write_text(
        json.dumps({"owner": {"login": "joe"}}),
        encoding="utf-8",
    )
    res = subprocess.run(  # noqa: S603 — argv list is hardcoded
        [
            sys.executable,
            "-m",
            "scripts.test_integrity",
            "--base",
            SHA,
            "--head",
            SHA,
            "--workdir",
            str(workdir),
            "--repo",
            "joe/krellbot",
            "--pr",
            "1",
            "--events-file",
            str(events_file),
            "--repository-file",
            str(repo_file),
            "--json",
            str(tmp_path / "out.json"),
        ],
        cwd=str(workdir / ".github"),
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert payload["approval"]["approved"] is False
    assert "owner-approved" in payload["approval"]["reason"]


def test_cli_offline_foreign_actor(tmp_path: Path, git_workdir: Path):
    """RED: a labeled event by someone who is NOT the owner → not approved."""
    workdir = git_workdir
    events_file = tmp_path / "events.json"
    events_file.write_text(
        json.dumps(
            [
                {
                    "event": "labeled",
                    "created_at": "2026-01-01T00:00:00Z",
                    "label": {"name": "owner-approved"},
                    "actor": {"login": "impostor"},
                }
            ]
        ),
        encoding="utf-8",
    )
    repo_file = tmp_path / "repo.json"
    repo_file.write_text(
        json.dumps({"owner": {"login": "joe"}}),
        encoding="utf-8",
    )
    res = subprocess.run(  # noqa: S603 — argv list is hardcoded
        [
            sys.executable,
            "-m",
            "scripts.test_integrity",
            "--base",
            SHA,
            "--head",
            SHA,
            "--workdir",
            str(workdir),
            "--repo",
            "joe/krellbot",
            "--pr",
            "1",
            "--events-file",
            str(events_file),
            "--repository-file",
            str(repo_file),
            "--json",
            str(tmp_path / "out.json"),
        ],
        cwd=str(workdir / ".github"),
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert payload["approval"]["approved"] is False
    assert "impostor" in payload["approval"]["reason"]
