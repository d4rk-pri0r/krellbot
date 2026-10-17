#!/usr/bin/env python3
"""Offline source + runtime verification for the PackLibrary filter-keyboard aria slice.

Checks that frontend/src/features/packs/PackLibrary.tsx carries the new
aria-keyshortcuts / aria-label annotations on the existing pack-library filter
controls (search input, bucket select, conditional clear button) without
disturbing any pre-existing surface, then runs the focused Vitest suite,
typecheck and build. AX semantics are evidence for assistive tech, not a claim
of audible screen-reader output or of a real keychord handler being added.
Uses only the standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SOURCE = "frontend/src/features/packs/PackLibrary.tsx"
BASE = "d285b94ddf5c98e0a26d8d020c406b6b3bc4041b"
NEW_SPEC = "src/features/packs/PackLibrary.filterKeyboard.test.tsx"
TESTS = (
    NEW_SPEC,
    "src/features/packs/PackLibrary.test.tsx",
    "src/features/packs/PackLibrary.signal.test.tsx",
    "src/features/packs/PackLibrary.ariaBusy.test.tsx",
    "src/features/packs/PackLibrary.clipboardFailure.test.tsx",
    "src/features/packs/PackLibrary.rowAriaLabel.test.tsx",
)
PRESERVED_FILES = tuple(f"frontend/{test}" for test in TESTS[1:]) + (
    "frontend/src/features/packs/client.ts",
    "frontend/src/features/packs/PackLibrary.signal.css",
    "frontend/src/shell/AppHome.tsx",
)
REQUIRED = (
    "source_read", "search_aria_keyshortcuts", "search_aria_uniqueness",
    "bucket_aria_keyshortcuts", "bucket_aria_uniqueness", "clear_aria_keyshortcuts",
    "clear_aria_label", "clear_visible_literal", "existing_refresh_surface_unchanged",
    "existing_testids_only_addition", "client_and_css_unchanged", "runtime_tests",
    "typecheck_no_slice_errors", "build", "verification_commands_recorded",
)

SEARCH_KEYSHORTCUTS = 'aria-keyshortcuts="Control+F Meta+F"'
BUCKET_KEYSHORTCUTS = 'aria-keyshortcuts="Control+Alt+B Meta+Alt+B"'
CLEAR_KEYSHORTCUTS = 'aria-keyshortcuts="Escape"'
CLEAR_ARIA_LABEL = 'aria-label="Clear pack-library search and bucket filter"'
CLEAR_LITERAL = "Clear search &amp; filter"


def run(argv: list[str], directory: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=directory, text=True, capture_output=True,
                          timeout=timeout, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir or Path(tempfile.mkdtemp(prefix="pack-library-filter-keyboard-"))
    out.mkdir(parents=True, exist_ok=True)
    assertions = dict.fromkeys(REQUIRED, False)
    commands: list[dict[str, object]] = []
    results: dict[str, object] = {
        "qualified": False,
        "required_assertions": assertions,
        "baseline": BASE,
        "source_path": SOURCE,
        "verification_commands": commands,
    }

    def record(name: str, cwd: str, argv: list[str], process: subprocess.CompletedProcess[str]) -> int:
        (out / f"{name}.log").write_text(process.stdout + process.stderr)
        commands.append({"name": name, "cwd": cwd, "argv": argv,
                         "exit": process.returncode})
        return process.returncode

    try:
        def git(*a: str) -> str:
            return subprocess.run(
                ["git", *a], cwd=ROOT, text=True, capture_output=True, check=False
            ).stdout

        def block(text: str, pattern: str) -> str:
            match = re.search(pattern, text, re.S)
            assert match, f"canonical block not found: {pattern}"
            return match.group()

        source = (FRONTEND / "src/features/packs/PackLibrary.tsx").read_text()
        baseline = git("show", f"{BASE}:{SOURCE}")
        results["head"] = git("rev-parse", "HEAD").strip()
        results["source_sha256"] = hashlib.sha256(source.encode()).hexdigest()
        assertions["source_read"] = bool(baseline) and bool(source)

        search_pattern = r'<input\s+id="pack-library-search".*?/>'
        bucket_pattern = r'<select\s+id="pack-library-bucket".*?</select>'
        clear_pattern = (
            r'<button\s+type="button"\s+className="kbot-pack-library__clear".*?</button>'
        )
        refresh_pattern = (
            r'<button\s+type="button"\s+className="kbot-pack-library__refresh".*?</button>'
        )
        new_search = block(source, search_pattern)
        old_search = block(baseline, search_pattern)
        new_bucket = block(source, bucket_pattern)
        old_bucket = block(baseline, bucket_pattern)
        new_clear = block(source, clear_pattern)
        old_clear = block(baseline, clear_pattern)

        # (A) Search input: the documented focus chord is announced and the
        # existing control identity/value/handler stay byte-equal.
        assertions["search_aria_keyshortcuts"] = (
            SEARCH_KEYSHORTCUTS in new_search
            and SEARCH_KEYSHORTCUTS not in old_search
            and all(value in new_search for value in (
                'id="pack-library-search"', 'type="search"',
                'className="kbot-pack-library__search"',
                'data-testid="pack-library-search"',
                'placeholder="pack_id, version or permission"',
                "value={query}", "onChange={(event) => {", "setQuery(event.target.value);",
            ))
            and all(value in new_search for value in old_search.replace("\r", "").splitlines())
            and 'aria-label' not in new_search
        )
        assertions["search_aria_uniqueness"] = (
            source.count(SEARCH_KEYSHORTCUTS) == 1
            and len(re.findall(r'(?<![\w-])id="pack-library-search"', source)) == 1
            and source.count('<span className="kbot-pack-library__search-caption">Search packs</span>') == 1
            and '<label className="kbot-pack-library__search-label" htmlFor="pack-library-search">' in source
        )

        # (B) Bucket select: its chord is distinct from the alerts (Alt+S),
        # last-runs venue (Alt+V) and last-runs status (Alt+T) shortcuts.
        assertions["bucket_aria_keyshortcuts"] = (
            BUCKET_KEYSHORTCUTS in new_bucket
            and BUCKET_KEYSHORTCUTS not in old_bucket
            and all(chord not in BUCKET_KEYSHORTCUTS for chord in (
                "Alt+S", "Alt+V", "Alt+T"))
            and all(value in new_bucket for value in (
                'id="pack-library-bucket"',
                'className="kbot-pack-library__bucket-select"',
                'data-testid="pack-library-bucket-select"',
                "value={bucketFilter}", "onChange={(event) => {",
                "setBucketFilter(event.target.value);",
                '<option value={ALL_BUCKETS}>All buckets</option>',
            ))
        )
        assertions["bucket_aria_uniqueness"] = (
            source.count(BUCKET_KEYSHORTCUTS) == 1
            and len(re.findall(r'(?<![\w-])id="pack-library-bucket"', source)) == 1
            and source.count('<span className="kbot-pack-library__bucket-caption">Filter by bucket</span>') == 1
            and '<label className="kbot-pack-library__bucket-label" htmlFor="pack-library-bucket">' in source
        )

        # (C) Conditional clear button: Escape chord + accessible name, with
        # the visible literal, disabled gating and callback byte-equal.
        assertions["clear_aria_keyshortcuts"] = (
            CLEAR_KEYSHORTCUTS in new_clear
            and CLEAR_KEYSHORTCUTS not in old_clear
        )
        assertions["clear_aria_label"] = (
            new_clear.count(CLEAR_ARIA_LABEL) == 1
            and "aria-label" not in old_clear
            and source.count(CLEAR_ARIA_LABEL) == 1
        )
        assertions["clear_visible_literal"] = (
            CLEAR_LITERAL in new_clear
            and CLEAR_LITERAL in old_clear
            and all(value in new_clear for value in (
                'type="button"', 'className="kbot-pack-library__clear"',
                'data-testid="pack-library-clear-filters"',
                "disabled={!filtersActive}", "aria-disabled={!filtersActive}",
                "onClick={handleClearFilters}",
            ))
            and len(re.findall(r"(?<!-)disabled=", new_clear)) == 1
        )

        # The already-integrated refresh slice stays byte-equal.
        new_refresh = block(source, refresh_pattern)
        old_refresh = block(baseline, refresh_pattern)
        status_match = re.search(
            r'<p\b[^>]*data-testid="pack-library-refresh-status"[^>]*>', source, re.S)
        status_block = status_match.group() if status_match else ""
        assertions["existing_refresh_surface_unchanged"] = (
            new_refresh == old_refresh
            and all(value in new_refresh for value in (
                'data-testid="pack-library-refresh"', "disabled={refreshing}",
                "aria-disabled={refreshing}", "aria-busy={refreshing}",
                "onClick={handleRefresh}",
            ))
            and '{refreshing ? "Refreshing\u2026" : "Refresh"}' in source
            and status_block.count('role="status"') == 1
            and status_block.count('aria-live="polite"') == 1
        )

        # No data-testid is added, removed or renamed anywhere in the source.
        assertions["existing_testids_only_addition"] = (
            re.findall(r'data-testid="([^"]+)"', source)
            == re.findall(r'data-testid="([^"]+)"', baseline)
            and source.count("aria-keyshortcuts=") == 3
        )
        assertions["client_and_css_unchanged"] = all(
            git("show", f"{BASE}:{path}") == (ROOT / path).read_text()
            for path in PRESERVED_FILES
        ) and (ROOT / "frontend" / NEW_SPEC).exists()

        tests_argv = ["npm", "run", "test:unit", "--", "run", *TESTS]
        tests = run(tests_argv, FRONTEND, timeout=300)
        record("focused_tests", "frontend", tests_argv, tests)
        assertions["runtime_tests"] = tests.returncode == 0
        results["new_spec_executed"] = NEW_SPEC in tests.stdout + tests.stderr

        typecheck_argv = ["npm", "run", "typecheck"]
        typecheck = run(typecheck_argv, FRONTEND, timeout=300)
        record("typecheck", "frontend", typecheck_argv, typecheck)
        # Inherited check debt exists at the baseline; this slice must add none
        # of its own (no error may name the packs files it touched).
        slice_error_pattern = (
            r"^src/features/packs/(PackLibrary\.tsx|PackLibrary\.filterKeyboard\.test\.tsx)"
            r"\(\d+,\d+\): error"
        )
        results["typecheck_slice_errors"] = [
            line for line in (typecheck.stdout + typecheck.stderr).splitlines()
            if re.search(slice_error_pattern, line)
        ]
        assertions["typecheck_no_slice_errors"] = not results["typecheck_slice_errors"]

        build_argv = ["npm", "run", "build"]
        build = run(build_argv, FRONTEND, timeout=300)
        record("build", "frontend", build_argv, build)
        assertions["build"] = build.returncode == 0

        self_argv = ["uv", "run", "--frozen", "python",
                     "scripts/verify_pack_library_filter_keyboard.py"]
        assertions["verification_commands_recorded"] = (
            len(commands) == 3
            and all(set(command) == {"name", "cwd", "argv", "exit"} for command in commands)
        )
        results["qualified"] = all(assertions.values())
        # The verifier is the fourth verification command; its exit is fully
        # determined once every assertion is computed, so it can be recorded
        # truthfully here (the process returns exactly this value below).
        results["verification_commands"] = commands + [{
            "name": "verify_pack_library_filter_keyboard", "cwd": ".", "argv": self_argv,
            "exit": 0 if results["qualified"] else 1,
        }]
    except (OSError, ValueError, RuntimeError, AssertionError,
            subprocess.SubprocessError) as error:
        results["error"] = f"{type(error).__name__}: {error}"
    report = out / "summary.json"
    report.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({**results, "summary_file": str(report.resolve())}, indent=2))
    return 0 if results["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
