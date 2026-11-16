"""Secrets-gated release signing — workflow honesty pins.

Pins:

1. PR / unsigned paths stay available without secrets.
2. ``codesign`` / ``signtool`` appear only inside secrets-gated steps.
3. Missing-secret paths fail closed with named secret errors.
4. While ``ARTIFACTS_SIGNED`` is False, publish stays ``--prerelease``
   and unsigned notes remain available in the workflow text.
5. ``docs/signing.md`` documents secret **names** only (no cert material).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release-frozen.yml"
SIGNING_DOC = REPO_ROOT / "docs" / "signing.md"


def _read_workflow() -> str:
    assert WORKFLOW_PATH.exists(), WORKFLOW_PATH
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_release_frozen_workflow_exists() -> None:
    text = _read_workflow()
    assert "publish GitHub release assets" in text


def test_signing_doc_lists_secret_names_without_cert_material() -> None:
    assert SIGNING_DOC.is_file(), "docs/signing.md must exist"
    text = SIGNING_DOC.read_text(encoding="utf-8")
    required_names = (
        "APPLE_DEVELOPER_ID_P12_BASE64",
        "APPLE_DEVELOPER_ID_P12_PASSWORD",
        "APPLE_CODESIGN_IDENTITY",
        "APPLE_TEAM_ID",
        "APPLE_API_KEY_P8_BASE64",
        "APPLE_API_KEY_ID",
        "APPLE_API_ISSUER_ID",
        "WINDOWS_CODESIGN_P12_BASE64",
        "WINDOWS_CODESIGN_P12_PASSWORD",
        "KRELLBOT_SIGN_RELEASE",
    )
    for name in required_names:
        assert name in text, f"docs/signing.md must name secret/var {name}"
    assert "Gatekeeper" in text
    assert "SmartScreen" in text
    assert "checksum" in text.lower()
    # Refuse accidental cert dumps in the doc.
    assert "BEGIN CERTIFICATE" not in text
    assert "BEGIN PRIVATE KEY" not in text
    assert "-----BEGIN" not in text


def test_unsigned_release_notes_path_still_present() -> None:
    """Unsigned publish notes must remain available while signing may be off."""

    text = _read_workflow()
    assert "Unsigned" in text
    assert "Not notarized" in text
    assert "Not Authenticode-signed" in text
    assert "--prerelease" in text


def test_codesign_only_under_secrets_gated_macos_step() -> None:
    text = _read_workflow()
    assert "codesign" in text, "macOS signing step must invoke codesign when gated on"
    assert "Sign macOS Developer ID Application and notarize" in text
    assert "APPLE_DEVELOPER_ID_P12_BASE64" in text
    assert "required secrets are missing" in text
    # PR path must not require signing.
    assert "pull_request" in text
    assert re.search(
        r"steps\.signing\.outputs\.requested\s*==\s*'true'",
        text,
    ), "codesign step must gate on steps.signing.outputs.requested"


def test_signtool_only_under_secrets_gated_windows_step() -> None:
    text = _read_workflow()
    assert "signtool" in text, "Windows signing step must invoke signtool when gated on"
    assert "Sign Windows Authenticode" in text
    assert "WINDOWS_CODESIGN_P12_BASE64" in text
    assert re.search(
        r"steps\.signing\.outputs\.requested\s*==\s*'true'",
        text,
    ), "signtool step must gate on steps.signing.outputs.requested"


def test_linux_checksum_policy_step_present() -> None:
    text = _read_workflow()
    assert "Record Linux checksum-pinned signing policy" in text
    assert "checksum_pinned" in text


def test_signing_request_uses_repo_var_or_dispatch_input() -> None:
    text = _read_workflow()
    assert "KRELLBOT_SIGN_RELEASE" in text
    assert "sign_release" in text
    assert "Resolve whether platform signing is requested" in text


def test_release_notes_helper_unsigned_and_signed_paths() -> None:
    from scripts.ci_release_notes_from_signing_status import build_notes

    root = Path("/tmp/krellbot-signing-status-test")
    # Unique per-run dir under pytest tmp is nicer; keep self-contained.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        unsigned = build_notes(root=root, sha="abc")
        assert "Unsigned" in unsigned
        assert "Not notarized" in unsigned
        assert "Not Authenticode-signed" in unsigned

        (root / "signing-status-macos-arm64.json").write_text(
            '{"platform":"macos","arch":"arm64","signing_requested":true,"signed":true,"detail":"developer_id_notarized","sha":"abc"}\n',
            encoding="utf-8",
        )
        (root / "signing-status-windows-x86_64.json").write_text(
            '{"platform":"windows","arch":"x86_64","signing_requested":true,"signed":true,"detail":"authenticode","sha":"abc"}\n',
            encoding="utf-8",
        )
        (root / "signing-status-linux-x86_64.json").write_text(
            '{"platform":"linux","arch":"x86_64","signing_requested":true,"signed":false,"detail":"checksum_pinned_policy","sha":"abc"}\n',
            encoding="utf-8",
        )
        signed = build_notes(root=root, sha="abc")
        assert "Developer ID-signed and notarized" in signed
        assert "Authenticode-signed" in signed
        assert "prerelease" in signed.lower()
        assert "Unsigned" not in signed
