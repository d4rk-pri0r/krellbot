#!/usr/bin/env python3
"""Offline source + runtime verification for the Strategy explanation supported
aria slice.

Checks that frontend/src/features/strategies/StrategyExplanation.tsx exposes the
supported/unsupported signal on the existing indicator and market <li> rows via
role="listitem" plus a per-row aria-label derived from the runtime
indicator/market data inside the same map iteration, while every pre-existing
surface (visible text, data-supported, keys, classNames, parent <ul> testids,
sibling status/paragraph contracts, ConditionList/MetadataRow/props contract)
stays byte-equal to the base. The aria-label semantics are additionally
exercised on the mounted component through the focused Vitest suite.
Inherited typecheck debt exists at the baseline (packs/paper/strategies copy
tests); this slice must add none of its own, so diagnostics are compared
against a typecheck of the base tree. AX semantics are evidence for assistive
tech, not a claim of audible screen-reader output. Uses only the standard
library.

Run: python3 scripts/verify_strategy_explanation_supported_aria.py
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BASE = "d285b94ddf5c98e0a26d8d020c406b6b3bc4041b"
COMPONENT = "frontend/src/features/strategies/StrategyExplanation.tsx"
TEST = "frontend/src/features/strategies/StrategyExplanation.supportedAria.test.tsx"
SCRIPT = "scripts/verify_strategy_explanation_supported_aria.py"
ALLOWED = {COMPONENT, TEST, SCRIPT}
TESTS = [
    "src/features/strategies/StrategyExplanation.supportedAria.test.tsx",
    "src/features/strategies/StrategyExplanation.test.tsx",
]
READ_ONLY = [
    "frontend/src/features/strategies/explainPack.ts",
    "frontend/src/features/strategies/StrategyExplanation.test.tsx",
    "frontend/src/features/strategies/StrategyExplanation.signal.css",
    "frontend/src/features/strategies/StrategyExplanationCsvExport.tsx",
    "frontend/src/features/strategies/Editor.tsx",
]
REQUIRED = [
    "source_read", "indicator_li_role_and_aria_shape", "market_li_role_and_aria_shape",
    "li_attribute_delta_exactly_role_and_aria_label", "li_visible_text_byte_equal",
    "aria_label_runtime_derived_in_map", "ul_testid_contracts_unchanged",
    "data_supported_preserved", "parent_and_sibling_contracts_unchanged",
    "focused_test_file_present", "allowlist_enforced", "runtime_tests",
    "typecheck_no_slice_errors", "build", "diff_check",
    "verification_commands_recorded",
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, timeout=60).strip()


def git_show(path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{BASE}:{path}"], cwd=ROOT, text=True, timeout=60)


def extract(pattern: str, source: str) -> str:
    match = re.search(pattern, source, re.DOTALL)
    if match is None:
        raise AssertionError(f"Missing source pattern: {pattern}")
    return match.group(0)


def li_attrs(tag: str) -> set[str]:
    return set(re.findall(r"([A-Za-z-]+)=", tag))


def main() -> int:
    self_argv = ["python3", SCRIPT]
    summary = {
        "tested_sha": git("rev-parse", "HEAD"),
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
                                    timeout=420)
            record.update(exit=result.returncode, output=result.stdout + result.stderr)
        except subprocess.TimeoutExpired:
            record.update(exit=124, output="Command exceeded 420 seconds")
        return record

    try:
        source = (ROOT / COMPONENT).read_text()
        base = git_show(COMPONENT)
        checks["source_read"] = bool(source and base)

        indicator_map = extract(
            r"\{explanation\.indicators\.map\(\(indicator, index\) => \([\s\S]*?\)\)\}", source)
        indicator_map_base = extract(
            r"\{explanation\.indicators\.map\(\(indicator, index\) => \([\s\S]*?\)\)\}", base)
        market_map = extract(
            r"\{explanation\.markets\.map\(\(market, index\) => \([\s\S]*?\)\)\}", source)
        market_map_base = extract(
            r"\{explanation\.markets\.map\(\(market, index\) => \([\s\S]*?\)\)\}", base)

        # (a)+(b)+(e) role="listitem" plus the supported/unsupported aria-label
        # bound to the same runtime flag that drives data-supported="1"/"0".
        indicator_li = extract(r"<li\b[^>]*>", indicator_map)
        market_li = extract(r"<li\b[^>]*>", market_map)
        checks["indicator_li_role_and_aria_shape"] = (
            'role="listitem"' in indicator_li
            and 'aria-label={`${indicator.supported ? "Supported" : "Unsupported"} indicator: ${indicator.text}`}'
            in indicator_li
        )
        checks["market_li_role_and_aria_shape"] = (
            'role="listitem"' in market_li
            and 'aria-label={`${market.supported ? "Supported" : "Unsupported"} market: ${market.text}`}'
            in market_li
        )
        checks["data_supported_preserved"] = (
            'data-supported={indicator.supported ? "1" : "0"}' in indicator_li
            and 'data-supported={market.supported ? "1" : "0"}' in market_li
            and 'data-supported={indicator.supported ? "1" : "0"}'
            in extract(r"<li\b[^>]*>", indicator_map_base)
            and 'data-supported={market.supported ? "1" : "0"}'
            in extract(r"<li\b[^>]*>", market_map_base)
        )

        # Exactly the two new attributes are added; key, className and every
        # other attribute of each row <li> stay byte-equal to the base.
        checks["li_attribute_delta_exactly_role_and_aria_label"] = (
            li_attrs(indicator_li)
            == li_attrs(extract(r"<li\b[^>]*>", indicator_map_base)) | {"role", "aria-label"}
            and li_attrs(market_li)
            == li_attrs(extract(r"<li\b[^>]*>", market_map_base)) | {"role", "aria-label"}
            and extract(r"key=\{[^}]*\}", indicator_li)
            == extract(r"key=\{[^}]*\}", extract(r"<li\b[^>]*>", indicator_map_base))
            and extract(r"key=\{[^}]*\}", market_li)
            == extract(r"key=\{[^}]*\}", extract(r"<li\b[^>]*>", market_map_base))
            and 'className="kbot-feature__strategy-explanation-list-item"' in indicator_li
            and 'className="kbot-feature__strategy-explanation-list-item"' in market_li
        )

        # (c) The visible text inside each <li> is byte-equal runtime data.
        checks["li_visible_text_byte_equal"] = (
            extract(r">\s*\{indicator\.text\}\s*</li>", indicator_map)
            == extract(r">\s*\{indicator\.text\}\s*</li>", indicator_map_base)
            and extract(r">\s*\{market\.text\}\s*</li>", market_map)
            == extract(r">\s*\{market\.text\}\s*</li>", market_map_base)
        )

        # The label is derived inside the same map iteration from the mapped
        # row (recomputed per render, exact runtime data, no static copy).
        checks["aria_label_runtime_derived_in_map"] = (
            "aria-label" in indicator_li and "aria-label" in market_li
            and "indicator.text" in indicator_li and "market.text" in market_li
            and "indicator.supported" in indicator_li and "market.supported" in market_li
            and not re.search(r'aria-label="[^"{]*"', indicator_map + market_map)
            and not re.search(r"aria-label=\{[^}`]*\}", indicator_map + market_map)
        )

        # (d) Parent <ul> contracts unchanged.
        ul_ok = True
        for testid in ("strategy-explanation-indicators", "strategy-explanation-markets"):
            pattern = rf'<ul\b[^>]*data-testid="{testid}"[^>]*>'
            ul_ok = ul_ok and extract(pattern, source) == extract(pattern, base)
        checks["ul_testid_contracts_unchanged"] = ul_ok

        # Parent <section>, header/status/paragraph siblings and the
        # ConditionList / MetadataRow / props contract stay byte-equal.
        checks["parent_and_sibling_contracts_unchanged"] = all(
            extract(pattern, source) == extract(pattern, base)
            for pattern in (
                r'<section\b[^>]*data-testid="strategy-explanation"[^>]*>',
                r'<header\b.*?</header>',
                r'<p\b[^>]*data-testid="strategy-explanation-revision"[^>]*>.*?</p>',
                r'<p\b[^>]*data-testid="strategy-explanation-unparsed"[^>]*>.*?</p>',
                r'<p\b[^>]*data-testid="strategy-explanation-unknowns"[^>]*>.*?</p>',
                r'<p\b[^>]*data-testid="strategy-explanation-allocation"[^>]*>.*?</p>',
                r'<p\b[^>]*data-testid="strategy-explanation-stop"[^>]*>.*?</p>',
                r'<p\b[^>]*data-testid="strategy-explanation-performance"[^>]*>.*?</p>',
                r"function ConditionList\([\s\S]*?\n\}",
                r"function MetadataRow\([\s\S]*?\n\}",
                r"export type StrategyExplanationProps = \{[\s\S]*?\};",
                r"const explanation = useMemo<ExplainResult>\([\s\S]*?\);",
                r"<StrategyExplanationCsvExport[^>]*/>",
            )
        )

        test_source = (ROOT / TEST).read_text()
        checks["focused_test_file_present"] = (
            "Supported indicator:" in test_source
            and "Unsupported indicator:" in test_source
            and "Supported market:" in test_source
            and "Unsupported market:" in test_source
            and '"listitem"' in test_source
            and "strategy-explanation-indicators" in test_source
            and "strategy-explanation-markets" in test_source
            and "rerender(" in test_source
            and "data-supported" in test_source
        )

        changed = set(git("diff", "--name-only", BASE).splitlines())
        changed.update(git("ls-files", "--others", "--exclude-standard").splitlines())
        checks["allowlist_enforced"] = (
            changed <= ALLOWED
            and all((ROOT / path).read_text() == git_show(path) for path in READ_ONLY)
        )

        checks["runtime_tests"] = run(
            ["npm", "run", "test:unit", "--", "--run", *TESTS], FRONTEND,
            "focused_tests")["exit"] == 0

        current_typecheck = run(["npm", "run", "typecheck"], FRONTEND, "typecheck")
        # Inherited check debt exists at the baseline (packs / paper /
        # SavedStrategyLibrary copy tests); this slice must add none of its own,
        # so the diagnostics are compared against a typecheck of the base tree.
        with tempfile.TemporaryDirectory(prefix="krellbot-supported-aria-base-") as temp:
            archive = subprocess.check_output([
                "git", "archive", BASE, "frontend/src", "frontend/tsconfig.json",
                "frontend/package.json", "frontend/vite.config.ts"], cwd=ROOT, timeout=60)
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
            output = re.sub(r"\x1b\[[0-9;]*m", "", record["output"] or "")
            return sorted(line for line in output.splitlines() if " error TS" in line)

        current_errors = diagnostics(current_typecheck)
        baseline_errors = diagnostics(baseline_typecheck)
        summary["typecheck_diagnostics_match_base"] = current_errors == baseline_errors
        checks["typecheck_no_slice_errors"] = (
            current_errors == baseline_errors
            and not any("StrategyExplanation" in line for line in current_errors)
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
    summary["commands"].append({
        "name": SCRIPT.rsplit("/", 1)[-1], "cwd": ".", "argv": self_argv,
        "exit": 0 if summary["qualified"] else 1,
    })
    print(json.dumps(summary, indent=2))
    return 0 if summary["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
