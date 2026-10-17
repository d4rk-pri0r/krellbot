#!/usr/bin/env python3
"""Verify the real Editor's file-import DOM behavior using native jsdom FileReader.

Run from the repository root: python scripts/verify_editor_file_import_busy_aria.py
Evidence is written to a fresh temporary directory, never into source files.
This qualifies the bounded DOM contract, not audible output in a screen reader.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
TEST = "Editor.fileImportBusy.test.tsx"
REQUIRED = (
    "aria_busy_on_input_while_in_flight",
    "aria_label_import_pack_file",
    "polite_live_sibling_during_in_flight",
    "polite_live_announces_success_on_settle",
    "polite_live_announces_failure_on_settle",
    "existing_role_alert_on_parse_failure",
    "aria_busy_removed_on_settle",
    "second_file_pick_short_circuited",
)
SOURCES = (
    "frontend/src/features/strategies/Editor.tsx",
    f"frontend/src/features/strategies/{TEST}",
    "scripts/verify_editor_file_import_busy_aria.py",
)


def main() -> int:
    out = Path(tempfile.mkdtemp(prefix="editor-file-import-busy-aria-"))
    report = out / "vitest.json"
    command = [
        "npm", "run", "test:unit", "--", "--run", TEST,
        "--reporter=json", f"--outputFile={report}",
    ]
    result = {
        "qualified": False,
        "required_assertions": dict.fromkeys(REQUIRED, False),
        "mechanism": "Real React Editor + asynchronous native jsdom FileReader; "
                     "readAsText call-through spy only, no replaced reads or parse path; "
                     "no backend requests, keys, orders or publication",
        "qualification_scope": "File-import DOM accessibility contract only; "
                               "not full-project typecheck or audible screen-reader qualification",
        "command": command,
        "cwd": str(FRONTEND),
        "output_dir": str(out),
    }
    try:
        result["source_sha"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10,
        ).strip()
        result["source_status"] = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True, timeout=10,
        )
        result["source_hashes"] = {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in SOURCES
        }
        completed = subprocess.run(
            command, cwd=FRONTEND, env={**os.environ, "CI": "1", "NODE_ENV": "test"},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=120, check=False,
        )
        (out / "vitest.log").write_text(completed.stdout)
        result["test_exit_code"] = completed.returncode
        runtime = json.loads(report.read_text())
        assertions = [
            assertion
            for suite in runtime.get("testResults", [])
            for assertion in suite.get("assertionResults", [])
        ]
        for name in REQUIRED:
            matches = [a for a in assertions if a.get("title") == name]
            result["required_assertions"][name] = (
                len(matches) == 1 and matches[0].get("status") == "passed"
            )
        result["tests_passed"] = runtime.get("numPassedTests", 0)
        result["qualified"] = (
            completed.returncode == 0
            and runtime.get("success") is True
            and runtime.get("numPendingTests") == 0
            and all(result["required_assertions"].values())
        )
    except Exception:
        result["failure"] = traceback.format_exc()
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"results.json: {out / 'results.json'}")
    print(json.dumps(result, indent=2))
    return 0 if result["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
