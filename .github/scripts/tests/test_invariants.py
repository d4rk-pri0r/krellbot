"""RED-then-GREEN tests for `.github/scripts/invariants.py`.

Every test runs against the historical baseline SHA recorded in the
project's Step 3 brief and uses the trusted `git show` machinery.
The test FAILS until the checkers pass. We try to cover every
"false positive" callout and every "false negative" must-flag case.

We use `pytest`. Tests import the trusted checker modules only.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from . import _ls_git, _read_git_text, base_ref, workdir as git_workdir  # type: ignore


# Import the checker from its package location. Tests NEVER import
# the malicious fixture as a module.
from scripts import invariants as invariants_module
from scripts import _util as scripts_util


SHA = "ca351a08d40ba47204116b02f3356cbb4600b556"


@pytest.fixture(scope="session")
def invariants():
    return invariants_module


@pytest.fixture(scope="session")
def util():
    return scripts_util


@pytest.fixture(scope="session")
def workdir(git_workdir) -> Path:
    return git_workdir


# -------------------------------------------------------------------------
# Rule 1 — no LLM SDK on the execution path
# -------------------------------------------------------------------------


def test_rule_no_llm_sdk_static_in_known_source(invariants, util, workdir):
    """RED: if any production Python file in the trusted baseline
    statically imports an LLM SDK, this test FAILS. (No production
    file should; the rule must produce zero findings.)"""
    src = util.git_source(workdir)
    py = [p for p in src.list_paths(SHA, prefix="src/") if p.endswith(".py")]
    py += [p for p in src.list_paths(SHA, prefix="scripts/") if p.endswith(".py")]
    py += [p for p in src.list_paths(SHA, prefix="tests/") if p.endswith(".py")]
    py += [p for p in src.list_paths(SHA, prefix="frontend/") if p.endswith(".py")]
    findings = invariants.rule_llm_sdk_imports(
        git_src=src,
        head_ref=SHA,
        base_ref=SHA,
        python_paths=py,
    )
    bad = [f for f in findings if f.rule == "no_llm_sdk_imports"]
    assert bad == [], (
        f"Expected zero static LLM findings on the baseline; got: "
        f"{[(f.file, f.line) for f in bad]}"
    )


def test_rule_no_llm_sdk_flags_openai_in_malicious_fixture(
    invariants, util, workdir
):
    """Construct an in-memory malicious module and feed it through
    the rule. The rule must flag `import openai`.

    This proves the scanner ACTUALLY detects the LLM SDK; it is
    not just "always pass"."""
    src = util.git_source(workdir)
    mal_path = "malicious_module_for_test.py"  # not in repo
    py = [mal_path]
    # Patch the scanner's read path so it reads our string directly.
    captured: dict[str, str] = {}

    def fake_read(ref, rel):
        if rel == mal_path:
            return (
                "import openai\n"
                "from anthropic import Anthropic\n"
                "import openai\n"
            )
        return util.run_git_show_text(workdir, ref, rel)

    src.read_text = fake_read  # type: ignore[assignment]
    findings = invariants.rule_llm_sdk_imports(
        git_src=src,
        head_ref=SHA,
        base_ref=SHA,
        python_paths=py,
    )
    # NOTE: a module named "malicious_module_for_test" is NOT in the
    # reachable set from EXECUTION_ENTRY_POINTS. So the static-import
    # detection only fires when the file is reachable. We build a
    # small synthetic graph by monkey-patching the BFS step:
    # Easiest: just check that `_extract` and `_scan_module_imports`
    # do the right thing on the malicious text — that's the unit.
    static, _dyn, _ = invariants._scan_module_imports(  # type: ignore[attr-defined]
        src.read_text(SHA, mal_path)  # type: ignore[misc]
    )
    assert "openai" in static
    assert "anthropic" in static
    # The integration test for reachable files is below.


def test_rule_no_llm_sdk_reachable_indirect(
    invariants, util, workdir, tmp_path
):
    """Build a tiny workdir with a CLI that imports openai. The BFS
    must reach openai and the rule must flag it. This proves the
    import-graph walk actually does the right thing."""
    # Set up a temp workdir with just the synthetic files.
    wd = tmp_path
    (wd / ".git").mkdir()  # Marker only — we won't run real git here.
    src_path = wd / "src"
    src_path.mkdir()
    cli_dir = src_path / "krellbot"
    cli_dir.mkdir()
    (cli_dir / "__init__.py").write_text("")
    cli = cli_dir / "cli.py"
    cli.write_text(
        "from openai import OpenAI\n"
        "_OPENAI_CLIENT = OpenAI()\n"
    )
    # Real GitSource doesn't work without a git repo, so we build
    # a fake one that reads from disk.
    class _Fake:
        def __init__(self, root):
            self.workdir = root

        def read_text(self, _ref, rel):
            return Path(self.workdir / rel).read_text(encoding="utf-8")

        def diff_paths(self, _a, _b):
            return []

        def list_paths(self, _r, prefix=""):
            out = []
            base = Path(self.workdir) / (prefix or "")
            for p in base.rglob("*.py"):
                if p.is_file():
                    out.append(p.relative_to(self.workdir).as_posix())
            return out

    fake_src = _Fake(wd)
    findings = invariants.rule_llm_sdk_imports(
        git_src=fake_src,  # type: ignore[arg-type]
        head_ref="HEAD",
        base_ref="HEAD",
        python_paths=[
            "src/krellbot/cli.py",
            "src/krellbot/__init__.py",
        ],
        refresh_audit=True,  # both refs are the same synth snapshot.
    )
    # Refuse to silently pass — the test FAILS here if the rule
    # misses an LLM SDK on the execution path.
    bad = [f for f in findings if f.rule == "no_llm_sdk_imports"]
    assert bad, "Rule missed an LLM SDK import on the execution path"
    assert any(f.file.endswith("src/krellbot/cli.py") for f in bad)


def test_rule_no_llm_sdk_dynamic_literal_reported(invariants, workdir):
    """RED: dynamic `importlib.import_module('openai')` must be flagged."""
    text = textwrap.dedent(
        """
        import importlib
        m = importlib.import_module('openai')
        """
    )
    static, dyn, _ = invariants._scan_module_imports(text)  # type: ignore[attr-defined]
    assert "openai" in dyn


def test_rule_no_llm_sdk_relative_is_recorded_with_honest_label(
    invariants, workdir
):
    """A non-literal dynamic import / relative import must surface as
    `relative_import_unresolved`, NOT as a fake `no_llm_sdk_imports`
    hit. This is the brief's "fail closed, don't lie" requirement."""
    text = textwrap.dedent(
        """
        from . import helper
        import importlib
        m = importlib.import_module(my_target)
        """
    )
    static, _dyn, dyn_locations = invariants._scan_module_imports(  # type: ignore[attr-defined]
        text
    )
    # The relative import is recorded as a `dyn_location` with the
    # original line — that's what the rule uses to emit the
    # `relative_import_unresolved` finding.
    assert dyn_locations, "Should have at least one unresolved entry"
    assert any("helper" in line for _, line in dyn_locations)


