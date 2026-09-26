"""Local first-run preferences and trust snapshot.

These tests prove the visit preference is bounded JSON, corrupt-safe,
and never widens the home directory's permissions. They also prove the
trust snapshot reflects a fake/null keychain without ever reading a
secret value.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest


@pytest.fixture
def zero_umask():
    """Force umask 0o000 so mkdir creates world-writable dirs by default.

    This exposes the privacy bug where _ensure_home would skip its chmod
    because the resulting mode (0o777) is not the umask-default 0o755.
    """
    old = os.umask(0o000)
    try:
        yield
    finally:
        os.umask(old)


@pytest.fixture
def custom_umask():
    """Force a non-default umask (0o022 reversed to 0o077 so mkdir creates 0o700)."""
    old = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(old)


# --- has_visited_dashboard / mark_visited_dashboard -------------------------


def test_fresh_home_is_not_visited(tmp_path: Path) -> None:
    from krellbot.ui.first_run import has_visited_dashboard

    assert has_visited_dashboard(tmp_path) is False


def test_mark_then_has_roundtrip(tmp_path: Path) -> None:
    from krellbot.ui.first_run import has_visited_dashboard, mark_visited_dashboard

    assert has_visited_dashboard(tmp_path) is False
    mark_visited_dashboard(tmp_path)
    assert has_visited_dashboard(tmp_path) is True


def test_corrupt_preference_is_not_visited(tmp_path: Path) -> None:
    from krellbot.ui.first_run import has_visited_dashboard, mark_visited_dashboard

    mark_visited_dashboard(tmp_path)
    assert has_visited_dashboard(tmp_path) is True

    # Truncated / non-JSON payload must be treated as "not visited" and
    # must not raise.
    (tmp_path / "ui-preferences.json").write_text("{")
    assert has_visited_dashboard(tmp_path) is False


def test_preference_payload_is_bounded(tmp_path: Path) -> None:
    from krellbot.ui.first_run import mark_visited_dashboard

    mark_visited_dashboard(tmp_path)

    payload = (tmp_path / "ui-preferences.json").read_text()
    data = json.loads(payload)
    assert data == {"visited_dashboard": True}


def test_unreadable_preference_is_not_visited(tmp_path: Path) -> None:
    from krellbot.ui.first_run import has_visited_dashboard, mark_visited_dashboard

    mark_visited_dashboard(tmp_path)
    assert has_visited_dashboard(tmp_path) is True

    # Replace the file with a directory so open() fails. has_visited_dashboard
    # must swallow OSError and return False.
    (tmp_path / "ui-preferences.json").unlink()
    (tmp_path / "ui-preferences.json").mkdir()
    assert has_visited_dashboard(tmp_path) is False


@pytest.mark.parametrize(
    "raw",
    [
        '{"visited_dashboard": 1}',                # truthy non-bool
        '{"visited_dashboard": "true"}',          # truthy string
        '{"visited_dashboard": "yes"}',           # truthy string
        '{"visited_dashboard": 0.1}',              # truthy float
        '{"visited_dashboard": [true]}',          # truthy list
        '{"visited_dashboard": null}',             # missing/falsy
        '{"visited_dashboard": false}',           # explicit false
        '{}',                                      # missing key
    ],
)
def test_has_visited_dashboard_strict_bool(tmp_path: Path, raw: str) -> None:
    """Any non-literal-True value must read as 'not visited'.

    Only the exact JSON literal `true` flips the wizard off; strings,
    numbers, lists, null, false, and missing keys keep the user in the
    wizard so a corrupt or hand-edited file cannot silently re-arm it.
    """
    from krellbot.ui.first_run import has_visited_dashboard

    (tmp_path / "ui-preferences.json").write_text(raw)
    assert has_visited_dashboard(tmp_path) is False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_mark_creates_missing_home_at_0o700(tmp_path: Path) -> None:
    """When the home does not exist yet, mark_visited_dashboard must create
    it with mode 0o700 on POSIX rather than letting atomic_write raise
    FileNotFoundError. The preference file inside is then 0o600.
    """
    from krellbot.ui.first_run import mark_visited_dashboard

    missing = tmp_path / "fresh-home"
    assert not missing.exists()

    mark_visited_dashboard(missing)

    assert missing.is_dir()
    home_mode = missing.stat().st_mode & 0o777
    assert home_mode == 0o700, f"newly created home should be 0o700, got {oct(home_mode)}"
    pref_mode = (missing / "ui-preferences.json").stat().st_mode & 0o777
    assert pref_mode == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_mark_does_not_widen_existing_home(tmp_path: Path) -> None:
    """If the home already exists with a non-default mode, marking must
    not chmod it. (Covered more strictly by test_mark_visited_does_not_widen_home,
    but this version does not pre-condition the mode to 0o750.)
    """
    from krellbot.ui.first_run import mark_visited_dashboard

    home = tmp_path / "existing-home"
    home.mkdir(mode=0o755)
    before = home.stat().st_mode & 0o777
    assert before == 0o755

    mark_visited_dashboard(home)

    after = home.stat().st_mode & 0o777
    assert after == before, f"home mode changed: {oct(before)} -> {oct(after)}"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_mark_visited_does_not_widen_home(tmp_path: Path) -> None:
    """Writing the preference file must not chmod the home directory.

    atomic_write chmods only the file it creates; the surrounding home
    must keep the mode the caller set. We start with a non-default mode
    (0o750) and assert it survives a mark.
    """
    from krellbot.ui.first_run import mark_visited_dashboard

    os.chmod(tmp_path, 0o750)
    before = tmp_path.stat().st_mode & 0o777
    assert before == 0o750

    mark_visited_dashboard(tmp_path)

    after = tmp_path.stat().st_mode & 0o777
    assert after == before, f"home mode changed: {oct(before)} -> {oct(after)}"
    # The preference file itself should still be private.
    pref_mode = (tmp_path / "ui-preferences.json").stat().st_mode & 0o777
    assert pref_mode == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_ensure_home_is_0o700_under_zero_umask(tmp_path: Path, zero_umask) -> None:
    """Privacy must hold under any umask, including umask=0o000.

    With umask 0o000, a plain ``mkdir`` would create the directory with
    mode 0o777 (world-readable/writable). _ensure_home must still leave
    the freshly created home at exactly 0o700 so the data directory
    cannot leak to other local users.
    """
    from krellbot.ui.first_run import mark_visited_dashboard

    missing = tmp_path / "fresh-home-zero-umask"
    assert not missing.exists()

    mark_visited_dashboard(missing)

    assert missing.is_dir()
    home_mode = missing.stat().st_mode & 0o777
    assert home_mode == 0o700, (
        f"newly created home must be 0o700 under zero umask, got {oct(home_mode)}"
    )
    pref_mode = (missing / "ui-preferences.json").stat().st_mode & 0o777
    assert pref_mode == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_ensure_home_is_0o700_under_other_nonstandard_umask(tmp_path: Path, custom_umask) -> None:
    """Privacy must also hold under a non-default umask like 0o077.

    With umask 0o077, mkdir creates 0o700 (already private). _ensure_home
    must still result in exactly 0o700 — no widening, no narrowing.
    """
    from krellbot.ui.first_run import mark_visited_dashboard

    missing = tmp_path / "fresh-home-custom-umask"
    assert not missing.exists()

    mark_visited_dashboard(missing)

    assert missing.is_dir()
    home_mode = missing.stat().st_mode & 0o777
    assert home_mode == 0o700, (
        f"newly created home must be 0o700 under umask 0o077, got {oct(home_mode)}"
    )


# --- trust_snapshot ---------------------------------------------------------


def test_trust_snapshot_keys(tmp_path: Path) -> None:
    from krellbot.ui import trust

    snap = trust.trust_snapshot(tmp_path)
    assert set(snap.keys()) == {
        "home",
        "home_mode",
        "keychain_backend",
        "keychain_ok",
        "bind",
        "live_arm_ui_allowed",
        "trade_only_required",
    }
    assert snap["home"] == str(tmp_path)
    assert snap["bind"] == "127.0.0.1"
    assert snap["live_arm_ui_allowed"] is False
    assert snap["trade_only_required"] is True


def test_trust_snapshot_never_reads_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fake/null keychain backend must surface keychain_ok=False, and the
    snapshot must never expose any secret value.
    """
    from krellbot.ui import trust

    monkeypatch.setattr(
        trust,
        "_keychain_backend",
        lambda: ("keyring.backends.null.Keyring", "keychain backend is NullKeyring (not persistent)"),
    )

    snap = trust.trust_snapshot(tmp_path)

    assert snap["keychain_backend"] == "keyring.backends.null.Keyring"
    assert snap["keychain_ok"] is False

    # No credential string should leak.
    repr_ = repr(snap).lower()
    assert "secret" not in repr_
    assert "password" not in repr_
    assert "api_key" not in repr_


def test_trust_snapshot_reports_missing_home_mode(tmp_path: Path) -> None:
    from krellbot.ui import trust

    # Use a path that does not exist.
    missing = tmp_path / "nope" / "home"
    snap = trust.trust_snapshot(missing)
    assert snap["home_mode"] is None


def test_trust_snapshot_reports_home_mode(tmp_path: Path) -> None:
    from krellbot.ui import trust

    os.chmod(tmp_path, 0o700)
    snap = trust.trust_snapshot(tmp_path)
    assert snap["home_mode"] == "0o700"


def test_trust_snapshot_reports_unreadable_home_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If stat() raises OSError, home_mode must be None (not raise)."""
    from krellbot.ui import trust

    real_stat = Path.stat

    def fake_stat(self, *args, **kwargs):  # noqa: ANN001
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "stat", fake_stat)

    # trust_snapshot uses os.stat directly, not Path.stat — patch the module's
    # reference.
    monkeypatch.setattr(trust.os, "stat", fake_stat)
    snap = trust.trust_snapshot(tmp_path)
    assert snap["home_mode"] is None
