#!/usr/bin/env python3
"""Run all Export result busy checks, preserving every exit and external log."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SOURCE_BASE = "c5f460a51757a621cdcbadf7ccd21ba6194112b3"
FILES = (
    "frontend/src/features/research/ResearchView.tsx",
    "frontend/src/features/research/ResearchView.exportResultBusy.test.tsx",
    "scripts/verify_research_export_result_busy.py",
)
COMMANDS = (
    ("focused", ["npx", "vitest", "run",
                 "src/features/research/ResearchView.exportResultBusy.test.tsx",
                 "src/features/research/ResearchView.test.tsx",
                 "src/features/research/ResearchView.loadResultBusy.test.tsx"]),
    ("unit", ["npm", "run", "test:unit", "--", "--run"]),
    ("typecheck", ["npm", "run", "typecheck"]),
    ("build", ["npm", "run", "build"]),
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.expanduser().resolve()
    if out == ROOT or ROOT in out.parents:
        parser.error("Verification artifacts must remain outside the checkout")
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "start": now(),
        "source_base": SOURCE_BASE,
        "tested_git_sha": git("rev-parse", "HEAD"),
        "source_status": git("status", "--porcelain"),
        "source_hashes": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in FILES
        },
        "output_dir": str(out),
        "summary_path": str(out / "summary.json"),
        "missing_requested_test_paths": [
            name for name in ["frontend/src/features/research/ResearchView.loadResultBusy.test.tsx"]
            if not (ROOT / name).exists()
        ],
        "browser_acceptance": "Not performed; independent mounted desktop/mobile keyboard review required",
        "commands": [],
    }
    for name, argv in COMMANDS:
        log = out / f"{name}.log"
        record = {"argv": argv, "cwd": str(ROOT / "frontend"),
                  "start": now(), "log": str(log)}
        try:
            with log.open("w") as stream:
                result = subprocess.run(argv, cwd=ROOT / "frontend", stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=600)
            record["exit"] = result.returncode
        except subprocess.TimeoutExpired as exc:
            record.update(exit=124, error=str(exc))
        except OSError as exc:
            record.update(exit=1, error=str(exc))
        record["end"] = now()
        summary["commands"].append(record)
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"{name}: exit={record['exit']} log={log}", flush=True)
    summary["end"] = now()
    summary["exit"] = int(any(record["exit"] != 0 for record in summary["commands"]))
    summary["passed"] = summary["exit"] == 0
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"summary: {out / 'summary.json'}", flush=True)
    return summary["exit"]


if __name__ == "__main__":
    raise SystemExit(main())