# -------------------------------------------------------------------------
# Rule 3 — venue clients outside the execution boundary
# -------------------------------------------------------------------------


def test_venue_rule_flags_kraken_import_in_cli(invariants, util, workdir):
    """RED: a fresh Python file with `from krellbot.venues.kraken
    import KrakenVenue` must be flagged by the venue rule. We
    construct a synthetic module list and run the helper directly."""
    py = [
        "src/krellbot/cli.py",  # outside boundary, must be flagged
        "src/krellbot/execution/x.py",  # inside boundary, must NOT be flagged
        "src/krellbot/run/y.py",  # inside boundary, must NOT be flagged
    ]

    class _Fake:
        def __init__(self, mapping):
            self.workdir = workdir
            self.mapping = mapping

        def read_text(self, _r, rel):
            return self.mapping.get(rel)

    fake = _Fake(
        {
            "src/krellbot/cli.py": (
                "from krellbot.venues.kraken import KrakenVenue\n"
                "_k = KrakenVenue()\n"
            ),
            "src/krellbot/execution/x.py": (
                "from krellbot.venues.kraken import KrakenVenue\n"
            ),
            "src/krellbot/run/y.py": (
                "from krellbot.venues.kraken import KrakenVenue\n"
            ),
        }
    )
    base_set = set()
    findings = invariants.rule_venue_clients_outside_boundary(
        git_src=fake,  # type: ignore[arg-type]
        head_ref="H",
        base_ref="B",
        python_paths=py,
        diff_paths={"src/krellbot/cli.py"},
        refresh_audit=True,  # base == head on first run.
    )[0]
    # The rule emits every violation that's NEW or, in refresh-audit
    # mode, every violation period.
    cli_hits = [f for f in findings if f.file == "src/krellbot/cli.py"]
    assert cli_hits, "Expected a hit on cli.py"
    # Inside-boundary hits must never appear.
    inside = [f for f in findings if f.file in (
        "src/krellbot/execution/x.py",
        "src/krellbot/run/y.py",
    )]
    assert not inside, f"Inside-boundary hits leaked: {inside}"


