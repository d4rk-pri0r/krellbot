#!/usr/bin/env python3
"""Run all Research Run busy checks, retaining every failure outside checkout."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SOURCE_BASE = "c5f460a51757a621cdcbadf7ccd21ba6194112b3"
FOCUSED_TESTS = [
    "src/features/research/ResearchView.runBusy.test.tsx",
    "src/features/research/ResearchView.test.tsx",
    "src/features/research/ResearchView.loadResultBusy.test.tsx",
    "src/features/research/ResearchView.exportResultBusy.test.tsx",
]
COMMANDS = [
    ["npx", "vitest", "run", *FOCUSED_TESTS],
    ["npm", "run", "test:unit", "--", "--run"],
    ["npm", "run", "typecheck"],
    ["npm", "run", "build"],
]
PATHS = [
    "frontend/src/features/research/ResearchView.tsx",
    "frontend/src/features/research/ResearchView.runBusy.test.tsx",
    "scripts/verify_research_run_busy.py",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path.home() / ".cache/research-run-busy-aria-w2-20261017/verify",
    )
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if out == ROOT or ROOT in out.parents:
        parser.error("Verification output must be outside checkout")
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "start": now(), "end": None, "source_base": SOURCE_BASE,
        "tested_git_sha": git("rev-parse", "HEAD"),
        "source_status": git("status", "--porcelain=v1"),
        "paths": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in PATHS},
        "missing_requested_tests": [name for name in FOCUSED_TESTS if not (FRONTEND / name).is_file()],
        "output_dir": str(out), "commands": [], "exit": None,
        "limits": "Unit/type/build checks only; independent real-backend desktop/mobile keyboard review required.",
    }
    for index, argv in enumerate(COMMANDS, 1):
        log = out / f"{index}.log"
        record = {"argv": argv, "cwd": str(FRONTEND), "start": now(), "log": str(log)}
        with log.open("w") as stream:
            try:
                result = subprocess.run(
                    argv, cwd=FRONTEND, stdout=stream, stderr=subprocess.STDOUT,
                    timeout=600, check=False,
                )
                record["exit"] = result.returncode
            except subprocess.TimeoutExpired as error:
                record.update(exit=124, error=str(error))
            except OSError as error:
                record.update(exit=127, error=str(error))
        record["end"] = now()
        summary["commands"].append(record)
        print(json.dumps(record), flush=True)
    summary["end"] = now()
    summary["exit"] = int(any(record["exit"] != 0 for record in summary["commands"]))
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"exit": summary["exit"], "summary": str(out / "summary.json")}), flush=True)
    return summary["exit"]


if __name__ == "__main__":
    raise SystemExit(main())
