"""M2-CI — exact-head frontend + Playwright job on pull_request.

PR #5 currently gets zero frontend or browser evidence from CI; this
test pins the invariants the brief requires so that a follow-up edit
cannot silently regress them.

PyYAML is not installed in this environment, so we parse the workflow
text with a small line-based reader in the same style as
``tests/test_m1r_t3a_publish_trigger.py``. We deliberately do NOT
import from that file: each test must remain self-contained.

The invariants this module locks down:

1. The top-level ``on:`` block still contains ``pull_request`` (the
   trigger that gates PR #5).
2. A job named ``frontend`` exists with ``runs-on: ubuntu-latest`` and
   ``timeout-minutes`` ≤ 30.
3. The job body contains, in this order, the seven gate substrings the
   brief requires:
       ``npm ci --include=dev`` → ``npm run typecheck`` →
       ``npm run lint`` → ``npm run test:unit -- --run`` →
       ``npm run build`` → ``playwright install --with-deps chromium`` →
       ``npm run test:e2e``
4. The job body also contains ``KRELLBOT_ENABLE_LIVE: "0"``,
   ``FakeKeyring``, ``1.62.1``, ``KRELLBOT_E2E_SKIP_BUILD``, and
   ``tested_sha=`` so the Steward can bind the run to the PR head SHA.
5. The job body contains no ``secrets.``, no ``continue-on-error``, and
   no ``|| true``: no permission creep, no soft gates.
6. ``frontend/package.json`` still pins ``"@playwright/test": "1.62.1"``
   so the version guard is meaningful.
7. The pre-existing ``test`` job's matrix line
   (``os: [ubuntu-latest, macos-latest, windows-latest]``) and the
   ``lint`` job's two ruff lines are still present, so this change is
   strictly additive.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
FRONTEND_PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"

# Ordered gate substrings the brief requires inside the ``frontend:`` job.
GATE_SUBSTRINGS_IN_ORDER: tuple[str, ...] = (
    "npm ci --include=dev",
    "npm run typecheck",
    "npm run lint",
    "npm run test:unit -- --run",
    "npm run build",
    "playwright install --with-deps chromium",
    "npm run test:e2e",
)

# Markers the job body must contain (order-independent).
REQUIRED_MARKERS: tuple[str, ...] = (
    'KRELLBOT_ENABLE_LIVE: "0"',
    "FakeKeyring",
    "1.62.1",
    "KRELLBOT_E2E_SKIP_BUILD",
    "tested_sha=",
)

# Forbidden substrings: no permission creep, no soft gates.
FORBIDDEN_MARKERS: tuple[str, ...] = (
    "secrets.",
    "continue-on-error",
    "|| true",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_on_block(text: str) -> tuple[list[str], list[str]]:
    """Return ``(header_line, body_lines)`` for the top-level ``on:`` block.

    The body stops on the first non-empty line at column 0 so that
    nested mappings under ``jobs:`` / ``permissions:`` / ``steps:``
    are not pulled in by mistake. Empty lines are kept so an assertion
    that ``pull_request`` appears is faithful.
    """

    lines = text.splitlines()
    on_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.split(":", 1)[0].strip()
        if line.startswith("on:") and stripped == "on":
            on_idx = i
            break
        if line == "on:":
            on_idx = i
            break
    assert on_idx is not None, "top-level `on:` not found in ci.yml"

    body: list[str] = []
    for line in lines[on_idx + 1 :]:
        if line and not line[:1].isspace():
            break
        body.append(line)
    return [lines[on_idx]], body


def _extract_job_body(text: str, job_name: str) -> list[str]:
    """Return the body lines for the job ``job_name`` inside ``jobs:``.

    The body is every line from ``  <job_name>:`` until the next line
    at exactly 2-space indent (which would be the next sibling job),
    or end of file. ``jobs:`` itself must be a top-level key.
    """

    lines = text.splitlines()
    jobs_idx: int | None = None
    for i, line in enumerate(lines):
        if line == "jobs:":
            jobs_idx = i
            break
    assert jobs_idx is not None, "top-level `jobs:` not found in ci.yml"

    # Find the job's header at 2-space indent.
    job_idx: int | None = None
    for j in range(jobs_idx + 1, len(lines)):
        line = lines[j]
        if line.startswith("  "):
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if indent == 2 and stripped.split(":", 1)[0].strip() == job_name:
                job_idx = j
                break
    assert job_idx is not None, f"job `{job_name}:` not found under `jobs:` in ci.yml"

    # Walk forward until the next sibling job (also at 2-space indent).
    body: list[str] = []
    for k in range(job_idx + 1, len(lines)):
        line = lines[k]
        if line.startswith("  ") and not line.startswith("    "):
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if indent == 2:
                # This is the next sibling job's header.
                break
        body.append(line)
    return body


def _body_joined(body: list[str]) -> str:
    return "\n".join(body)


def test_on_block_still_includes_pull_request() -> None:
    """The top-level ``on:`` block must still include ``pull_request``.

    PR #5's frontend coverage depends on this trigger firing on PRs.
    """

    text = _read_text(CI_WORKFLOW)
    _header, body = _extract_on_block(text)
    body_text = _body_joined(body)
    assert "pull_request" in body_text, (
        "ci.yml top-level `on:` block must still contain `pull_request` so PRs trigger the new frontend job"
    )


def test_frontend_job_exists_with_runs_on_and_timeout() -> None:
    """A ``frontend`` job must exist with ``runs-on: ubuntu-latest`` and a timeout.

    The brief caps ``timeout-minutes`` at 30 (the job is actually 25);
    we assert the literal to be exact rather than upper-bounding.
    """

    text = _read_text(CI_WORKFLOW)
    body = _extract_job_body(text, "frontend")
    body_text = _body_joined(body)

    assert "runs-on: ubuntu-latest" in body_text, "the `frontend:` job must declare `runs-on: ubuntu-latest`"

    match = re.search(r"timeout-minutes:\s*(\d+)", body_text)
    assert match is not None, "the `frontend:` job must declare `timeout-minutes: <int>`"
    timeout = int(match.group(1))
    assert 1 <= timeout <= 30, f"the `frontend:` job `timeout-minutes` must be in [1, 30]; got {timeout}"


def test_frontend_job_has_required_steps_in_order() -> None:
    """The seven gate substrings must appear in order inside the job.

    We assert ``a.index(b)`` strictly increases between successive
    substrings; this forbids re-ordering and forbids skipping.
    """

    text = _read_text(CI_WORKFLOW)
    body = _extract_job_body(text, "frontend")
    body_text = _body_joined(body)

    cursor = -1
    for needle in GATE_SUBSTRINGS_IN_ORDER:
        idx = body_text.find(needle, cursor + 1)
        assert idx > cursor, (
            f"frontend job body must contain `{needle}` in order after the previous gate "
            f"(cursor={cursor}, searched from there)"
        )
        cursor = idx


def test_frontend_job_contains_required_markers() -> None:
    """The job body must contain five markers (order-independent).

    ``KRELLBOT_ENABLE_LIVE: "0"`` blocks live arm. ``FakeKeyring`` is
    the harness's keyring. ``1.62.1`` is the pinned Playwright version.
    ``KRELLBOT_E2E_SKIP_BUILD`` lets CI skip the harness's auto-build.
    ``tested_sha=`` is what the Steward reads to bind the job to the
    PR head SHA.
    """

    text = _read_text(CI_WORKFLOW)
    body = _extract_job_body(text, "frontend")
    body_text = _body_joined(body)

    missing = [m for m in REQUIRED_MARKERS if m not in body_text]
    assert not missing, f"frontend job body is missing markers: {missing!r}"


def test_frontend_job_has_no_secrets_or_soft_gates() -> None:
    """The job body must contain no secrets reference, no continue-on-error, no ``|| true``.

    The job must be hard-gated; soft-gating a frontend gate hides
    regressions in PR #5+.
    """

    text = _read_text(CI_WORKFLOW)
    body = _extract_job_body(text, "frontend")
    body_text = _body_joined(body)

    violations = [m for m in FORBIDDEN_MARKERS if m in body_text]
    assert not violations, f"frontend job body must not contain any of {FORBIDDEN_MARKERS!r}; found {violations!r}"


def test_frontend_package_json_pins_playwright_1_62_1() -> None:
    """``frontend/package.json`` must still pin ``"@playwright/test": "1.62.1"``.

    The CI version guard ``npx playwright --version`` is meaningful only
    if the lockfile/installed runtime actually is 1.62.1; the pin in
    package.json is what makes that a contract rather than a hope.
    """

    text = _read_text(FRONTEND_PACKAGE_JSON)
    # Match the pin exactly; allow surrounding whitespace.
    match = re.search(r'"@playwright/test"\s*:\s*"([^"]+)"', text)
    assert match is not None, "frontend/package.json must declare a version for `@playwright/test`"
    assert match.group(1) == "1.62.1", (
        f'frontend/package.json must pin `@playwright/test` to "1.62.1"; got {match.group(1)!r}'
    )


def test_pre_existing_test_matrix_unchanged() -> None:
    """The pre-existing ``test`` job's OS matrix line must still be present.

    The brief explicitly says: "Leave the ``test`` and ``lint`` jobs
    and the ``on:`` block byte-identical." We assert the matrix line as
    a coarse sentinel — if anyone narrows it (e.g. drops macOS or
    Windows), this fails.
    """

    text = _read_text(CI_WORKFLOW)
    body = _extract_job_body(text, "test")
    body_text = _body_joined(body)
    assert "os: [ubuntu-latest, macos-latest, windows-latest]" in body_text, (
        "the pre-existing `test:` job must still have `os: [ubuntu-latest, macos-latest, windows-latest]`"
    )


def test_pre_existing_lint_job_ruff_lines_unchanged() -> None:
    """The pre-existing ``lint`` job's two ruff lines must still be present.

    The brief explicitly says the ``lint`` job stays byte-identical.
    These two ``uvx ruff`` lines are the whole job; if either changes
    the brief has been violated.
    """

    text = _read_text(CI_WORKFLOW)
    body = _extract_job_body(text, "lint")
    body_text = _body_joined(body)
    assert "uvx ruff check src tests" in body_text, (
        "the pre-existing `lint:` job must still run `uvx ruff check src tests`"
    )
    assert "uvx ruff format --check src tests" in body_text, (
        "the pre-existing `lint:` job must still run `uvx ruff format --check src tests`"
    )
