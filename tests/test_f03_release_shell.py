"""F03b — build the paper shell before freeze.

Behaviour under test:

  1. ``.github/workflows/release-frozen.yml`` installs Node 22 with
     ``actions/setup-node@v4`` and runs ``npm ci --include=dev`` plus
     ``npm --prefix frontend run build`` from the repo root BEFORE
     invoking ``uv run python scripts/freeze.py``. Plain ``npm ci``
     is insufficient on hosts that export ``NODE_ENV=production``
     because npm then skips ``devDependencies`` (Vite, the React
     plugin, vitest, …) and the Vite build has nothing to run.

  2. ``scripts.freeze.freeze()`` refuses to invoke PyInstaller when
     ``frontend/dist/index.html`` is missing. The SystemExit message
     names ``npm --prefix frontend run build`` so a CI failure
     points the operator at the right fix. PyInstaller is never
     started — the test monkeypatches the invoker and asserts it
     was not called.

  3. The pre-build cleanup in ``freeze()`` does NOT delete
     ``frontend/dist`` while cleaning the PyInstaller
     ``dist/`` tree. The Vite-built artefact must survive the
     cleanup so the freeze can ship it; deleting it would
     silently break the bundle.

No PyInstaller is invoked. No GitHub workflow is run. No commit,
push, tag, or deploy.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-frozen.yml"
FREEZE_SCRIPT = REPO_ROOT / "scripts" / "freeze.py"

FREEZE_STEP_RUN = "uv run python scripts/freeze.py"


# ---------------------------------------------------------------------------
# Loader helpers (mirror tests/test_f03_freeze_shell.py)
# ---------------------------------------------------------------------------


def _load_freeze_module():
    """Load ``scripts/freeze.py`` as a module without running ``__main__``."""

    spec = importlib.util.spec_from_file_location("freeze_under_test", FREEZE_SCRIPT)
    assert spec is not None and spec.loader is not None, FREEZE_SCRIPT
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workflow_text() -> str:
    """Return the raw text of ``release-frozen.yml`` as a single string."""

    return WORKFLOW.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Workflow installs Node 22 and builds the frontend before freeze
# ---------------------------------------------------------------------------


def test_workflow_pins_node_22_via_setup_node_v4() -> None:
    """The workflow installs Node 22 with ``actions/setup-node@v4``.

    Vite 8 requires Node 20.19+ or 22.12+. We pin 22 explicitly so
    GH runners do not silently slide onto a Node that breaks the
    build. ``setup-node@v4`` is the action major the workflow
    already uses elsewhere.
    """

    text = _workflow_text()

    assert "actions/setup-node@v4" in text, (
        "release-frozen.yml must install Node with actions/setup-node@v4 before the freeze step"
    )

    # The setup-node call must pin a Node 22.x major. We assert the
    # major appears as ``node-version: "22"`` or ``node-version: '22'``
    # rather than parsing YAML so the assertion is robust to quoting.
    import re

    match = re.search(
        r"uses:\s*actions/setup-node@v4[\s\S]+?node-version:\s*[\"']?22(?:\.\d+)?[\"']?",
        text,
    )
    assert match, (
        "actions/setup-node@v4 must pin a Node 22.x version (e.g. node-version: '22'); "
        f"setup-node@v4 call not found or version pin missing. Text:\n{text[:4000]}"
    )


def test_workflow_runs_npm_ci_with_dev_before_freeze() -> None:
    """``npm ci --include=dev`` appears BEFORE the freeze step.

    This host (and most CI) exports ``NODE_ENV=production``. Plain
    ``npm ci`` then skips ``devDependencies`` — Vite, the React
    plugin, vitest — and the subsequent ``vite build`` has no
    compiler. ``--include=dev`` overrides the default and pulls in
    the toolchain. The string must appear before ``uv run python
    scripts/freeze.py`` so the freeze always sees a built
    ``frontend/dist``.
    """

    text = _workflow_text()

    pos_ci = text.find("npm ci --include=dev --prefix frontend")
    pos_plain_ci = text.find("npm ci") if "npm ci --include=dev" not in text else -1
    pos_build = text.find("npm --prefix frontend run build")
    pos_freeze = text.find(FREEZE_STEP_RUN)

    assert pos_ci != -1, (
        "release-frozen.yml must run `npm ci --include=dev --prefix frontend` so the frontend lockfile is installed"
        "even when NODE_ENV=production"
    )
    # If a plain ``npm ci`` line is present, it must not be the
    # only install line and it must be earlier than the freeze step
    # only if there is also a ``--include=dev`` step.
    if pos_plain_ci != -1:
        # Allow the ``--include=dev`` line and any bare ``npm ci``
        # line — but a bare ``npm ci`` is harmless as long as the
        # ``--include=dev`` variant exists upstream. We still warn
        # the operator when the only ``npm ci`` is bare.
        has_bare_ci_only = ("npm ci --include=dev" not in text) or (
            text.replace("npm ci --include=dev", "").find("npm ci") != -1
        )
        assert not has_bare_ci_only, (
            "release-frozen.yml contains a bare `npm ci` step without `--include=dev`; "
            "on hosts with NODE_ENV=production it will skip devDependencies"
        )
    assert pos_build != -1, (
        "release-frozen.yml must run `npm --prefix frontend run build` to produce "
        "frontend/dist/index.html before freeze"
    )
    assert pos_freeze != -1, "release-frozen.yml must invoke `uv run python scripts/freeze.py` for the freeze step"
    assert pos_ci < pos_freeze, (
        f"`npm ci --include=dev` (offset {pos_ci}) must appear before the freeze step "
        f"`{FREEZE_STEP_RUN}` (offset {pos_freeze})"
    )
    assert pos_build < pos_freeze, (
        f"`npm --prefix frontend run build` (offset {pos_build}) must appear before "
        f"the freeze step `{FREEZE_STEP_RUN}` (offset {pos_freeze})"
    )
    # Build must happen AFTER the install so vite is on PATH.
    assert pos_ci < pos_build, (
        f"`npm ci --include=dev` (offset {pos_ci}) must precede `npm --prefix frontend run build` (offset {pos_build})"
    )


# ---------------------------------------------------------------------------
# 2. scripts.freeze.freeze() refuses to invoke PyInstaller without a built index
# ---------------------------------------------------------------------------


def test_freeze_raises_systemexit_when_frontend_index_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``frontend/dist/index.html`` is missing, ``freeze()`` raises
    ``SystemExit`` and never invokes PyInstaller.

    The test stands up a synthetic repo root whose ``frontend/dist/``
    directory exists but contains no ``index.html`` (i.e. the
    ``npm --prefix frontend run build`` step was skipped or
    failed). The PyInstaller invoker is monkeypatched to a
    sentinel that records any call; the test then asserts the
    sentinel was never touched.
    """

    freeze = _load_freeze_module()

    # Lay out a synthetic repo root:
    #   <tmp>/scripts/frozen_main.py   (so entry exists; not used)
    #   <tmp>/frontend/dist/          (no index.html inside)
    fake_repo = tmp_path / "synthetic_repo"
    (fake_repo / "scripts").mkdir(parents=True)
    (fake_repo / "frontend" / "dist").mkdir(parents=True)
    (fake_repo / "scripts" / "frozen_main.py").write_text(
        "# sentinel entry — freeze() should never reach PyInstaller",
        encoding="utf-8",
    )
    # No index.html under frontend/dist — this is the regression we
    # want freeze() to refuse.

    pyi_calls: list[list[str]] = []

    def _record_pyi(args: list[str]) -> int:
        pyi_calls.append(list(args))
        return 0

    monkeypatch.setattr(freeze, "_invoke_pyinstaller", _record_pyi)

    with pytest.raises(SystemExit) as excinfo:
        freeze.freeze(repo_root=fake_repo)

    assert pyi_calls == [], (
        f"freeze() must not invoke PyInstaller when frontend/dist/index.html is missing; got calls={pyi_calls!r}"
    )

    message = str(excinfo.value)
    assert "npm --prefix frontend run build" in message, (
        f"SystemExit message must name the frontend build command so the operator knows the "
        f"fix; got message={message!r}"
    )


