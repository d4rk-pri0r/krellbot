#!/usr/bin/env python3
"""Qualify the saved-strategy library search toolbar accessibility annotations.

Run from the repository root: uv run --frozen python scripts/verify_library_search_aria.py
The real SavedStrategyLibrary component is exercised through a focused
@testing-library/react Vitest mount; the fake LibraryClient is substituted only
at the component's I/O boundary. Static regex checks prove the preserved parts
of the canonical toolbar stayed byte-equal against the base commit. This
verifies DOM semantics, not actual screen-reader speech or browser defaults.
No backend, exchange, credentials, signing or trading path is invoked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BASE = "b3eb964206cc8e9bd06ab38786bf760d4723b068"
SOURCE = "frontend/src/features/strategies/SavedStrategyLibrary.tsx"
SEARCH_ARIA_SPEC = "SavedStrategyLibrary.searchAria.test.tsx"
STATE_FILTER_SPEC = "SavedStrategyLibrary.stateFilter.test.tsx"
SIGNAL_SPEC = "SavedStrategyLibrary.signal.test.tsx"
SPECS = [f"src/features/strategies/{name}" for name in (SEARCH_ARIA_SPEC, STATE_FILTER_SPEC, SIGNAL_SPEC)]
PRESERVED_FILES = [
    f"frontend/src/features/strategies/{STATE_FILTER_SPEC}",
    f"frontend/src/features/strategies/{SIGNAL_SPEC}",
    "frontend/src/features/strategies/SavedStrategyLibrary.signal.css",
]

# Runtime evidence: required assertion -> (spec file, exact test title that proves it live).
RUNTIME = {
    "search_input_id": (SEARCH_ARIA_SPEC, "gives the existing search input a structural id without renaming it"),
    "search_input_keyshortcuts": (SEARCH_ARIA_SPEC, "gives the existing search input a structural id without renaming it"),
    "no_visible_label_bound": (SEARCH_ARIA_SPEC, "gives the existing search input a structural id without renaming it"),
    "clear_button_conditional": (SEARCH_ARIA_SPEC, "announces the clear shortcut on the conditionally rendered clear button"),
    "clear_button_aria_label": (SEARCH_ARIA_SPEC, "announces the clear shortcut on the conditionally rendered clear button"),
    "clear_button_keyshortcuts": (SEARCH_ARIA_SPEC, "announces the clear shortcut on the conditionally rendered clear button"),
    "clear_button_click_clears": (STATE_FILTER_SPEC, "keeps search clear independent of state selection"),
    "state_filter_for_html_preserved": (SEARCH_ARIA_SPEC, "keeps the state filter label binding and announces its shortcut"),
    "state_filter_keyshortcuts": (SEARCH_ARIA_SPEC, "keeps the state filter label binding and announces its shortcut"),
    "escape_clears_in_input": (SEARCH_ARIA_SPEC, "keeps the in-input Escape clear behavior byte-equal in effect"),
}
REQUIRED = (
    *RUNTIME.keys(),
    "search_input_aria_label_preserved", "clear_button_visible_text_unchanged",
    "label_binding_unchanged", "canonical_handlers_byte_equal", "canonical_testids_byte_equal",
    "existing_specs_unchanged", "all_required_specs_executed",
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="library-search-aria-"))
    out.mkdir(parents=True, exist_ok=True)
    summary: dict = {"qualified": False, "required_assertions": dict.fromkeys(REQUIRED, False),
                     "commands": [], "output_dir": str(out),
                     "mechanism": "Focused Vitest/@testing-library/react mount of the real component; "
                                  "fake LibraryClient only at the component I/O boundary; static regex "
                                  "over the canonical toolbar keeps preserved surfaces byte-equal",
                     "scope": "aria/id annotations on the library search toolbar only"}
    required = summary["required_assertions"]
    try:
        summary["source_sha"] = git("rev-parse", "HEAD").strip()
        summary["source_status"] = git("status", "--porcelain")
        source = (ROOT / SOURCE).read_text()
        baseline = git("show", f"{BASE}:{SOURCE}")
        summary["source_hashes"] = {
            SOURCE: hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest(),
            SPECS[0]: hashlib.sha256((FRONTEND / SPECS[0]).read_bytes()).hexdigest(),
            "frontend/src/features/strategies/SavedStrategyLibrary.signal.css": hashlib.sha256(
                (FRONTEND / "src/features/strategies/SavedStrategyLibrary.signal.css").read_bytes()).hexdigest(),
        }
        summary["source_hashes"]["scripts/verify_library_search_aria.py"] = hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest()

        def block(text: str, pattern: str) -> str:
            match = re.search(pattern, text, re.S)
            assert match, f"canonical block not found: {pattern}"
            return match.group()

        input_pattern = r'<input\s+type="search".*?/>'
        clear_pattern = r'<button\s+type="button"\s+className="kbot-strategy-library__search-clear".*?</button>'
        select_pattern = r'<select\s+id="library-state-filter".*?</select>'
        label_pattern = '<label htmlFor="library-state-filter">State</label>'
        new_input, old_input = block(source, input_pattern), block(baseline, input_pattern)
        new_clear, old_clear = block(source, clear_pattern), block(baseline, clear_pattern)
        new_select = block(source, select_pattern)

        # Preserved surfaces stay byte-equal to the base toolbar.
        required["canonical_handlers_byte_equal"] = all(
            fragment in new_input and fragment in old_input for fragment in (
                'onChange={(event) => {', "setQuery(event.target.value);",
                'onKeyDown={(event) => {', 'if (event.key === "Escape") {',
                "event.preventDefault();", "clearQuery();",
            )
        ) and new_clear.count("onClick={clearQuery}") == 1 and old_clear.count("onClick={clearQuery}") == 1
        required["canonical_testids_byte_equal"] = (
            re.findall(r'data-testid="([^"]+)"', source) == re.findall(r'data-testid="([^"]+)"', baseline)
        )
        required["clear_button_visible_text_unchanged"] = (
            re.search(r">\s*Clear search\s*</button>", new_clear) is not None
            and re.search(r">\s*Clear search\s*</button>", old_clear) is not None
            and new_clear.count('aria-label="Clear search query"') == 1
            and new_clear.count('aria-keyshortcuts="Escape"') == 1
            and old_clear.count("aria-label=") == 0
        )
        required["label_binding_unchanged"] = (
            source.count(label_pattern) == 1 and baseline.count(label_pattern) == 1
            and 'id="library-state-filter"' in new_select
            and "aria-keyshortcuts" not in block(baseline, select_pattern)
        )
        required["existing_specs_unchanged"] = all(
            (ROOT / path).read_text() == git("show", f"{BASE}:{path}") for path in PRESERVED_FILES
        )

        # The three shipped annotations exist exactly once on their canonical elements.
        # A lookbehind is required so data-testid="library-search" is not mistaken for id=.
        id_count = len(re.findall(r'(?<![\w-])id="library-search"', new_input))
        required["search_input_aria_label_preserved"] = (
            new_input.count('aria-label="Search saved strategies"') == 1 and id_count == 1
        )
        required["search_input_keyshortcuts"] = new_input.count('aria-keyshortcuts="Control+F Meta+F"') == 1
        required["state_filter_keyshortcuts"] = new_select.count('aria-keyshortcuts="Mod+Alt+S"') == 1

        # Runtime: focused Vitest mount of the real component.
        report = out / "vitest.json"
        report.unlink(missing_ok=True)
        argv = ["npm", "run", "test:unit", "--", "--run", *SPECS,
                "--reporter=json", "--outputFile=" + str(report)]
        record = {"argv": argv, "cwd": str(FRONTEND), "log": str(out / "vitest.log"), "exit": None}
        summary["commands"].append(record)
        env = dict(os.environ, NODE_ENV="test", KRELLBOT_ENABLE_LIVE="0")
        with (out / "vitest.log").open("w") as log:
            try:
                record["exit"] = subprocess.run(argv, cwd=FRONTEND, env=env, stdout=log,
                                                stderr=subprocess.STDOUT, timeout=300).returncode
            except subprocess.TimeoutExpired:
                record["exit"] = 124
        summary["vitest_exit"] = record["exit"]
        if not report.exists():
            raise AssertionError("vitest json report missing; see vitest.log")
        data = json.loads(report.read_text())
        summary["tests_passed"] = data["numPassedTests"]
        summary["tests_total"] = data["numTotalTests"]
        required["all_required_specs_executed"] = record["exit"] == 0 and all(
            any(Path(item["name"]).name == Path(spec).name and item["status"] == "passed"
                and item["assertionResults"] for item in data["testResults"])
            for spec in SPECS
        )
        cases = {(Path(item["name"]).name, case["title"]): case["status"]
                 for item in data["testResults"] for case in item["assertionResults"]}
        missing = [(spec, title) for spec, title in RUNTIME.values() if (spec, title) not in cases]
        assert not missing, f"missing searchAria/stateFilter cases: {missing}"
        for name, (spec, title) in RUNTIME.items():
            required[name] = cases[(spec, title)] == "passed"
        summary["qualified"] = all(required.values())
    except (OSError, ValueError, KeyError, IndexError, AssertionError, AttributeError,
            subprocess.SubprocessError) as error:
        summary["error"] = f"{type(error).__name__}: {error}"
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"qualified": summary["qualified"],
                      "required_assertions": summary["required_assertions"],
                      "tests_passed": summary.get("tests_passed"),
                      "output_dir": str(out), "error": summary.get("error")}, indent=2))
    return 0 if summary["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
