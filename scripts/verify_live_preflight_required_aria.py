#!/usr/bin/env python3
"""Verify required-input ARIA, preserved surfaces, and the bounded regression suite.

Run: uv run --frozen python scripts/verify_live_preflight_required_aria.py
This verifies source and jsdom semantics, not audible screen-reader behavior.
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
BASE = "2ce1e3771f2d839391a7f2161a09fff3db979c39"
COMPONENT = "frontend/src/features/deployments/LivePreflight.tsx"
TEST = "frontend/src/features/deployments/LivePreflight.requiredAria.test.tsx"
SCRIPT = "scripts/verify_live_preflight_required_aria.py"
ALLOWED = {COMPONENT, TEST, SCRIPT}
TESTS = [TEST.removeprefix("frontend/")] + [
    f"src/features/deployments/LivePreflight{suffix}"
    for suffix in (".test.ts", ".staleState.test.tsx", ".signal.test.tsx")
]
REQUIRED = [
    "source_read", "account_input_aria_required", "revision_input_aria_required",
    "per_input_aria_invalid_wired", "per_input_aria_describedby_wired",
    "inline_problem_nodes_conditional", "role_alert_pattern_existing_unchanged",
    "submit_button_unchanged", "submit_order_preserved", "on_submit_shape_unchanged",
    "allowlist_enforced", "runtime_tests", "typecheck_no_slice_errors", "build",
    "diff_check", "verification_commands_recorded",
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, timeout=30).strip()


def extract(pattern: str, source: str) -> str:
    match = re.search(pattern, source, re.DOTALL)
    if match is None:
        raise AssertionError(f"Missing source pattern: {pattern}")
    return match.group(0)


def main() -> int:
    summary = {
        "tested_sha": git("rev-parse", "HEAD"),
        "source_dirty": bool(git("status", "--porcelain")),
        "base_sha": BASE,
        "invocation": ["uv", "run", "--frozen", "python", SCRIPT],
        "required_assertions": dict.fromkeys(REQUIRED, False),
        "commands": [],
        "limits": "Source + jsdom only; real-browser and audible SR verification remain with Operator.",
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
        base = git("show", f"{BASE}:{COMPONENT}")
        summary["source_hashes"] = {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in sorted(ALLOWED)
        }
        checks["source_read"] = bool(source and base)
        inputs = {
            field: extract(r'<input\b[^>]*data-testid="live-preflight-' + field + r'"[^>]*/>', source)
            for field in ("account", "revision")
        }
        for field, markup in inputs.items():
            checks[f"{field}_input_aria_required"] = 'aria-required="true"' in markup
        checks["per_input_aria_invalid_wired"] = all(
            f"aria-invalid={{fieldProblems.{field} !== null}}" in markup
            for field, markup in inputs.items()
        )
        checks["per_input_aria_describedby_wired"] = all(
            re.search(
                r'aria-describedby=\{\s*fieldProblems\.' + field
                + r' !== null \? "live-preflight-' + field + r'-problem" : undefined\s*\}', markup
            ) is not None for field, markup in inputs.items()
        )
        checks["inline_problem_nodes_conditional"] = all(
            re.search(
                r'\{fieldProblems\.' + field + r' !== null \? \(\s*<p\s+'
                + r'id="live-preflight-' + field + r'-problem"\s+'
                + r'data-testid="live-preflight-' + field + r'-problem"\s*>'
                + r'\s*\{fieldProblems\.' + field + r'\}\s*</p>\s*\) : null\}', source
            ) is not None for field in inputs
        )
        alert = r'\{errorMessage !== null \? \(\s*<p\b.*?</p>\s*\) : null\}'
        checks["role_alert_pattern_existing_unchanged"] = extract(alert, source) == extract(alert, base)
        button = r'<button\b[^>]*data-testid="live-preflight-submit".*?</button>'
        checks["submit_button_unchanged"] = (
            extract(button, source) == extract(button, base)
            and "disabled={pending}" in extract(button, source)
        )
        handler = extract(r'const handleSubmit = async .*?\n  };', source)
        checks["submit_order_preserved"] = (
            re.search(r'=> \{\s*event.preventDefault\(\);', handler) is not None
            and handler.index("setFieldProblems({") < handler.index("await fetch(")
        )
        on_submit = r'onSubmit=\{\(event\) => \{.*?\}\}'
        checks["on_submit_shape_unchanged"] = extract(on_submit, source) == extract(on_submit, base)
        changed = set(git("diff", "--name-only", BASE).splitlines())
        changed.update(git("ls-files", "--others", "--exclude-standard").splitlines())
        summary["changed_files"] = sorted(changed)
        checks["allowlist_enforced"] = changed <= ALLOWED
        checks["runtime_tests"] = run(["npm", "run", "test:unit", "--", "run", *TESTS], FRONTEND)["exit_code"] == 0
        current_typecheck = run(["npm", "run", "typecheck"], FRONTEND)

        # Compare actual base diagnostics rather than blessing unrelated failures by filename.
        with tempfile.TemporaryDirectory(prefix="krellbot-required-aria-base-") as temp:
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

        def diagnostics(record: dict) -> list[str]:
            output = re.sub(r'\x1b\[[0-9;]*m', '', record["output"])
            return sorted(line for line in output.splitlines() if re.match(r'src/.*error TS\d+:', line))

        current_errors = diagnostics(current_typecheck)
        baseline_errors = diagnostics(baseline_typecheck)
        summary["typecheck_diagnostics_match_base"] = current_errors == baseline_errors
        checks["typecheck_no_slice_errors"] = (
            current_typecheck["exit_code"] == baseline_typecheck["exit_code"] == 0
            or (current_typecheck["exit_code"] == baseline_typecheck["exit_code"]
                and current_typecheck["exit_code"] in (1, 2)
                and bool(current_errors) and current_errors == baseline_errors
                and not any("LivePreflight" in error for error in current_errors))
        )
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
