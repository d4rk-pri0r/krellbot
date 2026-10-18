#!/usr/bin/env python3
"""Shared verifier for APP-BONES-KEYBOARD-01 (armed-records keyboard toggle).

Runs the real checks for the keyboard-access slice and records actual
exits/logs. Invoked identically by worker, integrator and acceptance:

    python3 scripts/verify_armed_keyboard.py --output-dir <abs-dir>

The only permitted invocation difference between environments is the
absolute output directory. Every check runs even when an earlier one
fails; a known inherited failure stays a failure here — nothing is
waived or rewritten. Exits nonzero if ANY check failed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = REPO_ROOT / "frontend"
CHECK_TIMEOUT = 1800.0


@dataclass
class Check:
    name: str
    command: list[str]
    cwd: Path
    started_at: str
    ended_at: str = ""
    exit_code: int | None = None
    log_path: str = ""
    log_tail: list[str] = field(default_factory=list)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def build_checks(output_dir: Path) -> list[Check]:
    npm = "npm"
    focused = [
        npm, "run", "test:unit", "--",
        "--run", "--configLoader", "runner",
        "src/features/paper/ArmedRecordsList",
    ]
    full = focused[:-1]
    typecheck = [npm, "run", "typecheck"]
    build = [
        npm, "run", "build", "--",
        "--configLoader", "runner",
        "--outDir", str(output_dir / "dist"),
    ]
    return [
        Check("focused", focused, FRONTEND, now_iso()),
        Check("full_suite", full, FRONTEND, now_iso()),
        Check("typecheck", typecheck, FRONTEND, now_iso()),
        Check("build", build, FRONTEND, now_iso()),
    ]


def run_check(check: Check, output_dir: Path) -> None:
    log_path = output_dir / f"{check.name}.log"
    # No shell interpolation: argv is passed verbatim to subprocess.
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"# cwd: {check.cwd}\n# argv: {json.dumps(check.command)}\n\n")
        log.flush()
        try:
            completed = subprocess.run(
                check.command,
                cwd=check.cwd,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=CHECK_TIMEOUT,
                check=False,
            )
            check.exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            check.exit_code = 124
        except OSError as err:
            log.write(f"\n# spawn failed: {err}\n")
            check.exit_code = 127
    check.ended_at = now_iso()
    check.log_path = str(log_path)
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    check.log_tail = lines[-25:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Absolute directory for summary.json and per-check logs.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    checks = build_checks(output_dir)
    for check in checks:
        run_check(check, output_dir)

    failed = [c for c in checks if c.exit_code != 0]
    summary = {
        "feature": "APP-BONES-KEYBOARD-01",
        "tested_git_sha": git_head(),
        "started_at": checks[0].started_at,
        "ended_at": checks[-1].ended_at,
        "overall_exit": 1 if failed else 0,
        "any_failed": bool(failed),
        "checks": [
            {
                "name": c.name,
                "command": c.command,
                "cwd": str(c.cwd),
                "started_at": c.started_at,
                "ended_at": c.ended_at,
                "exit_code": c.exit_code,
                "log_path": c.log_path,
                "log_tail": c.log_tail,
            }
            for c in checks
        ],
        "summary_path": str(output_dir / "summary.json"),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )

    print(f"tested git SHA: {summary['tested_git_sha']}")
    for check in checks:
        status = "PASS" if check.exit_code == 0 else f"FAIL({check.exit_code})"
        print(f"{status:9} {check.name}: {' '.join(check.command)}")
        if check.exit_code != 0:
            print("  --- log tail (full log: %s) ---" % check.log_path)
            for line in check.log_tail:
                print(f"  {line}")
    print(f"summary: {summary['summary_path']}")
    print(f"overall exit: {summary['overall_exit']}")
    return summary["overall_exit"]


if __name__ == "__main__":
    sys.exit(main())
