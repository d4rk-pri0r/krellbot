#!/usr/bin/env python3
"""Offline source + runtime verification for the library row Compare keyboard-aria slice.

Checks that frontend/src/features/strategies/SavedStrategyLibrary.tsx:
  (a) every per-row Compare button carries aria-keyshortcuts="Control+Alt+C Meta+Alt+C",
  (b) every per-row Compare button carries an aria-label derived from the row's
      label / strategy_id / id fallback chain reading "Compare revisions of <name>",
  (c) the literal "Compare" inside the button stays byte-equal,
  (d) the outer library region carries an onKeyDown handler that intercepts
      ctrl/meta + alt + "c"/"C", prevents the browser default, and resolves the
      focused Compare button's <li data-revision-id> row (falling back to the
      first row when the section root itself holds focus) into setCompareRow,
  (e) event.repeat is honored so auto-repeat never re-fires the activation,
  (f) the existing data-testid contract stays byte-equal,
  (g) the existing className CSS contract stays byte-equal,
without disturbing any pre-existing surface (Reopen, Copy as new, RevisionCompare
mount, status surfaces, SavedStrategyLibraryProps, client contract), then runs
the focused Vitest suite and `npm run typecheck`. AX semantics are evidence for
assistive tech, not a claim of audible screen-reader output. Standard library only.
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
FEATURE = "frontend/src/features/strategies/"
SOURCE = FEATURE + "SavedStrategyLibrary.tsx"
BASE = "8243b207306f80570f4485ef2cb70e05be97d42c"
NEW_SPEC = "src/features/strategies/SavedStrategyLibrary.compareKeyboard.test.tsx"
TESTS = (
    NEW_SPEC,
    "src/features/strategies/SavedStrategyLibrary.test.tsx",
)
PRESERVED_FILES = tuple(f"frontend/{test}" for test in TESTS[1:]) + (
    "frontend/src/features/strategies/RevisionCompare.tsx",
    "frontend/src/features/strategies/libraryClient.ts",
    "frontend/src/features/strategies/client.ts",
    "frontend/src/features/strategies/ownedStrategy.ts",
    "frontend/src/features/strategies/Editor.tsx",
    "frontend/src/shell/WorkstationShell.tsx",
    "frontend/src/features/strategies/SavedStrategyLibrary.signal.css",
)
REQUIRED = (
    "source_read", "compare_keyshortcuts_announced", "compare_row_aria_label",
    "compare_literal_byte_equal", "compare_click_wiring_byte_equal",
    "section_onkeydown_wired", "chord_intercept", "focused_row_resolution",
    "section_root_first_row_resolution", "event_repeat_honored",
    "testids_byte_equal", "classnames_byte_equal", "preserved_surfaces_byte_equal",
    "read_boundaries_unchanged", "runtime_tests", "typecheck_no_slice_errors",
    "verification_commands_recorded",
)

COMPARE_KEYSHORTCUTS = 'aria-keyshortcuts="Control+Alt+C Meta+Alt+C"'
COMPARE_ARIA_LABEL = (
    r'aria-label=\{`Compare revisions of '
    r'\$\{row\.label \|\| row\.strategy_id \|\| row\.id \|\| "\(untitled\)"\}`\}'
)
PRESERVED_BLOCKS = (
    ("props_contract", r"export type SavedStrategyLibraryProps = \{.*?\n\};"),
    ("handle_reopen", r"  const handleReopen = .*?(?=  const handleCopyAsNew)"),
    ("handle_copy_as_new", r"  const handleCopyAsNew = .*?(?=  const clearQuery)"),
    ("reopen_button", r'<button\s+type="button"\s+className="kbot-strategy-library__reopen".*?</button>'),
    ("copy_button", r'<button\s+type="button"\s+className="kbot-strategy-library__copy".*?</button>'),
    ("row_li_opening_tag", r'                    <li\n                      key=\{row\.revision_id\}.*?\n                    \>'),
    ("row_main_cells", r'<div className="kbot-strategy-library__row-main">.*?</div>'),
    ("row_busy_status_span", r'<span\n                          className="kbot-strategy-library__row-busy-status".*?</span>'),
    ("revision_compare_mount", r'\{compareRow !== null && phase === "ready" \? \(\n        <RevisionCompare.*?\) : null\}'),
    ("loading_status", r'\{phase === "loading" \? \(.*?\) : null\}'),
    ("error_status", r'\{phase === "error" \? \(.*?\) : null\}'),
    ("empty_status", r'\{phase === "ready" && rows\.length === 0 \? \(.*?\) : null\}'),
    ("reopen_error_status", r'\{reopenError !== null \? \(.*?\) : null\}'),
    ("new_owned_strategy_button", r'<button\s+type="button"\s+data-testid="library-new-owned-strategy".*?</button>'),
)


def run(argv: list[str], directory: Path, timeout: int, log_path: Path,
        env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    with log_path.open("w") as log:
        try:
            return subprocess.run(argv, cwd=directory, text=True, env=env,
                                  stdout=log, stderr=subprocess.STDOUT,
                                  timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(argv, 124, "", "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir or Path(tempfile.mkdtemp(prefix="library-row-compare-keyboard-"))
    out.mkdir(parents=True, exist_ok=True)
    assertions = dict.fromkeys(REQUIRED, False)
    commands: list[dict[str, object]] = []
    results: dict[str, object] = {
        "qualified": False,
        "required_assertions": assertions,
        "baseline": BASE,
        "source_path": SOURCE,
        "verification_commands": commands,
        "mechanism": ("Real Vitest/Testing Library component; only the read "
                      "client boundary is faked; source diffed against the "
                      "canonical baseline commit"),
    }

    def record(name: str, cwd: str, argv: list[str],
               process: subprocess.CompletedProcess[str]) -> int:
        commands.append({"name": name, "cwd": cwd, "argv": argv,
                         "exit": process.returncode})
        return process.returncode

    try:
        def git(*a: str) -> str:
            return subprocess.run(["git", *a], cwd=ROOT, text=True,
                                  capture_output=True, check=False).stdout

        def block(text: str, pattern: str, what: str) -> str:
            match = re.search(pattern, text, re.S)
            assert match, f"canonical block not found ({what}): {pattern}"
            return match.group()

        source = (ROOT / SOURCE).read_text()
        baseline = git("show", f"{BASE}:{SOURCE}")
        results["head"] = git("rev-parse", "HEAD").strip()
        results["git_status"] = git("status", "--porcelain")
        results["source_sha256"] = hashlib.sha256(source.encode()).hexdigest()
        assertions["source_read"] = bool(baseline) and bool(source)

        compare_pattern = (
            r'<button\s+type="button"\s+className="kbot-strategy-library__compare".*?</button>'
        )
        new_compare = block(source, compare_pattern, "compare button")
        old_compare = block(baseline, compare_pattern, "baseline compare button")

        # (a) The documented Ctrl+Alt+C / Cmd+Alt+C activation shortcut is
        # announced on the per-row Compare button and was not there before.
        assertions["compare_keyshortcuts_announced"] = (
            COMPARE_KEYSHORTCUTS in new_compare
            and COMPARE_KEYSHORTCUTS not in old_compare
        )

        # (b) A row-specific accessible name derived from the same iteration's
        # label / strategy_id / id fallback chain.
        assertions["compare_row_aria_label"] = (
            re.search(COMPARE_ARIA_LABEL, new_compare) is not None
            and "aria-label" not in old_compare
        )

        # (c) + wiring: the visible literal and the existing click activation
        # stay byte-equal; the button keeps its testid and className.
        click_pattern = r"onClick=\{\(\) => \{\s*setCompareRow\(row\);\s*\}\}"
        literal_pattern = r">\n\s*Compare\n\s*</button>"
        assertions["compare_literal_byte_equal"] = (
            re.search(literal_pattern, new_compare).group()
            == re.search(literal_pattern, old_compare).group()
        )
        assertions["compare_click_wiring_byte_equal"] = (
            re.search(click_pattern, new_compare).group()
            == re.search(click_pattern, old_compare).group()
            and 'data-testid="library-row-compare"' in new_compare
            and 'className="kbot-strategy-library__compare"' in new_compare
        )

        # (d) The outer region carries the shortcut handler.
        section_pattern = r'<section\s+className="kbot-strategy-library"[^>]*>'
        new_section = block(source, section_pattern, "library region")
        old_section = block(baseline, section_pattern, "baseline library region")
        handler_pattern = r"  const handleCompareShortcut = .*?(?=\n  const searching)"
        new_handler = block(source, handler_pattern, "shortcut handler")
        assertions["section_onkeydown_wired"] = (
            'data-testid="saved-strategy-library"' in new_section
            and 'role="region"' in new_section
            and 'aria-label="Saved strategy library"' in new_section
            and "onKeyDown={handleCompareShortcut}" in new_section
            and "onKeyDown" not in old_section
        )
        assertions["chord_intercept"] = (
            "(event.ctrlKey || event.metaKey)" in new_handler
            and "!event.altKey" in new_handler
            and '(event.key !== "c" && event.key !== "C")' in new_handler
            and "event.preventDefault();" in new_handler
        )
        assertions["focused_row_resolution"] = (
            "document.activeElement" in new_handler
            and 'button[data-testid="library-row-compare"]' in new_handler
            and 'li[data-testid="library-row"]' in new_handler
            and 'getAttribute("data-revision-id")' in new_handler
            and "setCompareRow(" in new_handler
            and "rows.find((row) => row.revision_id === revisionId)" in new_handler
        )
        assertions["section_root_first_row_resolution"] = (
            "active === event.currentTarget" in new_handler
            and "setCompareRow(rows[0] ?? null)" in new_handler
        )

        # (e) Auto-repeat never re-fires the activation.
        assertions["event_repeat_honored"] = (
            "if (event.repeat) {\n      return;\n    }" in new_handler
        )

        # (f) Existing data-testid contract stays byte-equal. JSX attributes in
        # this file each sit on their own line; matching line-start
        # occurrences keeps the selector strings inside the new shortcut
        # handler from being miscounted as rendered testids.
        assertions["testids_byte_equal"] = (
            re.findall(r'^[ \t]*data-testid="([^"]+)"$', source, re.M)
            == re.findall(r'^[ \t]*data-testid="([^"]+)"$', baseline, re.M)
        )

        # (g) Existing className CSS contract stays byte-equal.
        assertions["classnames_byte_equal"] = (
            re.findall(r'className=\{?"([^"}]+)"\}?', source)
            == re.findall(r'className=\{?"([^"}]+)"\}?', baseline)
        )

        # Every pre-existing surface stays byte-equal against the baseline.
        preserved_ok = True
        for name, pattern in PRESERVED_BLOCKS:
            preserved_ok = preserved_ok and block(
                source, pattern, name) == block(baseline, pattern, name)
        assertions["preserved_surfaces_byte_equal"] = preserved_ok

        assertions["read_boundaries_unchanged"] = all(
            (ROOT / path).read_text() == git("show", f"{BASE}:{path}")
            for path in PRESERVED_FILES
        )

        results["source_hashes"] = {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in [
                SOURCE,
                "frontend/" + NEW_SPEC,
                "scripts/verify_library_row_compare_keyboard.py",
                *PRESERVED_FILES,
            ]
        }

        # Focused runtime evidence: the new spec plus the untouched legacy spec.
        report = out / "vitest.json"
        report.unlink(missing_ok=True)
        vitest_argv = ["npm", "run", "test:unit", "--", "--run", *TESTS,
                       "--reporter=json", "--outputFile=" + str(report)]
        vitest = run(vitest_argv, FRONTEND, 300, out / "vitest.log",
                     env=dict(os.environ, NODE_ENV="test", KRELLBOT_ENABLE_LIVE="0"))
        exit_code = record("vitest_focused", str(FRONTEND), vitest_argv, vitest)
        assertions["runtime_tests"] = exit_code == 0
        if report.exists():
            data = json.loads(report.read_text())
            results["tests_passed"] = data["numPassedTests"]
            assertions["runtime_tests"] = assertions["runtime_tests"] and all(
                any(Path(item["name"]).name == Path(test).name
                    and item["status"] == "passed" and item["assertionResults"]
                    for item in data["testResults"])
                for test in TESTS
            )

        typecheck_argv = ["npm", "run", "typecheck"]
        typecheck = run(typecheck_argv, FRONTEND, 300, out / "typecheck.log")
        record("typecheck", str(FRONTEND), typecheck_argv, typecheck)
        # Inherited check debt exists at the baseline (PackLibrary.test.tsx,
        # paper/client.test.ts, SavedStrategyLibrary.copy.test.tsx); this
        # slice must add none of its own — no error may name the files it
        # touched.
        slice_error_pattern = (
            r"^src/features/strategies/"
            r"(SavedStrategyLibrary\.tsx|SavedStrategyLibrary\.compareKeyboard\.test\.tsx)"
            r"\(\d+,\d+\): error"
        )
        results["typecheck_slice_errors"] = [
            line for line in (out / "typecheck.log").read_text().splitlines()
            if re.search(slice_error_pattern, line)
        ]
        assertions["typecheck_no_slice_errors"] = not results["typecheck_slice_errors"]
        assertions["verification_commands_recorded"] = len(commands) == 2
        results["qualified"] = all(assertions.values())
    except (OSError, ValueError, AttributeError, KeyError, AssertionError,
            subprocess.SubprocessError) as error:
        results["error"] = str(error)
    (out / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({"qualified": results["qualified"],
                      "summary_file": str(out / "summary.json"),
                      "failed": [k for k, v in results.get(
                          "required_assertions", {}).items() if not v],
                      "error": results.get("error")}, indent=2))
    return 0 if results["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
