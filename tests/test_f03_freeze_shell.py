"""F03a — bundle the built paper shell.

Tests-first. The behaviour under test is the PyInstaller one-dir bundle
shipping the Vite-built ``frontend/dist`` and the API shell resolver
preferring the bundled copy when ``sys.frozen`` is true.

Behavior under test:

  1. ``scripts.freeze._build_args`` emits an ``--add-data`` entry whose
     source is ``frontend/dist`` and whose destination inside the
     bundle is ``frontend/dist``. The legacy
     ``src/krellbot/ui/static`` → ``krellbot/ui/static`` entry remains
     (the brief explicitly forbids removing it).

  2. ``_build_args`` is pure: calling it does not invoke PyInstaller
     and does not start a subprocess.

  3. When ``sys.frozen`` is true and ``sys._MEIPASS`` points at a
     directory whose ``frontend/dist/index.html`` exists, the API shell
     resolver returns that bundled directory — NOT a checkout-relative
     path.

  4. When ``sys.frozen`` is true but ``_MEIPASS`` does NOT contain
     ``frontend/dist/index.html`` (defence-in-depth for a stale layout),
     the resolver falls back to the checkout ``frontend/dist``. The
     frozen run still serves a usable shell.

  5. When NOT frozen, the resolver returns the checkout ``frontend/dist``.

  6. The explicit ``dist_dir`` keyword on ``_resolve_dist_dir`` continues
     to override the auto-detected path in both frozen and non-frozen
     modes.

  7. A missing build still yields ``shell_not_built`` from the existing
     static route; the resolver does not synthesise HTML, frozen or not.

No PyInstaller is invoked by these tests. The freeze-step assertions
introspect the argument list; the resolver assertions use a stub ``sys``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FREEZE_SCRIPT = REPO_ROOT / "scripts" / "freeze.py"

SEP = ";" if sys.platform == "win32" else ":"


# ---------------------------------------------------------------------------
# Loader helpers (mirror tests/test_frozen_main.py)
# ---------------------------------------------------------------------------


def _load_freeze_module():
    """Load ``scripts/freeze.py`` as a module without running its ``__main__`` guard.

    The module body only defines helpers and a ``__main__`` guard, so
    loading it under a non-``__main__`` run-name is a pure import. No
    subprocess, no PyInstaller.
    """
    spec = importlib.util.spec_from_file_location("freeze_under_test", FREEZE_SCRIPT)
    assert spec is not None and spec.loader is not None, FREEZE_SCRIPT
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _add_data_entries(args: list[str]) -> list[tuple[str, str]]:
    """Return every ``--add-data SRC<DEST>`` pair from a PyInstaller arg list."""

    pairs: list[tuple[str, str]] = []
    for index, token in enumerate(args):
        if token == "--add-data" and index + 1 < len(args):
            raw = args[index + 1]
            if SEP in raw:
                src, dest = raw.split(SEP, 1)
                pairs.append((src, dest))
    return pairs


def _build_args_kwargs():
    """Return a kwargs dict usable with the helper under test."""

    return {
        "entry": REPO_ROOT / "scripts" / "frozen_main.py",
        "dist_root": REPO_ROOT / "dist",
        "work_root": REPO_ROOT / "build" / "pyinstaller",
        "spec_root": REPO_ROOT / "build" / "spec",
        "repo_root": REPO_ROOT,
    }


def _import_app_resolver():
    """Return ``(app_module, resolver)``. Patched ``sys`` is applied per test."""

    from krellbot.api import app as app_module

    return app_module, app_module._resolve_dist_dir


def _make_bundled_meipass(tmp_path: Path, name: str = "meipass") -> Path:
    """Lay out ``<tmp>/<name>/frontend/dist/index.html`` and return the dist path."""

    meipass = tmp_path / name
    dist = meipass / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "index.js").write_text("// bundled placeholder", encoding="utf-8")
    (dist / "index.html").write_text(
        '<!doctype html><html><head><title>F03a bundled</title></head><body><div id="root"></div></body></html>',
        encoding="utf-8",
    )
    return dist


# ---------------------------------------------------------------------------
# 1. _build_args includes the frontend/dist add-data entry
# ---------------------------------------------------------------------------


def test_build_args_includes_frontend_dist_data_entry() -> None:
    """``_build_args`` emits an ``--add-data`` entry that ships
    ``frontend/dist`` into the bundle at ``frontend/dist``.

    The dest path inside the bundle is exactly ``frontend/dist`` so the
    API shell resolver can find ``frontend/dist/index.html`` by
    suffixing ``sys._MEIPASS``.
    """

    freeze = _load_freeze_module()
    args = freeze._build_args(**_build_args_kwargs())

    pairs = _add_data_entries(args)
    matches = [pair for pair in pairs if Path(pair[1]).parts == ("frontend", "dist")]
    assert matches, f"_build_args must include an --add-data entry whose dest is frontend/dist; got pairs={pairs!r}"
    src_path = Path(matches[0][0]).resolve()
    expected_src = (REPO_ROOT / "frontend" / "dist").resolve()
    assert src_path == expected_src, (src_path, expected_src)


def test_build_args_keeps_legacy_static_data_entry() -> None:
    """The brief forbids removing the legacy ``src/krellbot/ui/static`` → ``krellbot/ui/static``
    entry. We assert the pair is still present so the legacy wizard /
    dashboard path keeps working in the bundle.
    """

    freeze = _load_freeze_module()
    args = freeze._build_args(**_build_args_kwargs())

    pairs = _add_data_entries(args)
    legacy = [pair for pair in pairs if Path(pair[1]).parts == ("krellbot", "ui", "static")]
    assert legacy, (
        "_build_args must keep the legacy src/krellbot/ui/static -> "
        f"krellbot/ui/static --add-data entry; got pairs={pairs!r}"
    )
    src_path = Path(legacy[0][0]).resolve()
    expected_src = (REPO_ROOT / "src" / "krellbot" / "ui" / "static").resolve()
    assert src_path == expected_src, (src_path, expected_src)


# ---------------------------------------------------------------------------
# 2. _build_args must not invoke PyInstaller
# ---------------------------------------------------------------------------


def test_build_args_does_not_invoke_pyinstaller(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_build_args`` is a pure assembler. Calling it must not start
    a subprocess, must not probe for the pyinstaller executable, and
    must not run the higher-level ``freeze()`` machinery.
    """

    freeze = _load_freeze_module()

    def _fail(*_args, **_kwargs):
        raise AssertionError("_build_args must not invoke pyinstaller or run any subprocess")

    monkeypatch.setattr(freeze.subprocess, "run", _fail)
    monkeypatch.setattr(freeze.shutil, "which", _fail)
    called_freeze = mock.MagicMock(side_effect=_fail)
    monkeypatch.setattr(freeze, "freeze", called_freeze)

    args = freeze._build_args(**_build_args_kwargs())

    assert isinstance(args, list)
    assert all(isinstance(token, str) for token in args)
    called_freeze.assert_not_called()