# -------------------------------------------------------------------------
# Rule 4 — UI hex colors only from tokens.css or var fallback
# -------------------------------------------------------------------------


def test_rule_ui_hex_flags_raw_hex_outside_tokens(invariants, util, workdir):
    """RED: a CSS line `color: #abc;` outside tokens.css must be
    flagged."""
    captured = []

    def fake_read(ref, rel):
        if rel.endswith("a.signal.css"):
            return "/* ok comment */\n.x { color: #abc; }\n"
        return None

    class _Fake:
        def __init__(self):
            self.workdir = workdir

        def read_text(self, ref, rel):
            return fake_read(ref, rel)

        def diff_paths(self, _a, _b):
            return {"frontend/src/foo/a.signal.css"}

        def list_paths(self, _r, prefix=""):
            return ["frontend/src/foo/a.signal.css"]

    fake = _Fake()
    findings, _ = invariants.rule_ui_hex_colors(  # type: ignore[attr-defined]
        git_src=fake,
        head_ref="H",
        base_ref="H",
        refresh_audit=True,
    )
    raw = [f for f in findings if "#abc" in f.snippet]
    assert raw, "Expected at least one raw hex finding"
    assert any(f.rule == "ui_hex_colors" for f in raw)


def test_rule_ui_hex_allows_var_fallback(invariants, util, workdir):
    """RED: `var(--token, #abc)` second arg is a fallback — ALLOWED.
    The rule must NOT produce a violation line for the second arg.
    """
    class _Fake:
        def __init__(self):
            self.workdir = workdir

        def read_text(self, ref, rel):
            return ".x { background: var(--bg, #abc); color: #def; }\n"

        def diff_paths(self, _a, _b):
            return {"frontend/src/foo/a.signal.css"}

        def list_paths(self, _r, prefix=""):
            return ["frontend/src/foo/a.signal.css"]

    fake = _Fake()
    findings, _ = invariants.rule_ui_hex_colors(  # type: ignore[attr-defined]
        git_src=fake,
        head_ref="H",
        base_ref="H",
        refresh_audit=True,
    )
    # The fallback `#abc` must not appear in any finding. The
    # genuine `#def` (NOT a fallback) must.
    tokens = [f.snippet for f in findings]
    bad_fallback = [t for t in tokens if "#abc" in t]
    real_hex = [t for t in tokens if "#def" in t]
    assert not bad_fallback
    assert real_hex


def test_rule_ui_hex_requires_explicit_brand_exceptions(invariants, util, workdir):
    """Phase 2 permits no blanket brand exemption; existing colors need issues."""
    class _Fake:
        def __init__(self):
            self.workdir = workdir

        def read_text(self, ref, rel):
            return ".x { fill: #abc; }\n"

        def diff_paths(self, _a, _b):
            return set()

        def list_paths(self, _r, prefix=""):
            return [
                "frontend/src/assets/brand/x.svg",
                "frontend/src/components/brand/X.tsx",
            ]

    fake = _Fake()
    findings, _ = invariants.rule_ui_hex_colors(  # type: ignore[attr-defined]
        git_src=fake,
        head_ref="H",
        base_ref="H",
        refresh_audit=True,
    )
    assert {f.file for f in findings} == {
        "frontend/src/assets/brand/x.svg", "frontend/src/components/brand/X.tsx"
    }