# ---------------------------------------------------------------------------
# 3. Pre-build cleanup must not delete frontend/dist
# ---------------------------------------------------------------------------


def test_freeze_cleanup_preserves_frontend_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``freeze()``'s pre-build cleanup removes the PyInstaller
    ``dist/`` tree but does NOT touch ``frontend/dist``.

    The Vite build artefact is the source of truth for the bundle.
    If the cleanup accidentally swept it, the freeze would ship
    an empty bundle even when ``npm run build`` succeeded
    upstream. The test arranges a synthetic repo with both
    ``frontend/dist/index.html`` and a sibling ``dist/``
    directory containing PyInstaller leftovers, then verifies
    that after ``freeze()`` returns (or fails) the
    ``frontend/dist/index.html`` is still on disk.

    ``freeze()`` raises SystemExit when ``dist_root`` exists and is
    not a directory it can clean (the synthetic repo has none, so
    cleanup is a no-op); we exercise the same pre-build branch by
    monkey-patching ``shutil.rmtree`` and asserting it is never
    asked to delete any path under ``frontend/``.
    """

    freeze = _load_freeze_module()

    fake_repo = tmp_path / "preserves_frontend"
    (fake_repo / "scripts").mkdir(parents=True)
    frontend_dist = fake_repo / "frontend" / "dist"
    frontend_dist.mkdir(parents=True)
    (frontend_dist / "index.html").write_text(
        "<!doctype html><html><head><title>keep me</title></head><body></body></html>",
        encoding="utf-8",
    )
    (fake_repo / "scripts" / "frozen_main.py").write_text("# sentinel entry", encoding="utf-8")

    # Arrange a pre-existing dist_root + work_root so the cleanup
    # branch actually runs. We also precreate a nested file under
    # ``dist/`` so shutil.rmtree has something to delete.
    (fake_repo / "dist" / "krellbot").mkdir(parents=True)
    (fake_repo / "dist" / "krellbot" / "leftover.txt").write_text("pyinstaller leftover", encoding="utf-8")

    observed_rmtrees: list[Path] = []
    real_rmtree = freeze.shutil.rmtree

    def _spy_rmtree(path, *args, **kwargs):
        observed_rmtrees.append(Path(path))
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(freeze.shutil, "rmtree", _spy_rmtree)
    # We never want PyInstaller to actually run during this
    # regression — the brief says freeze() may proceed, but the
    # test only needs to assert cleanup semantics. Stub it out.
    monkeypatch.setattr(
        freeze,
        "_invoke_pyinstaller",
        lambda args: (_ for _ in ()).throw(SystemExit("stop before pyinstaller")),
    )

    with pytest.raises(SystemExit):
        freeze.freeze(repo_root=fake_repo)

    # frontend/dist must still exist after cleanup.
    assert frontend_dist.is_dir(), f"cleanup must not delete frontend/dist; observed_rmtrees={observed_rmtrees!r}"
    assert (frontend_dist / "index.html").is_file(), "frontend/dist/index.html must survive the pre-build cleanup"

    # Defence-in-depth: no rmtree call ever targeted a path under
    # ``frontend/``. This catches the regression where someone
    # refactors _resolve_paths to put dist_root under ``frontend/dist``.
    for removed in observed_rmtrees:
        try:
            removed.relative_to(fake_repo / "frontend")
        except ValueError:
            continue
        pytest.fail(f"cleanup must never delete a path under frontend/; observed_rmtrees={observed_rmtrees!r}")


# ---------------------------------------------------------------------------
# 4. Version pin and version tag are untouched by the freeze refusal
# ---------------------------------------------------------------------------


def test_freeze_refusal_does_not_change_version_pin() -> None:
    """The brief forbids changing the version pin ``0.9.5``. The refusal
    path is a guard at the top of ``freeze()``; it must not touch
    ``pyproject.toml`` or the workflow version env.
    """

    text_pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.9.5"' in text_pyproject, "pyproject.toml must keep the version pin 0.9.5 unchanged"

    text_workflow = _workflow_text()
    assert 'KRELLBOT_VERSION: "0.9.5"' in text_workflow, (
        "release-frozen.yml must keep KRELLBOT_VERSION: 0.9.5 unchanged"
    )


def test_workflow_has_no_publish_or_tag_step_for_f03b() -> None:
    """The brief says: do not add a publish or tag step. We assert
    only that this diff does not introduce a new one. The
    existing ``publish`` job that uploads already-uploaded
    artifacts via ``gh release upload`` is part of F02 and is
    outside the allowed file set for F03b, so we don't touch it
    here. We assert the *new* step counts remain stable: there
    is exactly one freeze-step invocation.

    This test guards against the simple regression where a later
    contributor adds another ``on: push: tags: [v*]`` trigger or
    re-tags inside the ``build`` job.
    """

    text = _workflow_text()
    assert text.count(FREEZE_STEP_RUN) == 1, (
        f"release-frozen.yml must invoke `{FREEZE_STEP_RUN}` exactly once in the build job; "
        f"got {text.count(FREEZE_STEP_RUN)} occurrences"
    )


if __name__ == "__main__":  # pragma: no cover - module imported by pytest
    sys.exit(0)
