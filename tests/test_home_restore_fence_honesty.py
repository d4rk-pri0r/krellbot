"""Home restore API — fence honesty + corrupt refuse (M16.6).

``POST /api/v1/home/restore`` validates the gzip archive before touching
the live workstation home. Corrupt archives are refused without
destroying a good home. A successful restore into an empty home engages
the restore fence; while ``PAPER_ONLY_RELEASE`` is True the response
never claims ``live_ready``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from krellbot import release_policy
from krellbot.application import live_gate
from krellbot.storage import home_backup
from tests.test_ns06_api import (
    TEST_PORT as NS06_PORT,
)
from tests.test_ns06_api import (
    _bootstrap_and_get_csrf,
    _build_app,
    asgi_call,
)

TEST_PORT = NS06_PORT


def _bootstrap(app, token: str) -> tuple[str, str]:
    csrf_token = _bootstrap_and_get_csrf(app, token)
    assert csrf_token, csrf_token
    state = app.state.krellbot
    session_value = next(iter(state.sessions.keys()))
    return session_value, csrf_token


def _headers(session_value: str, csrf_token: str | None = None) -> list[tuple[str, str]]:
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    if csrf_token is not None:
        headers.append(("X-Krellbot-CSRF", csrf_token))
    return headers


def _post_restore(
    app,
    *,
    body: bytes,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes]:
    base = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/gzip"),
        ("Content-Length", str(len(body))),
    ]
    if headers:
        base.extend(headers)
    status, resp_headers, body_out, _cookies = asgi_call(
        app,
        method="POST",
        path="/api/v1/home/restore",
        headers=base,
        body=body,
    )
    return status, resp_headers, body_out


def _seed_source(home: Path) -> None:
    (home / "packs").mkdir(parents=True, exist_ok=True)
    (home / "packs" / "note.txt").write_text("restore-me\n", encoding="utf-8")
    (home / "run").mkdir(parents=True, exist_ok=True)
    (home / "run" / "marker.json").write_text('{"ok":true}\n', encoding="utf-8")


def _make_archive(tmp_path: Path) -> bytes:
    source = tmp_path / "source-home"
    source.mkdir()
    _seed_source(source)
    archive = tmp_path / "good.tar.gz"
    home_backup.create(source, archive, now=1_700_000_400)
    return archive.read_bytes()


# ---- gates ---------------------------------------------------------------


def test_home_restore_requires_session(home: Path) -> None:
    app = _build_app(home)
    status, _h, body = _post_restore(
        app,
        body=b"not-a-real-archive",
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, (status, body)


def test_home_restore_requires_csrf(home: Path) -> None:
    token = f"boot-restore-csrf-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value, _csrf = _bootstrap(app, token)
    status, _h, body = _post_restore(app, body=b"x", headers=_headers(session_value))
    assert status == 403, (status, body)


# ---- corrupt refuse / non-empty honesty ---------------------------------


def test_corrupt_archive_refused_without_destroying_home(home: Path, tmp_path: Path) -> None:
    marker = home / "packs" / "keep-me.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("precious\n", encoding="utf-8")

    token = f"boot-restore-corrupt-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf = _bootstrap(app, token)

    status, _h, body = _post_restore(
        app,
        body=b"this-is-not-a-gzip-archive",
        headers=_headers(session_value, csrf),
    )
    assert status == 400, (status, body)
    decoded = json.loads(body)
    assert decoded["ok"] is False
    assert decoded["code"] == "archive_corrupt"
    assert decoded["applied"] is False
    assert decoded["live_ready"] is False
    assert decoded["paper_only_release"] is True
    assert marker.read_text(encoding="utf-8") == "precious\n"


def test_valid_archive_refused_on_nonempty_home_without_destroy(home: Path, tmp_path: Path) -> None:
    marker = home / "packs" / "keep-me.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("still-here\n", encoding="utf-8")

    token = f"boot-restore-nonempty-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf = _bootstrap(app, token)

    status, _h, body = _post_restore(
        app,
        body=_make_archive(tmp_path),
        headers=_headers(session_value, csrf),
    )
    assert status == 409, (status, body)
    decoded = json.loads(body)
    assert decoded["ok"] is False
    assert decoded["code"] == "home_not_empty"
    assert decoded["validated"] is True
    assert decoded["applied"] is False
    assert decoded["fence_engaged"] is True
    assert decoded["live_ready"] is False
    assert decoded["paper_only_release"] is True
    assert (
        "home restored" in (decoded.get("kill_reason") or "").lower()
        or "restore" in (decoded.get("kill_reason") or "").lower()
    )
    assert marker.read_text(encoding="utf-8") == "still-here\n"


# ---- successful restore fence honesty -----------------------------------


def test_restore_into_empty_home_engages_fence_and_never_live_ready(home: Path, tmp_path: Path) -> None:
    assert release_policy.PAPER_ONLY_RELEASE is True

    token = f"boot-restore-ok-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf = _bootstrap(app, token)

    empty = tmp_path / "empty-target"
    empty.mkdir()
    # Session/CSRF stay in memory; point the API at an empty restore target.
    app.state.krellbot.home = empty

    status, _h, body = _post_restore(
        app,
        body=_make_archive(tmp_path),
        headers=_headers(session_value, csrf),
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded["ok"] is True
    assert decoded["code"] == "home_restored"
    assert decoded["applied"] is True
    assert decoded["fence_engaged"] is True
    assert decoded["entries_paused"] is True
    assert decoded["live_ready"] is False
    assert decoded["paper_only_release"] is True
    assert decoded["kill_reason"]
    assert "restore" in decoded["kill_reason"].lower()

    kill = live_gate.kill_state(empty)
    assert kill.engaged is True
    assert kill.reason == decoded["kill_reason"]
    assert (empty / "packs" / "note.txt").is_file()


def test_restore_honesty_stays_false_even_if_paper_only_patched_off(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restore response still reports live_ready False (fence engaged)."""

    monkeypatch.setattr(release_policy, "PAPER_ONLY_RELEASE", False)

    token = f"boot-restore-policy-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf = _bootstrap(app, token)

    empty = tmp_path / "empty-target-policy"
    empty.mkdir()
    app.state.krellbot.home = empty

    status, _h, body = _post_restore(
        app,
        body=_make_archive(tmp_path),
        headers=_headers(session_value, csrf),
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded["ok"] is True
    assert decoded["fence_engaged"] is True
    assert decoded["live_ready"] is False
    assert decoded["paper_only_release"] is False


def test_home_restore_path_appears_in_openapi(home: Path) -> None:
    app = _build_app(home)
    status, _h, body, _c = asgi_call(
        app,
        method="GET",
        path="/openapi.json",
        headers=[("Host", f"127.0.0.1:{TEST_PORT}")],
    )
    assert status == 200, status
    paths = json.loads(body).get("paths") or {}
    assert "/api/v1/home/restore" in paths, sorted(paths.keys())
