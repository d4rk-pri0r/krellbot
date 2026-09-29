"""M1R-T3A — make the preview tag safe.

PyPI publication is undecided (see decisions.md), so a ``v*`` tag must
not queue a PyPI run. This test pins two invariants and one new
invariant:

1. ``.github/workflows/publish.yml`` is manual-dispatch only. The
   ``on:`` block's first-level keys are exactly ``{workflow_dispatch}``;
   ``tags`` and ``push`` do not appear anywhere inside that block. The
   pypa publish step itself is preserved, so an operator can still
   trigger the publish job by hand.
2. ``.github/workflows/release-frozen.yml`` still fires on ``v*`` tags
   and its publish job still gates on ``refs/tags/v`` and passes
   ``--prerelease`` to ``gh release create``.
3. The engine version literal (``0.9.5``) agrees across the package
   metadata, the lockfile, the package ``__version__``, and the
   workflow's ``KRELLBOT_VERSION:`` env.

PyYAML is not installed in this environment, so we parse workflow text
with a small line-based reader instead of ``yaml.safe_load``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLISH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-frozen.yml"
PYPROJECT = REPO_ROOT / "pyproject.toml"
UV_LOCK = REPO_ROOT / "uv.lock"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_on_block(text: str) -> tuple[list[str], list[str]]:
    """Return ``(header_line, body_lines)`` for the top-level ``on:`` block.

    The header is the single ``on:`` line. The body is every line after
    it until the next line whose first non-whitespace character is at
    column 0 (i.e. a new top-level key). We deliberately stop on the
    first zero-indentation line so that nested ``jobs:`` /
    ``permissions:`` / ``steps:`` blocks are not pulled into the
    ``on:`` block by mistake.
    """

    lines = text.splitlines()
    on_idx: int | None = None
    for i, line in enumerate(lines):
        if line == "on:" or line.startswith("on:"):
            # Match the top-level scalar form (``on:`` or ``on: push:``).
            # A indented ``on:`` inside another mapping cannot match
            # ``line == "on:"`` because of leading whitespace, and a
            # key like ``actions:`` cannot match ``startswith("on:")``
            # without the trailing colon.
            stripped = line.split(":", 1)[0].strip()
            if stripped == "on":
                on_idx = i
                break
    assert on_idx is not None, "top-level `on:` not found in workflow"

    body: list[str] = []
    for line in lines[on_idx + 1 :]:
        # A line is "end of block" when it has no leading whitespace
        # AND is not empty. Empty lines inside the block are kept so
        # the assertion that "tags" does not appear is faithful.
        if line and not line[:1].isspace():
            break
        body.append(line)
    return [lines[on_idx]], body


def _first_level_keys(body: list[str]) -> set[str]:
    """Collect the first-level keys of the ``on:`` mapping.

    A first-level key is a non-empty, non-comment line whose first
    non-whitespace character is in column 2 (i.e. one indent step
    inside ``on:``) and whose first token ends with ``:``. Inline
    scalars like ``on: push:`` are handled by ``_extract_on_block``
    already; here we only need the body shape.
    """

    keys: set[str] = set()
    for raw in body:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        # Compute the indentation of the first non-whitespace char.
        stripped = raw.lstrip()
        indent = len(raw) - len(stripped)
        if indent != 2:
            continue
        # The key is everything up to the first ``:``.
        if ":" not in stripped:
            continue
        key = stripped.split(":", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def test_publish_workflow_is_manual_dispatch_only() -> None:
    """``publish.yml`` must be ``workflow_dispatch`` only.

    No ``push:`` trigger, no ``tags:`` matcher, and the
    pypa publish step must still be in the file so manual dispatch
    remains functional.
    """

    text = _read_text(PUBLISH_WORKFLOW)
    _header, body = _extract_on_block(text)

    keys = _first_level_keys(body)
    assert keys == {"workflow_dispatch"}, f"publish.yml `on:` must be {{workflow_dispatch}}; got {sorted(keys)!r}"

    body_text = "\n".join(body)
    assert "tags" not in body_text, (
        "publish.yml `on:` block must not contain `tags`; a v* tag must not queue a PyPI run"
    )
    assert "push" not in body_text, (
        "publish.yml `on:` block must not contain `push`; publishing must be manual-dispatch only"
    )

    # Sanity: the job itself was not deleted. Manual dispatch would
    # not work without the pypa publish step.
    assert "pypa/gh-action-pypi-publish" in text, (
        "publish.yml must still reference pypa/gh-action-pypi-publish; the publish job was deleted"
    )


def test_release_frozen_still_fires_on_v_tags() -> None:
    """``release-frozen.yml`` must still trigger on ``v*`` tags.

    The brief narrows ``publish.yml``; it does not narrow
    ``release-frozen.yml``. The ``on:`` block still contains
    ``push: tags: ["v*"]`` (or equivalent) and the ``publish`` job
    still gates on ``startsWith(github.ref, 'refs/tags/v')`` and
    passes ``--prerelease`` to ``gh release create``.
    """

    text = _read_text(RELEASE_WORKFLOW)
    _header, body = _extract_on_block(text)
    body_text = "\n".join(body)

    assert "push:" in body_text, (
        "release-frozen.yml `on:` block must still declare `push:` so v* tags build and publish release assets"
    )
    # tags matcher may be quoted as ``v*`` or unquoted; accept both.
    assert re.search(r"tags:\s*\[\s*[\"']?v\*[\"']?\s*\]", body_text), (
        "release-frozen.yml `on:` block must still match `v*` tags"
    )

    assert "startsWith(github.ref, 'refs/tags/v')" in text, (
        "release-frozen.yml publish job must still gate on `startsWith(github.ref, 'refs/tags/v')`"
    )
    assert "--prerelease" in text, (
        "release-frozen.yml publish job must still pass `--prerelease` to `gh release create`"
    )


def test_version_literals_agree() -> None:
    """All four engine-version literals must equal ``"0.9.5"``.

    The workstation preview tag is ``v0.9.5``; the engine literal
    moves with it. Any other version in any of these four files
    fails the test so the diff cannot ship with a stale pin.
    """

    pyproject = _read_text(PYPROJECT)
    match_pyproject = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert match_pyproject is not None, 'pyproject.toml must declare `version = "..."`'
    assert match_pyproject.group(1) == "0.9.5", (
        f"pyproject.toml version must be 0.9.5; got {match_pyproject.group(1)!r}"
    )

    # Read the krellbot __version__ from the package source.
    import krellbot  # local import keeps this test self-contained

    assert krellbot.__version__ == "0.9.5", f"krellbot.__version__ must be 0.9.5; got {krellbot.__version__!r}"

    lock = _read_text(UV_LOCK)
    match_lock = re.search(
        r'\[\[package\]\]\s*\nname\s*=\s*"krellbot"\s*\nversion\s*=\s*"([^"]+)"',
        lock,
    )
    assert match_lock is not None, (
        'uv.lock must contain a `[[package]] name = "krellbot"` entry with a `version = "..."` line'
    )
    assert match_lock.group(1) == "0.9.5", f"uv.lock krellbot version must be 0.9.5; got {match_lock.group(1)!r}"

    workflow = _read_text(RELEASE_WORKFLOW)
    match_wf = re.search(r'^\s*KRELLBOT_VERSION:\s*"([^"]+)"', workflow, re.MULTILINE)
    assert match_wf is not None, 'release-frozen.yml must declare `KRELLBOT_VERSION: "..."`'
    assert match_wf.group(1) == "0.9.5", f"release-frozen.yml KRELLBOT_VERSION must be 0.9.5; got {match_wf.group(1)!r}"
