"""NS29 — release-frozen artifacts are unsigned / not notarized.

Tests-first. This test reads ``.github/workflows/release-frozen.yml``
and asserts the release-publish step's notes contain the literal words
``Unsigned`` and ``Not notarized``, and that the workflow does NOT
invoke ``codesign`` or ``signtool``.

If any of these assertions is already false (the workflow has been
edited to add signing or to remove the "Unsigned / Not notarized"
phrasing), this test stops and the report is written by the lane-D
conductor. We do NOT edit the workflow to fix the assertion.
"""

from __future__ import annotations

from pathlib import Path

WORKFLOW_PATH = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release-frozen.yml"


def _read_workflow() -> str:
    assert WORKFLOW_PATH.exists(), WORKFLOW_PATH
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_release_frozen_workflow_exists() -> None:
    """Sanity: the workflow file is on disk and is readable."""

    assert WORKFLOW_PATH.exists(), WORKFLOW_PATH
    text = _read_workflow()
    assert "publish GitHub release assets" in text, text[:200]


def test_release_notes_contain_unsigned_and_not_notarized() -> None:
    """Publish notes must include the literal words "Unsigned" and "Not notarized".

    The release notes are the user-visible guarantee that this build
    is unsigned and not notarized. The phrase must appear as-is in
    the ``--notes`` argument to ``gh release create``.
    """

    text = _read_workflow()
    assert "Unsigned" in text, "release notes are missing the literal word 'Unsigned'"
    assert "Not notarized" in text, "release notes are missing the literal phrase 'Not notarized'"


def test_release_workflow_does_not_call_codesign() -> None:
    """The workflow must not invoke ``codesign`` (macOS signing)."""

    text = _read_workflow()
    assert "codesign" not in text, (
        "release-frozen.yml must not invoke `codesign`; signing is out of scope for this build"
    )


def test_release_workflow_does_not_call_signtool() -> None:
    """The workflow must not invoke ``signtool`` (Windows Authenticode)."""

    text = _read_workflow()
    assert "signtool" not in text, (
        "release-frozen.yml must not invoke `signtool`; signing is out of scope for this build"
    )