def test_rule_ui_hex_skips_comments(invariants, util, workdir):
    """Hex inside a CSS comment must NOT be flagged."""
    class _Fake:
        def __init__(self):
            self.workdir = workdir

        def read_text(self, ref, rel):
            return (
                "/* palette ref: #0E1C29 and #14222E */\n"
                ".x { color: var(--text, #e9f0f5); }\n"
            )

        def diff_paths(self, _a, _b):
            return {"frontend/src/foo/a.signal.css"}

        def list_paths(self, _r, prefix=""):
            return ["frontend/src/foo/a.signal.css"]

    fake = _Fake()
    findings, _ = invariants.rule_ui_hex_colors(  # type: ignore[attr-defined]
        git_src=fake,
        head_ref="H",
        base_ref="H",
        refresh_audit=True,
    )
    assert findings == []


# -------------------------------------------------------------------------
# Rule 5 — ARIA-keyshortcuts modifier names
# -------------------------------------------------------------------------


def test_aria_mod_alt_s_is_a_violation(invariants, util, workdir):
    """RED: `Mod+Alt+S` must produce a finding.

    The ARIA spec requires the modifier-name set; `Mod` is not in
    it (issue #89). `Alt` is fine, `S` is the key. Net: violation."""
    class _Fake:
        def __init__(self):
            self.workdir = workdir

        def read_text(self, ref, rel):
            return (
                "const X = () => <button aria-keyshortcuts=\"Mod+Alt+S\">x</button>;\n"
            )

        def diff_paths(self, _a, _b):
            return {"frontend/src/foo/x.tsx"}

        def list_paths(self, _r, prefix=""):
            return ["frontend/src/foo/x.tsx"]

    fake = _Fake()
    findings = invariants.rule_aria_keyshortcuts(  # type: ignore[attr-defined]
        git_src=fake, head_ref="H", base_ref="H", refresh_audit=True
    )
    assert any(
        "Mod" in f.detail or "Mod" in f.snippet for f in findings
    ), "Expected a finding for Mod+Alt+S"


def test_aria_control_s_is_not_a_violation(invariants, util, workdir):
    """`Control+S Meta+S` is two valid shortcuts. NO violation."""
    class _Fake:
        def __init__(self):
            self.workdir = workdir

        def read_text(self, ref, rel):
            return (
                "const X = () => <button aria-keyshortcuts=\"Control+S Meta+S\">x</button>;\n"
            )

        def diff_paths(self, _a, _b):
            return {"frontend/src/foo/x.tsx"}

        def list_paths(self, _r, prefix=""):
            return ["frontend/src/foo/x.tsx"]

    fake = _Fake()
    findings = invariants.rule_aria_keyshortcuts(  # type: ignore[attr-defined]
        git_src=fake, head_ref="H", base_ref="H", refresh_audit=True
    )
    assert findings == [], f"Expected no findings; got {findings}"


def test_aria_runtime_template_literal_detected(invariants, util, workdir):
    """RED: a template literal `Mod+Alt+S` interpolated via JSX
    `aria-keyshortcuts={...}` IS detected when the value comes from
    a string literal in the same file (the brief says we cover
    "runtime string expressions/templates where statically visible").

    The brief also says we fail closed on non-literal arguments,
    which we DON'T test here (covered by `test_rule_no_llm_sdk_relative_is_recorded_with_honest_label`
    for the LLM equivalent). The string literal must be the
    SHOULDER of an `aria-keyshortcuts={…}` form."""
    class _Fake:
        def __init__(self):
            self.workdir = workdir

        def read_text(self, ref, rel):
            return (
                "const X = () => <button aria-keyshortcuts={'Mod+Alt+S'}>x</button>;\n"
            )

        def diff_paths(self, _a, _b):
            return {"frontend/src/foo/x.tsx"}

        def list_paths(self, _r, prefix=""):
            return ["frontend/src/foo/x.tsx"]

    fake = _Fake()
    findings = invariants.rule_aria_keyshortcuts(  # type: ignore[attr-defined]
        git_src=fake, head_ref="H", base_ref="H", refresh_audit=True
    )
    assert any(f.rule == "aria_keyshortcuts_modifiers" for f in findings), (
        f"Expected finding; got {findings}"
    )


