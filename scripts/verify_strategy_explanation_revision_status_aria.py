#!/usr/bin/env python3
"""Offline source-contract verification; not audible screen-reader qualification."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "673d67bc14197a2a41176cdda0fbd3711ec8c643"
COMPONENT = "frontend/src/features/strategies/StrategyExplanation.tsx"
EXPLAIN_PACK = "frontend/src/features/strategies/explainPack.ts"
OUTPUT = ROOT / "tests_tmp" / "strategy-explanation-revision-status-aria" / "results.json"
REQUIRED = (
    "source_read",
    "revision_paragraph_preserved",
    "revision_status_role",
    "revision_polite_live_region",
    "revision_atomic_announcement",
    "saved_label_copy_preserved",
    "parent_region_unchanged",
    "explain_pack_import_unchanged",
    "explain_pack_and_saved_status_unchanged",
    "only_requested_attributes_added",
)


def baseline(path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{BASE}:{path}"], cwd=ROOT, text=True, timeout=10,
    )


def extract(pattern: str, source: str) -> str:
    match = re.search(pattern, source, re.DOTALL)
    if match is None:
        raise AssertionError(f"Missing source pattern: {pattern}")
    return match.group(0)


def main() -> int:
    checks = dict.fromkeys(REQUIRED, False)
    result = {
        "base_sha": BASE,
        "source": COMPONENT,
        "required_assertions": checks,
        "limits": "Source contract only; React transitions are covered by the companion Vitest test.",
    }
    try:
        source = (ROOT / COMPONENT).read_text(encoding="utf-8")
        original = baseline(COMPONENT)
        checks["source_read"] = bool(source and original)
        revision_pattern = (
            r'<p\b[^>]*\bdata-testid="strategy-explanation-revision"[^>]*>'
            r'\s*\{savedLabel\}\s*</p>'
        )
        revision = extract(revision_pattern, source)
        checks["revision_paragraph_preserved"] = (
            source.count('data-testid="strategy-explanation-revision"') == 1
            and 'className="kbot-feature__strategy-explanation-revision"' in revision
        )
        for name, attribute in (
            ("revision_status_role", 'role="status"'),
            ("revision_polite_live_region", 'aria-live="polite"'),
            ("revision_atomic_announcement", 'aria-atomic="true"'),
        ):
            checks[name] = attribute in revision.split(">", 1)[0]

        label_pattern = r'const savedLabel\s*=.*?;'
        label = extract(label_pattern, source)
        checks["saved_label_copy_preserved"] = (
            label == extract(label_pattern, original)
            and 'explanation.savedStatus === "saved"' in label
            and '`Saved revision ${explanation.revisionId}`' in label
            and '"No saved revision yet (showing stored draft content as unsaved)"' in label
        )
        section = extract(r'<section\b[^>]*>', source)
        checks["parent_region_unchanged"] = (
            section == extract(r'<section\b[^>]*>', original)
            and 'role="region"' in section
            and 'aria-label="Strategy explanation"' in section
        )
        import_pattern = r'import\s*\{[^}]*\}\s*from "\./explainPack";'
        import_statement = extract(import_pattern, source)
        checks["explain_pack_import_unchanged"] = (
            import_statement == extract(import_pattern, original)
            and re.search(r'\bexplainPack\s*,\s*NOT_SUPPLIED\s*,', import_statement) is not None
        )
        checks["explain_pack_and_saved_status_unchanged"] = (
            (ROOT / EXPLAIN_PACK).read_text(encoding="utf-8") == baseline(EXPLAIN_PACK)
        )
        stripped_revision = revision
        for attribute in ('role="status"', 'aria-live="polite"', 'aria-atomic="true"'):
            stripped_revision = stripped_revision.replace(f"          {attribute}\n", "", 1)
        checks["only_requested_attributes_added"] = (
            source.replace(revision, stripped_revision, 1) == original
        )
    except (OSError, subprocess.SubprocessError, AssertionError) as error:
        result["failure"] = f"{type(error).__name__}: {error}"

    result["qualified"] = all(checks.values())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"Results: {OUTPUT.relative_to(ROOT)}")
    return 0 if result["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
