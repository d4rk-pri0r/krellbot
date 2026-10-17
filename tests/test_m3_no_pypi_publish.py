"""M3-PUB — no PyPI publish surface anywhere under ``.github/``.

The 2026-09-29 20:15 PyPI = NO decision retires the PyPI publish
workflow. After this change lands, no workflow file or composite
action file may:

1. Reference the ``pypa/gh-action-pypi-publish`` action (substring,
   case-insensitive).
2. Declare a top-level ``environment: pypi`` value (line is exactly
   ``environment: pypi``, optionally quoted, case-insensitive).
3. Map an unnamed ``environment:`` block onto a ``name: pypi`` key
   within the next three lines.
4. Invoke ``twine upload``, ``uv publish``, ``upload.pypi.org`` or
   ``test.pypi.org`` (substring, case-insensitive).
5. Be named ``publish.yml`` or ``pypi*.yml`` under ``.github/workflows/``.

The module also ships a self-test that exercises the detector against a
fixture text containing the two most common violations, so the checker
cannot quietly become a no-op.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
ACTIONS_DIR = REPO_ROOT / ".github" / "actions"

# Rule 2: ``environment: pypi`` as a single-line value, optionally quoted.
_ENV_PYPI = re.compile(r"^\s*environment:\s*['\"]?pypi['\"]?\s*$", re.IGNORECASE)
# Rule 3 (left half): an open ``environment:`` block with no inline value.
_ENV_OPEN = re.compile(r"^\s*environment:\s*$", re.IGNORECASE)
# Rule 3 (right half): a ``name: pypi`` key (case-insensitive, optional quote).
_NAME_PYPI = re.compile(r"^\s*name:\s*['\"]?pypi['\"]?\s*$", re.IGNORECASE)

# Rule 4: other PyPI-publishing tools/hosts.
_PYPI_TOKENS: tuple[str, ...] = (
    "twine upload",
    "uv publish",
    "upload.pypi.org",
    "test.pypi.org",
)


def _scan_workflow_files() -> list[Path]:
    """Return workflow YAML files under ``.github/workflows/`` (both extensions)."""
    if not WORKFLOWS_DIR.is_dir():
        return []
    files = list(WORKFLOWS_DIR.glob("*.yml")) + list(WORKFLOWS_DIR.glob("*.yaml"))
    return sorted(files)


def _scan_action_files() -> list[Path]:
    """Return composite-action YAML files under ``.github/actions/`` (recursive)."""
    if not ACTIONS_DIR.is_dir():
        return []
    return sorted(ACTIONS_DIR.rglob("*.yml"))


def _violations(text: str) -> list[str]:
    """Return the list of PyPI-publish violations found in ``text``.

    Each violation is a short stable string. The list is empty when the
    text is clean. The function is module-level so the self-test can
    call it directly without going through the filesystem.
    """

    violations: list[str] = []

    if "pypa/gh-action-pypi-publish" in text.lower():
        violations.append("contains pypa/gh-action-pypi-publish")

    for lineno, line in enumerate(text.splitlines(), start=1):
        if _ENV_PYPI.match(line):
            violations.append(f"line {lineno}: declares environment: pypi")

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not _ENV_OPEN.match(line):
            continue
        window = lines[i + 1 : i + 4]
        for offset, wline in enumerate(window, start=1):
            if _NAME_PYPI.match(wline):
                violations.append(f"line {i + 1}: environment mapping names 'pypi' (within {offset} line(s))")
                break

    lowered = text.lower()
    for token in _PYPI_TOKENS:
        if token in lowered:
            violations.append(f"contains {token!r}")

    return violations


def _is_forbidden_workflow_name(name: str) -> bool:
    """Rule 5: ``publish.yml`` or ``pypi*.yml`` are forbidden."""
    return name == "publish.yml" or (name.startswith("pypi") and name.endswith(".yml"))


SCAN_TARGETS: list[Path] = _scan_workflow_files() + _scan_action_files()
assert SCAN_TARGETS, "expected at least one file under .github/workflows/; the scan must not pass vacuously"


@pytest.mark.parametrize(
    "path",
    SCAN_TARGETS,
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_no_pypi_publish_in_file(path: Path) -> None:
    """Every scanned workflow/action file must report zero violations."""
    text = path.read_text(encoding="utf-8")
    violations = _violations(text)
    assert not violations, f"{path.relative_to(REPO_ROOT)} must not publish to PyPI; violations: {violations}"


def test_no_forbidden_workflow_filenames() -> None:
    """No workflow file may be named ``publish.yml`` or ``pypi*.yml``."""
    forbidden = [p.name for p in _scan_workflow_files() if _is_forbidden_workflow_name(p.name)]
    assert not forbidden, f"forbidden PyPI workflow names found: {forbidden!r}"


def test_detector_flags_known_violations(tmp_path: Path) -> None:
    """Self-test: the detector must flag both known violations in a temp file.

    The fixture combines a ``pypa/gh-action-pypi-publish`` action and an
    inline ``environment: pypi`` line. The detector has to surface both,
    proving it is wired correctly and is not a silent no-op.
    """
    sample = tmp_path / "sniff.yml"
    sample.write_text(
        "jobs:\n  pypi:\n    environment: pypi\n    steps:\n      - uses: pypa/gh-action-pypi-publish@release/v1\n",
        encoding="utf-8",
    )
    violations = _violations(sample.read_text(encoding="utf-8"))
    joined = " | ".join(violations)
    assert "pypa/gh-action-pypi-publish" in joined, f"detector missed the pypa publish action; got {violations!r}"
    assert "environment: pypi" in joined, f"detector missed the `environment: pypi` line; got {violations!r}"