# ---------------------------------------------------------------------------
# 3. _resolve_dist_dir — sys.frozen + sys._MEIPASS branch
# ---------------------------------------------------------------------------


@pytest.fixture
def frozen_with_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Patch ``krellbot.api.app.sys`` so the resolver runs as if frozen.

    Returns ``(module, resolver, bundled_dist)`` where ``bundled_dist``
    is the ``<meipass>/frontend/dist`` the resolver must return.
    """

    bundled_dist = _make_bundled_meipass(tmp_path, name="meipass_with_bundle")
    app_module, resolver = _import_app_resolver()

    fake_sys = SimpleNamespace(
        frozen=True,
        _MEIPASS=str(tmp_path / "meipass_with_bundle"),
        platform=sys.platform,
    )
    monkeypatch.setattr(app_module, "sys", fake_sys)

    return app_module, resolver, bundled_dist


def test_resolve_dist_dir_frozen_with_meipass_index_returns_bundled(
    frozen_with_bundle,
) -> None:
    """When ``sys.frozen`` is true and ``sys._MEIPASS`` points at a
    directory whose ``frontend/dist/index.html`` exists, the resolver
    returns that bundled directory — not a checkout-relative path.
    """

    _app_module, resolver, bundled_dist = frozen_with_bundle

    resolved = resolver(None)

    assert resolved == bundled_dist, (
        f"_resolve_dist_dir must return the bundled frontend/dist, not a checkout path; got {resolved!r}"
    )
    # Defence-in-depth: the bundled HTML actually exists and is reachable.
    assert (resolved / "index.html").is_file()


# ---------------------------------------------------------------------------
# 4. _resolve_dist_dir — sys.frozen without a valid MEIPASS index falls back
# ---------------------------------------------------------------------------


def test_resolve_dist_dir_frozen_without_index_stays_in_the_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A frozen process with no bundled index must not read the checkout."""

    app_module, resolver = _import_app_resolver()

    empty_meipass = tmp_path / "empty_meipass"
    empty_meipass.mkdir()

    fake_sys = SimpleNamespace(
        frozen=True,
        _MEIPASS=str(empty_meipass),
        platform=sys.platform,
    )
    monkeypatch.setattr(app_module, "sys", fake_sys)

    resolved = resolver(None)

    expected = empty_meipass / "frontend" / "dist"
    assert resolved == expected, (resolved, expected)
    assert REPO_ROOT not in resolved.parents


