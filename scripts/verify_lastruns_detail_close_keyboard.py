#!/usr/bin/env python3
"""Exercise shipped last-runs detail dismissal through the Vitest DOM harness."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TEST = "src/features/paper/LastRunsPanel.detailCloseKeyboard.test.tsx"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=120, help="Child test deadline in seconds")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    node = shutil.which("node")
    vitest = ROOT / "frontend/node_modules/vitest/vitest.mjs"
    if node is None or not vitest.is_file():
        parser.exit(2, "Install Node and frontend dependencies before running this verifier.\n")
    try:
        result = subprocess.run(
            [node, str(vitest), "run", TEST],
            cwd=ROOT / "frontend",
            env={**os.environ, "NODE_ENV": "test"},
            timeout=args.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("Last-runs detail close keyboard verification timed out.")
        return 124
    return result.returncode if result.returncode >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
