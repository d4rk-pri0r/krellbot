#!/usr/bin/env python3
"""Verify the bounded UTC invalid-input ARIA slice; not audible SR qualification.

Run: uv run --frozen python scripts/verify_research_date_window_invalid_aria.py
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BASE = "2ccc523109cdc749a1fda9bd9ac14ec2f9d3d753"
COMPONENT = "frontend/src/features/research/ResearchDateWindow.tsx"
TEST = "frontend/src/features/research/ResearchDateWindow.invalidAria.test.tsx"
SCRIPT = "scripts/verify_research_date_window_invalid_aria.py"
ALLOWED = {COMPONENT, TEST, SCRIPT}
TESTS = [TEST.removeprefix("frontend/")] + [
    "src/features/research/ResearchDateWindow.test.tsx",
    "src/features/research/ResearchView.test.tsx",
]
REQUIRED = (
    "source_read", "invalid_span_has_id", "input_aria_invalid_reflects_showInvalid",
    "input_aria_describedby_wired_only_when_invalid", "ordering_paragraph_preserved",
    "four_input_ids_present", "existing_data_testids_preserved", "only_three_attributes_added",
    "allowlist_enforced", "runtime_tests", "typecheck_no_slice_errors", "build",
    "diff_check", "verification_commands_recorded",
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, timeout=30).strip()


def extract(pattern: str, source: str) -> str:
    match = re.search(pattern, source, re.DOTALL)
    if match is None:
        raise AssertionError(f"Missing source pattern: {pattern}")
    return match.group(0)


def diagnostics(record: dict) -> list[str]:
    output = re.sub(r"\x1b\[[0-9;]*m", "", record["output"])
    return sorted(line.strip() for line in output.splitlines() if "error TS" in line)


def main() -> int:
    summary = {
        "tested_sha": git("rev-parse", "HEAD"),
        "source_dirty": bool(git("status", "--porcelain")),
        "base_sha": BASE,
        "invocation": ["uv", "run", "--frozen", "python", SCRIPT],
        "required_assertions": dict.fromkeys(REQUIRED, False),
        "commands": [],
        "limits": "Source and jsdom only; real-browser, audible SR, and Windows qualification remain separate.",
    }
    checks = summary["required_assertions"]

    def run(argv: list[str], cwd: Path) -> dict:
        record = {"argv": argv, "cwd": str(cwd), "timeout_seconds": 180}
        summary["commands"].append(record)
        try:
            result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=180)
            record.update(exit_code=result.returncode, output=result.stdout + result.stderr)
        except subprocess.TimeoutExpired:
            record.update(exit_code=124, output="Command exceeded 180 seconds")
        return record

    try:
        source = (ROOT / COMPONENT).read_text()
        base = git("show", f"{BASE}:{COMPONENT}") + "\n"
        checks["source_read"] = bool(source and base)
        summary["source_hashes"] = {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in sorted(ALLOWED)
        }
        input_markup = extract(r"<input\b.*?/>", source)
        hint = extract(r"\{showInvalid \? \(\s*<span\b.*?</span>\s*\) : null\}", source)
        checks["invalid_span_has_id"] = 'id={`${id}-problem`}' in hint
        checks["input_aria_invalid_reflects_showInvalid"] = 'aria-invalid={showInvalid}' in input_markup
        checks["input_aria_describedby_wired_only_when_invalid"] = (
            'aria-describedby={showInvalid ? `${id}-problem` : undefined}' in input_markup
        )
        ordering = r"\{orderingInverted \? \(\s*<p\b.*?</p>\s*\) : null\}"
        checks["ordering_paragraph_preserved"] = extract(ordering, source) == extract(ordering, base)
        ids = (
            "kbot-research-utc-from", "kbot-research-utc-to",
            "kbot-research-holdout-utc-start", "kbot-research-holdout-utc-end",
        )
        checks["four_input_ids_present"] = all(
            source.count(f'id="{field}"') == 1 for field in ids
        ) and 'id={id}' in input_markup and 'htmlFor={id}' in source
        testids = r'data-testid=(?:"[^"]*"|\{`[^`]*`\})'
        checks["existing_data_testids_preserved"] = re.findall(testids, source) == re.findall(testids, base)
        additions = (
            '        aria-invalid={showInvalid}\n',
            '        aria-describedby={showInvalid ? `${id}-problem` : undefined}\n',
            '          id={`${id}-problem`}\n',
        )
        stripped = source
        for addition in additions:
            stripped = stripped.replace(addition, "", 1)
        checks["only_three_attributes_added"] = stripped == base and all(
            source.count(addition) == 1 for addition in additions
        )
        changed = set(git("diff", "--name-only", BASE).splitlines())
        changed.update(git("ls-files", "--others", "--exclude-standard").splitlines())
        summary["changed_files"] = sorted(changed)
        checks["allowlist_enforced"] = changed == ALLOWED
        checks["runtime_tests"] = run(["npm", "run", "test:unit", "--", "run", *TESTS], FRONTEND)["exit_code"] == 0
        current_typecheck = run(["npm", "run", "typecheck"], FRONTEND)
        # Compare actual base diagnostics rather than exempting unrelated filenames.
        with tempfile.TemporaryDirectory(prefix="krellbot-date-window-base-") as temp:
            archive = subprocess.check_output([
                "git", "archive", BASE, "frontend/src", "frontend/tsconfig.json", "frontend/package.json",
            ], cwd=ROOT, timeout=30)
            with tarfile.open(fileobj=io.BytesIO(archive)) as contents:
                for member in contents.getmembers():
                    if member.isfile():
                        target = Path(temp) / member.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(contents.extractfile(member).read())
            baseline_frontend = Path(temp) / "frontend"
            (baseline_frontend / "node_modules").symlink_to(FRONTEND / "node_modules", target_is_directory=True)
            baseline_typecheck = run(["npm", "run", "typecheck"], baseline_frontend)
        current_errors = diagnostics(current_typecheck)
        baseline_errors = diagnostics(baseline_typecheck)
        checks["typecheck_no_slice_errors"] = (
            current_typecheck["exit_code"] == baseline_typecheck["exit_code"] == 0
            or (current_typecheck["exit_code"] == baseline_typecheck["exit_code"]
                and current_typecheck["exit_code"] in (1, 2)
                and bool(current_errors) and current_errors == baseline_errors
                and not any("ResearchDateWindow" in error for error in current_errors))
        )
        summary["typecheck_baseline_comparison"] = {
            "current_errors": current_errors, "base_errors": baseline_errors,
        }
        checks["build"] = run(["npm", "run", "build"], FRONTEND)["exit_code"] == 0
        checks["diff_check"] = run(["git", "diff", "--check"], ROOT)["exit_code"] == 0
        checks["verification_commands_recorded"] = len(summary["commands"]) == 5
    except Exception as error:
        summary["failure"] = f"{type(error).__name__}: {error}"
    summary["qualified"] = all(checks.values())
    print(json.dumps(summary, indent=2))
    return 0 if summary["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