# ---------------------------------------------------------------------------
# 5. _resolve_dist_dir — non-frozen checkout path
# ---------------------------------------------------------------------------


def test_resolve_dist_dir_not_frozen_returns_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When not frozen, the resolver returns the checkout ``frontend/dist``."""

    app_module, resolver = _import_app_resolver()

    fake_sys = SimpleNamespace(
        frozen=False,
        _MEIPASS=None,
        platform=sys.platform,
    )
    monkeypatch.setattr(app_module, "sys", fake_sys)

    resolved = resolver(None)

    expected = (REPO_ROOT / "frontend" / "dist").resolve()
    assert resolved == expected, (resolved, expected)


# ---------------------------------------------------------------------------
# 6. Explicit dist_dir keyword wins, even when sys.frozen is true
# ---------------------------------------------------------------------------


def test_resolve_dist_dir_explicit_overrides_frozen_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``_resolve_dist_dir(dist_dir)`` returns ``dist_dir`` verbatim
    regardless of whether ``sys.frozen`` is true. The brief allows
    tests (and operators) to inject a directory; the injected one
    always wins.
    """

    app_module, resolver = _import_app_resolver()

    override = tmp_path / "injected_dist"
    override.mkdir()

    fake_sys = SimpleNamespace(
        frozen=True,
        _MEIPASS=str(tmp_path / "unused_meipass"),
        platform=sys.platform,
    )
    monkeypatch.setattr(app_module, "sys", fake_sys)

    resolved = resolver(override)

    assert resolved == override, resolved


# ---------------------------------------------------------------------------
# 7. Frozen + missing bundle still produces shell_not_built on GET /
# ---------------------------------------------------------------------------


def test_frozen_missing_bundle_yields_shell_not_built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end through the FastAPI app: when the resolver returns a
    path that does NOT contain ``frontend/dist/index.html``, the static
    layer still returns ``{"code": "shell_not_built"}``. We exercise
    the frozen-runtime branch by injecting ``dist_dir=missing_dist``
    which the resolver returns verbatim; the static route then
    encounters the missing file and emits the closed JSON shape. No
    synthetic HTML is written to disk by either the resolver or the
    route.
    """

    from tests.test_ns06_api import asgi_call

    app_module, _resolver = _import_app_resolver()

    empty_meipass = tmp_path / "no_bundle"
    empty_meipass.mkdir()

    fake_sys = SimpleNamespace(
        frozen=True,
        _MEIPASS=str(empty_meipass),
        platform=sys.platform,
    )
    monkeypatch.setattr(app_module, "sys", fake_sys)

    # Inject a directory that does not exist on disk via ``dist_dir`` so
    # the resolver does not consult the host checkout at all. The
    # static route then encounters a missing ``index.html`` and returns
    # the closed JSON shape.
    missing_dist = tmp_path / "no_such_dist"

    app = app_module.create_app(
        home=tmp_path / "home_f03",
        port=8080,
        bootstrap_token="boot-f03-missing",
        dist_dir=missing_dist,
    )

    status, headers, body, _cookies = asgi_call(
        app,
        method="GET",
        path="/",
        headers=[("Host", "127.0.0.1:8080")],
    )
    assert status == 404, (status, headers, body)
    flat = {name.lower(): value for name, value in headers}
    assert flat.get("content-type", "").startswith("application/json"), flat
    import json

    assert json.loads(body) == {"code": "shell_not_built"}, body
    # No HTML was synthesised on disk by the resolver or the route.
    assert not (missing_dist / "index.html").exists()