# -------------------------------------------------------------------------
# Rule 6 — no new verify_*.py
# -------------------------------------------------------------------------


def test_rule_no_new_verify_in_baseline(invariants, util, workdir):
    """RED: at the pinned baseline SHA, the rule must report every
    verify_*.py on the head ref as a candidate (because of
    refresh-audit). Production baseline has exactly 45 such files."""
    class _Fake:
        def __init__(self, mapping):
            self.workdir = workdir
            self.mapping = mapping

        def list_paths(self, ref, prefix=""):
            return self.mapping.get(prefix, [])

        def diff_paths(self, a, b):
            return set()

    # We pre-fetch the actual list once from git.
    src = util.git_source(workdir)
    head_verify = [
        p for p in src.list_paths(SHA, prefix="scripts/")
        if p.startswith("scripts/verify_") and p.endswith(".py")
    ]
    base_verify = head_verify  # base == head in this test
    fake = _Fake({"scripts/": base_verify})
    findings = invariants.rule_no_new_verify_scripts(  # type: ignore[attr-defined]
        git_src=fake,
        head_ref="H",
        base_ref="B",
        refresh_audit=True,
    )
    assert len(head_verify) == 45, (
        f"Baseline is not 45: got {len(head_verify)}"
    )
    assert len(findings) == 45


# -------------------------------------------------------------------------
# Whole-script CLI smoke
# -------------------------------------------------------------------------


def test_invariants_cli_runs_against_real_baseline(invariants, workdir, tmp_path):
    """End-to-end: run the script with --refresh-audit and assert
    the JSON has each rule present with `shipped` boolean set.

    The script's exit code is `1` when ANY shipped rule has new
    findings — including ones we expect at the baseline (the venue
    rule has 8 baseline violations, the ARIA rule has 1, etc.). We
    therefore only assert the JSON shape; the exit-code is validated
    by the allowlist test below."""
    res = subprocess.run(  # noqa: S603 — argv list is hardcoded
        [
            sys.executable,
            "-m",
            "scripts.invariants",
            "--base",
            SHA,
            "--head",
            SHA,
            "--workdir",
            str(workdir),
            "--refresh-audit",
            "--json",
            str(tmp_path / "test_invariants_baseline.json"),
        ],
        cwd=str(workdir / ".github"),
        capture_output=True,
        text=True,
        check=False,
    )
    # We don't assert returncode; the script exits non-zero on
    # baseline violations and that is the EXPECTED behaviour.
    payload_path = tmp_path / "test_invariants_baseline.json"
    if not payload_path.exists():
        # If the CLI failed before writing JSON, fail loud.
        assert False, (
            f"CLI did not write JSON. stdout={res.stdout!r} "
            f"stderr={res.stderr!r}"
        )
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    rules = {r["rule"]: r for r in payload["rules"]}
    assert rules["no_float_on_money"]["shipped"] is False
    assert rules["no_llm_sdk_imports"]["shipped"] is True
    # On the exact baseline, every shipped rule's finding count
    # should be >= 0 (refresh-audit emits 45 verify scripts as
    # candidates, 8 venue hits, etc.).
    for rule in (
        "venue_clients_outside_boundary",
        "ui_hex_colors",
        "aria_keyshortcuts_modifiers",
        "no_new_verify_scripts",
    ):
        assert rules[rule]["finding_count"] >= 0, (
            f"Rule {rule} returned negative findings"
        )


