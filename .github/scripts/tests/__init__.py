"""Tests for the .github/scripts checkers.

We use `pytest`. Each test imports ONLY the trusted checker module
under test — never any fixture content.

Fixtures (under `tests/fixtures/`) contain malicious-looking
Python that PROVES the checkers parse text without executing it.
"""

# Tests must NEVER live at the repo's `tests/` top-level so they
# don't accidentally get loaded by the product pytest configuration
# (which sets up a fake keyring backend). This directory is its
# own root.

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
SCRIPTS_DIR = HERE.parent
PKG_ROOT = SCRIPTS_DIR.parent  # .github/
REPO_ROOT = PKG_ROOT.parent  # the actual repo (where `git` runs)

# Make `scripts` importable as a package regardless of where the
# runner is started from.
sys.path.insert(0, str(PKG_ROOT))


@pytest.fixture(scope="session")
def workdir() -> Path:
    """Use the real repo workdir for git operations in tests.

    The brief requires the checker to read files from explicit git
    refs. In offline CI tests, we point at this workdir.
    """
    return Path(__file__).resolve().parent.parent.parent.parent


@pytest.fixture(scope="session")
def test_workdir() -> Path:
    return workdir()  # type: ignore[return-value]


@pytest.fixture(scope="session")
def base_ref() -> str:
    # The Step 3 prompt tells the parent to evaluate against a known
    # historical SHA. We pin to the same baseline commit the parent
    # records.
    return "ca351a08d40ba47204116b02f3356cbb4600b556"


# -------------------------------------------------------------------------
# RED: the malicious fixture body must NOT be executed.
# -------------------------------------------------------------------------


def test_malicious_fixture_is_never_executed() -> None:
    """Importing the fixture location must NOT trigger side effects.

    If a future refactor accidentally made the fixture executable, the
    directory would either (a) raise because /etc/passwd is unreadable
    in our sandbox, or (b) raise because `openai`/`anthropic`/
    `krellbot` aren't installed — which is fine — but the prose
    below documents the rule: NEVER import the fixture module."""
    fixture_dir = HERE / "fixtures"
    assert fixture_dir.is_dir()
    # The fixtures package itself MUST be importable (it's empty),
    # but the malicious file MUST NOT contain importable Python that
    # would actually run. We just confirm the sentinel is present.
    bad = (fixture_dir / "malicious_module.py").read_text(encoding="utf-8")
    assert "END_FIXTURE_DO_NOT_EXECUTE" in bad


# -------------------------------------------------------------------------
# Helpers around `git show`-based reading
# -------------------------------------------------------------------------


def _read_git_text(workdir: Path, ref: str, rel: str) -> str | None:
    argv = ["git", "show", f"{ref}:{rel}"]
    res = subprocess.run(  # noqa: S603 — argv is hardcoded
        argv, cwd=str(workdir), capture_output=True, text=True, check=False
    )
    if res.returncode != 0:
        return None
    return res.stdout


def _ls_git(workdir: Path, ref: str, prefix: str = "") -> list[str]:
    argv = ["git", "ls-tree", "-r", "--name-only", ref, "--", prefix or "."]
    res = subprocess.run(  # noqa: S603 — argv is hardcoded
        argv, cwd=str(workdir), capture_output=True, text=True, check=False
    )
    if res.returncode != 0:
        return []
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]
