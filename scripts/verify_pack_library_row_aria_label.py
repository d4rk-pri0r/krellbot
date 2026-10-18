#!/usr/bin/env python3
"""Offline source + runtime verification for the PackLibrary row aria-label slice.

Checks that frontend/src/features/packs/PackLibrary.tsx carries the new
per-row aria-label summary on the existing row <li> without disturbing any
pre-existing surface (children, copy-button label, aria-busy wiring), then
runs the focused Vitest suite, typecheck (compared against the base
diagnostics, since inherited check debt exists), build and git diff --check.
AX semantics are evidence for assistive tech, not a claim of audible
screen-reader output. Uses only the standard library.

Run: uv run --frozen python scripts/verify_pack_library_row_aria_label.py
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
BASE = "d70791d69bf26e360f4325e2cfd77f8799a205b7"
COMPONENT = "frontend/src/features/packs/PackLibrary.tsx"
TEST = "frontend/src/features/packs/PackLibrary.rowAriaLabel.test.tsx"
SCRIPT = "scripts/verify_pack_library_row_aria_label.py"
ALLOWED = {COMPONENT, TEST, SCRIPT}
TESTS = [
    "src/features/packs/PackLibrary.rowAriaLabel.test.tsx",
    "src/features/packs/PackLibrary.test.tsx",
    "src/features/packs/PackLibrary.signal.test.tsx",
    "src/features/packs/PackLibrary.ariaBusy.test.tsx",
    "src/features/packs/PackLibrary.clipboardFailure.test.tsx",
]
REQUIRED = [
    "source_read", "row_aria_label_shape", "bucket_label_reuse",
    "child_testids_preserved", "existing_button_aria_labels_preserved",
    "allowlist_enforced", "runtime_tests", "typecheck_no_slice_errors", "build",
    "diff_check", "verification_commands_recorded",
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, timeout=30).strip()


def git_show(path: str, ref: str = BASE) -> str:
    return subprocess.check_output(
        ["git", "show", f"{ref}:{path}"], cwd=ROOT, text=True, timeout=30)


def extract(pattern: str, source: str) -> str:
    match = re.search(pattern, source, re.DOTALL)
    if match is None:
        raise AssertionError(f"Missing source pattern: {pattern}")
    return match.group(0)


def main() -> int:
    self_argv = ["uv", "run", "--frozen", "python", SCRIPT]
    summary = {
        "tested_sha": git("rev-parse", "HEAD"),
        "source_dirty": bool(git("status", "--porcelain")),
        "base_sha": BASE,
        "invocation": self_argv,
        "required_assertions": dict.fromkeys(REQUIRED, False),
        "commands": [],
        "limits": ("Source + jsdom only; real-browser and audible screen-reader "
                   "verification remain with the Operator."),
    }
    checks = summary["required_assertions"]

    def run(argv: list[str], cwd: Path, name: str) -> dict:
        try:
            label = str(cwd.relative_to(ROOT))
        except ValueError:
            label = str(cwd)
        record = {"name": name, "cwd": label, "argv": argv, "exit": None}
        summary["commands"].append(record)
        try:
            result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                                    timeout=300)
            record.update(exit=result.returncode, output=result.stdout + result.stderr)
        except subprocess.TimeoutExpired:
            record.update(exit=124, output="Command exceeded 300 seconds")
        return record

    def attrs_of(tag: str) -> set[str]:
        return set(re.findall(r"([A-Za-z-]+)=", tag))

    try:
        source = (ROOT / COMPONENT).read_text()
        base = git("show", f"{BASE}:{COMPONENT}")
        summary["source_hashes"] = {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in sorted(ALLOWED) if (ROOT / name).exists()
        }
        checks["source_read"] = bool(source and base)

        # 1. The row <li> gains exactly one attribute — aria-label={rowSummary};
        #    the className and data-testid stay and no role is introduced.
        li = extract(
            r'<li\b[^>]*data-testid=\{`pack-library-row-\$\{row\.pack_id\}`\}[^>]*>', source)
        li_base = extract(
            r'<li\b[^>]*data-testid=\{`pack-library-row-\$\{row\.pack_id\}`\}[^>]*>', base)
        checks["row_aria_label_shape"] = (
            "aria-label={rowSummary}" in li
            and 'className="kbot-pack-library__row"' in li
            and "role=" not in li
            and attrs_of(li) == attrs_of(li_base) | {"aria-label"}
        )

        # 2. rowSummary is computed in PackRowItem with the required shape and
        #    reuses the file-local bucketLabel helper (no new prop/import).
        summary_expr = extract(r"const rowSummary = `.*?`;", source)
        checks["row_aria_label_shape"] = checks["row_aria_label_shape"] and all(
            fragment in summary_expr for fragment in (
                "`Pack ${row.pack_id}, bucket ",
                "${bucketLabel(row.bucket)}",
                "}, version ${",
                'row.version ?? "unspecified"',
                "}, permissions ${",
                'row.permissions.length > 0 ? row.permissions.join(", ") : "none"',
                "}, prior revision ${priorRevision}`;",
            ))
        checks["bucket_label_reuse"] = (
            "bucketLabel(row.bucket)" in summary_expr
            and not re.search(r"import\b[^;]*bucketLabel", source)
            and extract(r"function bucketLabel\([^)]*\): string \{[^}]*\}", source)
            == extract(r"function bucketLabel\([^)]*\): string \{[^}]*\}", base)
            and not re.search(r"rowSummary|bucketLabel", extract(
                r"type PackRowItemProps = \{.*?\};", source))
        )

        # 3. Every child under the row <li> is byte-equal to base, so all
        #    existing data-testids, classNames and visible text survive.
        children = r'(<div className="kbot-pack-library__row-head">.*?</dl>)'
        checks["child_testids_preserved"] = (
            extract(children, source) == extract(children, base)
            and all(f'`pack-library-{part}-${{row.pack_id}}`' in extract(children, source)
                    for part in ("bucket", "id", "copy", "copy-feedback", "version",
                                 "permissions", "rollback-ref"))
            and 'data-testid={`pack-library-row-${row.pack_id}`}' in li
        )

        # 4. Pre-existing aria-labels are untouched: the per-row copy button
        #    and the region label the aria-busy slice relied upon.
        copy_button = r'<button\b[^>]*data-testid=\{`pack-library-copy-\$\{row\.pack_id\}`\}[^>]*>'
        checks["existing_button_aria_labels_preserved"] = (
            extract(copy_button, source) == extract(copy_button, base)
            and 'aria-label={`Copy pack_id ${row.pack_id}`}' in extract(copy_button, source)
            and extract(r'<section\b.*?>', source) == extract(r'<section\b.*?>', base)
            and 'aria-label="Pack library"' in extract(r'<section\b.*?>', source)
        )

        changed = set(git("diff", "--name-only", BASE).splitlines())
        changed.update(git("ls-files", "--others", "--exclude-standard").splitlines())
        summary["changed_files"] = sorted(changed)
        checks["allowlist_enforced"] = changed <= ALLOWED and all(
            git_show(path) == (ROOT / path).read_text() for path in (
                "frontend/src/features/packs/client.ts",
                "frontend/src/features/packs/PackLibrary.signal.css",
                "frontend/src/features/packs/PackLibrary.test.tsx",
            ))

        checks["runtime_tests"] = run(
            ["npm", "run", "test:unit", "--", "run", *TESTS], FRONTEND,
            "focused_tests")["exit"] == 0

        current_typecheck = run(["npm", "run", "typecheck"], FRONTEND, "typecheck")
        # Inherited check debt exists at the baseline (paper / strategies /
        # PackLibrary.test.tsx); this slice must add none of its own, so the
        # diagnostics are compared against a typecheck of the base tree.
        with tempfile.TemporaryDirectory(prefix="krellbot-row-aria-base-") as temp:
            archive = subprocess.check_output([
                "git", "archive", BASE, "frontend/src", "frontend/tsconfig.json",
                "frontend/package.json"], cwd=ROOT, timeout=30)
            with tarfile.open(fileobj=io.BytesIO(archive)) as contents:
                for member in contents.getmembers():
                    if member.isfile():
                        target = Path(temp) / member.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(contents.extractfile(member).read())
            baseline_frontend = Path(temp) / "frontend"
            (baseline_frontend / "node_modules").symlink_to(
                FRONTEND / "node_modules", target_is_directory=True)
            baseline_typecheck = run(["npm", "run", "typecheck"], baseline_frontend,
                                     "typecheck_base")

        def diagnostics(record: dict) -> list[str]:
            output = re.sub(r"\x1b\[[0-9;]*m", "", record["output"])
            return sorted(line for line in output.splitlines() if " error TS" in line)

        current_errors, baseline_errors = diagnostics(current_typecheck), diagnostics(baseline_typecheck)
        summary["typecheck_diagnostics_match_base"] = current_errors == baseline_errors
        checks["typecheck_no_slice_errors"] = (
            current_errors == baseline_errors
            and not any("PackLibrary.rowAriaLabel" in line or "PackLibrary.tsx" in line
                        for line in current_errors)
        )

        checks["build"] = run(["npm", "run", "build"], FRONTEND, "build")["exit"] == 0
        checks["diff_check"] = run(["git", "diff", "--check"], ROOT, "diff_check")["exit"] == 0

        checks["verification_commands_recorded"] = (
            len(summary["commands"]) == 5
            and all(set(command) == {"name", "cwd", "argv", "exit", "output"}
                    for command in summary["commands"])
        )
    except Exception as error:
        summary["failure"] = f"{type(error).__name__}: {error}"
    summary["qualified"] = all(checks.values())
    # The verifier is the sixth verification command; its exit is fully
    # determined once every assertion is computed, so it is recorded
    # truthfully here (the process returns exactly this value below).
    summary["commands"].append({
        "name": SCRIPT.rsplit("/", 1)[-1], "cwd": ".", "argv": self_argv,
        "exit": 0 if summary["qualified"] else 1,
    })
    print(json.dumps(summary, indent=2))
    return 0 if summary["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
