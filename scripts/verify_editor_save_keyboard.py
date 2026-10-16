#!/usr/bin/env python3
"""Record all keyboard-save acceptance checks without waiving failures."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


def now():
    return datetime.now(timezone.utc).isoformat()


def git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=True
    ).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output_dir.resolve()
    if not args.output_dir.is_absolute() or output.is_relative_to(root):
        parser.error("--output-dir must be absolute and outside the checkout")
    output.mkdir(parents=True, exist_ok=True)
    frontend = root / "frontend"
    commands = [
        ("keyboard", ["npm", "run", "test:unit", "--", "--run",
                      "src/features/strategies/Editor.saveKeyboard"]),
        ("editor", ["npm", "run", "test:unit", "--", "--run",
                    "src/features/strategies/Editor"]),
        ("full-suite", ["npm", "run", "test:unit", "--", "--run"]),
        ("typecheck", ["npm", "run", "typecheck"]),
        ("build", ["npm", "run", "build", "--", "--outDir", str(output / "dist")]),
    ]
    report = {
        "started_at": now(),
        "tested_git_sha": git(root, "rev-parse", "HEAD"),
        "git_status_porcelain": git(root, "status", "--porcelain"),
        "repository": str(root),
        "output_dir": str(output),
        "summary_path": str(output / "summary.json"),
        "dist_path": str(output / "dist"),
        "checks": [],
    }
    for name, command in commands:
        log_path = output / f"{name}.log"
        check = {
            "name": name,
            "command": command,
            "cwd": str(frontend),
            "started_at": now(),
            "log_path": str(log_path),
        }
        print(f"Running {name}: {command}", flush=True)
        with log_path.open("w", encoding="utf-8") as log:
            try:
                result = subprocess.run(
                    command, cwd=frontend, stdout=log,
                    stderr=subprocess.STDOUT, check=False,
                )
                check["exit_code"] = result.returncode
            except OSError as error:
                log.write(f"Could not execute command: {error}\n")
                check["exit_code"] = 127
        check["ended_at"] = now()
        report["checks"].append(check)
        print(f"{name}: exit {check['exit_code']} ({log_path})", flush=True)
    report["ended_at"] = now()
    report["passed"] = all(check["exit_code"] == 0 for check in report["checks"])
    (output / "summary.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Summary: {output / 'summary.json'}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
