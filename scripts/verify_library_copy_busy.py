#!/usr/bin/env python3
"""Verify row-scoped Copy as new busy feedback with the real frontend component.

Run from the repository root with Python's standard library only; no uv sync,
backend, exchange, credentials, signing or trading path is invoked. Vitest uses
Testing Library and a deferred fake LibraryClient at the component I/O boundary.
This verifies DOM semantics, not actual screen-reader speech or browser defaults.
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
BASE = "d70791d69bf26e360f4325e2cfd77f8799a205b7"
FEATURE = "frontend/src/features/strategies/"
SOURCE = FEATURE + "SavedStrategyLibrary.tsx"
TESTS = [
    "SavedStrategyLibrary.copyBusy.test.tsx",
    "SavedStrategyLibrary.test.tsx",
    "SavedStrategyLibrary.signal.test.tsx",
    "SavedStrategyLibrary.stateFilter.test.tsx",
    "SavedStrategyLibrary.copy.test.tsx",
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="library-copy-busy-"))
    out.mkdir(parents=True, exist_ok=True)
    results: dict = {"qualified": False, "canonical_sha": BASE, "commands": [], "assertions": {},
                     "mechanism": "Real Vitest/Testing Library component; deferred fake LibraryClient; no backend"}
    assertions = results["assertions"]
    try:
        results["source_sha"] = git("rev-parse", "HEAD").strip()
        results["source_status"] = git("status", "--porcelain")
        source = (ROOT / SOURCE).read_text()
        baseline = git("show", f"{BASE}:{SOURCE}")
        reopen = r"  const handleReopen = .*?(?=  const handleCopyAsNew)"
        assertions["reopen_handler_byte_equal"] = (
            re.search(reopen, source, re.S).group() == re.search(reopen, baseline, re.S).group()
        )
        reopen_button = r'<button\s+type="button"\s+className="kbot-strategy-library__reopen".*?</button>'
        assertions["reopen_button_guard_byte_equal"] = (
            re.search(reopen_button, source, re.S).group() == re.search(reopen_button, baseline, re.S).group()
        )
        error = r'\{copyError !== null \? \(.*?\) : null\}'
        assertions["canonical_copy_error_byte_equal"] = (
            re.search(error, source, re.S).group() == re.search(error, baseline, re.S).group()
        )
        assertions["testids_preserved"] = (
            re.findall(r'data-testid="([^"]+)"', source) == re.findall(r'data-testid="([^"]+)"', baseline)
        )
        copy_button = re.search(r'<button\s+type="button"\s+className="kbot-strategy-library__copy".*?</button>', source, re.S).group()
        assertions["native_copy_button_no_key_handler"] = "onKeyDown" not in copy_button and "onKeyUp" not in copy_button
        preserved = [FEATURE + name for name in TESTS[1:]] + [FEATURE + "libraryClient.ts", "src/krellbot/api/app.py"]
        assertions["existing_tests_and_read_boundary_unchanged"] = all(
            (ROOT / path).read_text() == git("show", f"{BASE}:{path}") for path in preserved
        )
        tests = list(TESTS)
        reopen_test = "SavedStrategyLibrary.reopenBusyAria.test.tsx"
        results["reopen_reference_present"] = (ROOT / FEATURE / reopen_test).exists()
        if results["reopen_reference_present"]:
            tests.append(reopen_test)
        results["source_hashes"] = {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in [SOURCE, FEATURE + "SavedStrategyLibrary.signal.css", FEATURE + TESTS[0],
                         "scripts/verify_library_copy_busy.py"]
        }
        report = out / "vitest.json"
        report.unlink(missing_ok=True)
        argv = ["npm", "run", "test:unit", "--", "--run",
                *["src/features/strategies/" + name for name in tests],
                "--reporter=json", "--outputFile=" + str(report)]
        record = {"argv": argv, "cwd": str(FRONTEND), "log": str(out / "vitest.log"), "exit": None}
        results["commands"].append(record)
        env = dict(os.environ, NODE_ENV="test", KRELLBOT_ENABLE_LIVE="0")
        with (out / "vitest.log").open("w") as log:
            try:
                record["exit"] = subprocess.run(argv, cwd=FRONTEND, env=env, stdout=log,
                                                stderr=subprocess.STDOUT, timeout=300).returncode
            except subprocess.TimeoutExpired:
                record["exit"] = 124
        assertions["runtime_tests"] = record["exit"] == 0
        if report.exists():
            data = json.loads(report.read_text())
            results["tests_passed"] = data["numPassedTests"]
            assertions["all_required_specs_executed"] = all(
                any(Path(item["name"]).name == name and item["status"] == "passed"
                    and item["assertionResults"] for item in data["testResults"])
                for name in tests
            )
        else:
            assertions["all_required_specs_executed"] = False
        results["qualified"] = all(assertions.values())
    except (OSError, ValueError, AttributeError, KeyError, subprocess.SubprocessError) as error:
        results["error"] = str(error)
    (out / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({"qualified": results["qualified"], "summary_file": str(out / "summary.json"),
                      "error": results.get("error")}, indent=2))
    return 0 if results["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
