"""Paper coverage gate. Refuses to count a day when the clock file is absent.

Never creates the clock file. A missing clock is not a started soak.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def evaluate(home: Path) -> str:
    clock = Path(home) / "paper-clock.json"
    if not clock.exists():
        return "clock-not-started"
    try:
        record = json.loads(clock.read_text())
    except (OSError, json.JSONDecodeError):
        return "coverage-incomplete"
    if not isinstance(record, dict) or not record.get("started_at"):
        return "coverage-incomplete"
    if not isinstance(record.get("expected_evaluations"), int):
        return "coverage-incomplete"
    return "counted"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("clock-not-started")
        return 2
    code = evaluate(Path(args[0]))
    print(code)
    return 0 if code == "counted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
