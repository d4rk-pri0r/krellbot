"""Static invariant lints and test-integrity guard (Phase 2, Step 3).

This package is invoked from CI as plain scripts:

    python -m .github.scripts.invariants --base REF --head REF [--allowlist PATH] [--json PATH]
    python -m .github.scripts.test_integrity --base REF --head REF --repo OWNER/REPO --pr N [--json PATH]

The scripts parse the product's source tree and the PR diff as DATA.
They never import or exec any code they are checking. They have no
third-party dependencies — stdlib only — and they ship with tests
in `.github/scripts/tests/` that exercise the checkers against hand-
crafted fixtures and never against the actual product source tree.

Trust boundaries are enforced in two places:
 1. The CI workflow fetches the checker from the PR's base with
    `git show origin/<base>:<path>`, so a malicious PR cannot weaken
    the checker by editing it.
 2. The checker refuses any path that resolves out of the worktree, any
    shell that is not `sh -c`, and any subprocess argv that is not a
    list of strings.
"""

__all__: list[str] = []
