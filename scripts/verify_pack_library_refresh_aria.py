#!/usr/bin/env python3
"""Offline source + runtime verification for the PackLibrary refresh aria-busy slice.

Checks that frontend/src/features/packs/PackLibrary.tsx carries the new
aria-busy / polite live-region affordance on the existing refresh button
without disturbing any pre-existing surface, then runs the focused Vitest
suite, typecheck and build. AX semantics are evidence for assistive tech,
not a claim of audible screen-reader output. Uses only the standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SOURCE = "frontend/src/features/packs/PackLibrary.tsx"
BASE = "34b183592d08b63e772813e36aabc3b1887874c1"
TESTS = (
    "src/features/packs/PackLibrary.ariaBusy.test.tsx",
    "src/features/packs/PackLibrary.test.tsx",
    "src/features/packs/PackLibrary.signal.test.tsx",
    "src/features/packs/PackLibrary.clipboardFailure.test.tsx",
)
REQUIRED = (
    "source_read", "button_aria_busy", "polite_status_region", "status_text_truth",
    "existing_button_surface_unchanged", "new_testid_only_addition",
    "client_and_css_unchanged", "runtime_tests", "typecheck_no_slice_errors",
    "build", "verification_commands_recorded",
)


def run(argv: list[str], directory: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=directory, text=True, capture_output=True,
                          timeout=timeout, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir or Path(tempfile.mkdtemp(prefix="pack-library-refresh-aria-"))
    out.mkdir(parents=True, exist_ok=True)
    assertions = dict.fromkeys(REQUIRED, False)
    commands: list[dict[str, object]] = []
    results: dict[str, object] = {
        "qualified": False,
        "required_assertions": assertions,
        "baseline": BASE,
        "source_path": SOURCE,
        "verification_commands": commands,
    }

    def record(name: str, cwd: str, argv: list[str], process: subprocess.CompletedProcess[str]) -> int:
        (out / f"{name}.log").write_text(process.stdout + process.stderr)
        commands.append({"name": name, "cwd": cwd, "argv": argv,
                         "exit": process.returncode})
        return process.returncode

    try:
        def git(*a: str) -> str:
            return subprocess.run(
                ["git", *a], cwd=ROOT, text=True, capture_output=True, check=False
            ).stdout
        source = (FRONTEND / "src/features/packs/PackLibrary.tsx").read_text()
        results["head"] = git("rev-parse", "HEAD").strip()
        results["source_sha256"] = hashlib.sha256(source.encode()).hexdigest()
        assertions["source_read"] = True

        buttons = re.findall(r"<button\b(.*?)>", source, re.S)
        refresh = next((b for b in buttons if 'data-testid="pack-library-refresh"' in b), "")
        assertions["button_aria_busy"] = "aria-busy={refreshing}" in refresh

        status = re.search(
            r'<p\b(?P<attrs>[^>]*data-testid="pack-library-refresh-status"[^>]*)>'
            r'(?P<body>.*?)</p>', source, re.S)
        assertions["polite_status_region"] = bool(status) and all(value in status.group("attrs") for value in (
            'role="status"', 'aria-live="polite"',
            'className="kbot-pack-library__refresh-status"',
        ))
        assertions["status_text_truth"] = bool(status) and bool(re.search(
            r'\{refreshing \? "Reading installed packs\u2026" : ""\}', status.group("body")))

        assertions["existing_button_surface_unchanged"] = all(value in refresh for value in (
            'className="kbot-pack-library__refresh"', "disabled={refreshing}",
            "aria-disabled={refreshing}", "onClick={handleRefresh}", 'type="button"',
        )) and '{refreshing ? "Refreshing\u2026" : "Refresh"}' in source

        baseline = git("show", f"{BASE}:{SOURCE}")
        before = set(re.findall(r'data-testid="([^"]+)"', baseline))
        after = set(re.findall(r'data-testid="([^"]+)"', source))
        assertions["new_testid_only_addition"] = (
            before <= after and after - before == {"pack-library-refresh-status"}
        )
        assertions["client_and_css_unchanged"] = all(
            git("show", f"{BASE}:{path}") == (ROOT / path).read_text() for path in (
                "frontend/src/features/packs/client.ts",
                "frontend/src/features/packs/PackLibrary.signal.css",
            )
        )

        tests_argv = ["npm", "run", "test:unit", "--", "run", *TESTS]
        tests = run(tests_argv, FRONTEND, timeout=300)
        record("focused_tests", "frontend", tests_argv, tests)
        assertions["runtime_tests"] = tests.returncode == 0

        typecheck_argv = ["npm", "run", "typecheck"]
        typecheck = run(typecheck_argv, FRONTEND, timeout=300)
        record("typecheck", "frontend", typecheck_argv, typecheck)
        # Inherited check debt exists at the baseline; this slice must add none
        # of its own (no error may name the packs files it touched).
        assertions["typecheck_no_slice_errors"] = not re.search(
            r"features/packs/PackLibrary(\.ariaBusy\.test)?\.tsx?[^\n]*error", typecheck.stdout + typecheck.stderr)

        build_argv = ["npm", "run", "build"]
        build = run(build_argv, FRONTEND, timeout=300)
        record("build", "frontend", build_argv, build)
        assertions["build"] = build.returncode == 0

        self_argv = ["uv", "run", "--frozen", "python", "scripts/verify_pack_library_refresh_aria.py"]
        assertions["verification_commands_recorded"] = (
            len(commands) == 3
            and all(set(command) == {"name", "cwd", "argv", "exit"} for command in commands)
        )
        results["qualified"] = all(assertions.values())
        # The verifier is the fourth verification command; its exit is fully
        # determined once every assertion is computed, so it can be recorded
        # truthfully here (the process returns exactly this value below).
        results["verification_commands"] = commands + [{
            "name": "verify_pack_library_refresh_aria", "cwd": ".", "argv": self_argv,
            "exit": 0 if results["qualified"] else 1,
        }]
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        results["error"] = str(error)
    report = out / "summary.json"
    report.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({**results, "summary_file": str(report.resolve())}, indent=2))
    return 0 if results["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