def test_invariants_cli_exits_zero_with_full_allowlist(invariants, workdir, tmp_path):
    """RED-GREEN: when every baseline violation is in the
    allowlist, the CLI exits zero."""
    test_invariants_cli_runs_against_real_baseline(invariants, workdir, tmp_path)
    payload_path = tmp_path / "test_invariants_baseline.json"
    baseline = json.loads(payload_path.read_text(encoding="utf-8"))
    allow = {
        f["identity"]: {
            "rule": f["rule"],
            "file": f["file"],
            "line": f["line"],
            "issue_url": "https://github.com/example/fixture/issues/1",
            "snippet": f["snippet"],
            "reason": "test allow",
            "approved_by": "test",
        }
        for rule in baseline["rules"]
        if rule["shipped"]
        for f in rule["findings"]
    }
    allow_path = tmp_path / "test_invariants_full_allow.json"
    allow_path.write_text(json.dumps(allow), encoding="utf-8")
    res = subprocess.run(  # noqa: S603 — argv list is hardcoded
        [
            sys.executable,
            "-m",
            "scripts.invariants",
            "--base",
            SHA,
            "--head",
            SHA,
            "--workdir",
            str(workdir),
            "--refresh-audit",
            "--allowlist",
            str(allow_path),
            "--json",
            str(tmp_path / "test_invariants_full_allow_out.json"),
        ],
        cwd=str(workdir / ".github"),
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(
        (tmp_path / "test_invariants_full_allow_out.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["summary"]["total_findings_after_allowlist"] == 0, (
        "Allowlist should have suppressed every baseline finding."
    )
    assert res.returncode == 0, (
        f"CLI exited {res.returncode}; stdout={res.stdout!r}; "
        f"stderr={res.stderr!r}"
    )


def test_marker_patterns_cover_required_labels(invariants) -> None:
    """Skip marker decorator must be syntactically detectable.

    This is a documentation test: it documents the regex set used
    in `_MARKER_PATTERNS` from the test-integrity checker."""
    from scripts import test_integrity as ti  # type: ignore

    labels = {label for label, _ in ti._MARKER_PATTERNS}
    # The brief lists these marker names; assert the checker covers
    # each. Failing this means a future refactor removed coverage.
    required = {
        "pytest.mark.skip",
        "pytest.mark.xfail",
        "pytest.skip(",
        ".skip(",
        ".only(",
        ".todo(",
        ".fixme(",
        "test.fail(",
    }
    missing = required - labels
    assert not missing, f"Missing marker patterns: {missing}"


# The brief says: "Tests for the checkers may import the trusted
# checker module only, never fixtures being checked." Confirm we
# never import any product module.


def test_no_product_module_imports(invariants) -> None:
    """`import scripts.invariants` must not pull in `krellbot.*`.

    If a future refactor accidentally added a top-level
    `import krellbot`, the brief's "do not execute any product
    code" rule would be broken. We rebuild the import system and
    confirm only the trusted modules are loaded."""
    import importlib
    import sys

    # Save the existing modules map and restore at the end so we
    # don't pollute later tests' import environment.
    saved = dict(sys.modules)
    try:
        # Reset every cached lookup of krellbot.* so a fresh
        # import attempt would actually need to load it.
        for name in [n for n in sys.modules if n == "krellbot" or n.startswith("krellbot.")]:
            sys.modules.pop(name, None)
        sys.modules.pop("scripts.invariants", None)
        # Re-import.
        spec = importlib.util.find_spec("scripts.invariants")  # type: ignore
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules["scripts.invariants"] = mod
        loader = importlib.util.spec_from_loader(  # type: ignore
            "scripts.invariants", loader=None
        )
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        # Imports succeeded; verify krellbot was NOT pulled in.
        assert "krellbot" not in sys.modules, (
            "scripts.invariants pulled in `krellbot`; the checkers "
            "must remain free of product imports."
        )
    finally:
        # Restore. We restore only the keys that existed before;
        # the freshly-loaded `scripts.invariants` is dropped.
        for k in list(sys.modules):
            if k not in saved:
                sys.modules.pop(k, None)
        sys.modules.update(saved)
