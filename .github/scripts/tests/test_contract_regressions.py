"""Parent acceptance regressions: exercise real Git objects, never candidate imports."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from scripts import _util, invariants as inv, test_integrity as ti


class Repo:
    def __init__(self, path):
        self.path = path
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.put('seed', 'seed\n')
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.path, text=True).strip()

    def put(self, path, text):
        p = self.path / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def src(self):
        return _util.git_source(self.path)


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path)


def test_added_journey_fail_marker_is_rejected(repo):
    repo.put('frontend/journeys/a.spec.ts', 'test("J1.1", () => { test.fail(); expect(1).toBe(2); });\n')
    head = repo.commit()
    assert ti.rule_new_test_marker(git_src=repo.src(), base_ref=repo.base, head_ref=head)


@pytest.mark.parametrize('path', ['.github/workflows/new.yml', 'docs/journeys/new.md'])
def test_new_protected_file_requires_owner(repo, path):
    repo.put(path, 'new\n')
    assert ti.rule_protected_docs_modified(git_src=repo.src(), base_ref=repo.base, head_ref=repo.commit())


def test_test_to_test_rename_requires_owner(repo):
    repo.put('tests/test_a.py', 'def test_a():\n    assert True\n')
    base = repo.commit()
    repo.git('mv', 'tests/test_a.py', 'tests/test_b.py')
    assert ti.rule_test_file_deleted_or_renamed(git_src=repo.src(), base_ref=base, head_ref=repo.commit())


def test_replacing_marker_at_same_line_is_not_approved(repo):
    repo.put('frontend/e2e/a.spec.ts', 'test.skip("a", () => {});\n')
    base = repo.commit()
    repo.put('frontend/e2e/a.spec.ts', 'test.only("a", () => {});\n')
    assert ti.rule_new_test_marker(git_src=repo.src(), base_ref=base, head_ref=repo.commit())


def test_added_snapshot_requires_owner(repo):
    repo.put('frontend/e2e/a.spec.ts-snapshots/screen-chromium.png', 'not executed\n')
    assert ti.rule_snapshots_modified(git_src=repo.src(), base_ref=repo.base, head_ref=repo.commit())


def test_owner_approval_actually_waives_guard_cli(repo, tmp_path):
    repo.put('.github/workflows/a.yml', 'old\n')
    base = repo.commit()
    repo.put('.github/workflows/a.yml', 'new\n')
    head = repo.commit()
    events = tmp_path / 'events.json'
    events.write_text(json.dumps([{'id': 1, 'event': 'labeled', 'created_at': '2026-01-01T00:00:00Z',
                                  'label': {'name': 'owner-approved'}, 'actor': {'login': 'joe', 'id': 42}}]))
    owner = tmp_path / 'owner.json'
    owner.write_text(json.dumps({'owner': {'login': 'joe', 'id': 42}}))
    result = subprocess.run([sys.executable, '-m', 'scripts.test_integrity', '--workdir', str(repo.path),
                             '--base', base, '--head', head, '--repo', 'joe/repo', '--pr', '1',
                             '--events-file', str(events), '--repository-file', str(owner)],
                            cwd=repo.path,
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[2])},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_invalid_ref_cannot_silently_pass(repo):
    with pytest.raises((ValueError, RuntimeError, subprocess.CalledProcessError)):
        repo.src().list_paths('definitely-missing-ref', prefix='src/')


def test_indirect_relative_llm_import_is_found_without_execution(repo):
    sentinel = repo.path / 'EXECUTED'
    repo.put('src/krellbot/__init__.py', '')
    repo.put('src/krellbot/cli.py', 'from . import helper\n')
    repo.put('src/krellbot/helper.py', f'from pathlib import Path\nPath({str(sentinel)!r}).write_text("bad")\nfrom openai import OpenAI\n')
    head = repo.commit()
    paths = ['src/krellbot/__init__.py', 'src/krellbot/cli.py', 'src/krellbot/helper.py']
    hits = inv.rule_llm_sdk_imports(git_src=repo.src(), base_ref=repo.base, head_ref=head, python_paths=paths)
    assert any(f.rule == 'no_llm_sdk_imports' and f.file.endswith('helper.py') for f in hits)
    assert not sentinel.exists()


def test_relative_venue_import_outside_boundary_is_found(repo):
    repo.put('src/krellbot/cli.py', 'from .venues import kraken\n')
    repo.put('src/krellbot/venues/kraken.py', 'class KrakenVenue: pass\n')
    head = repo.commit()
    paths = ['src/krellbot/cli.py', 'src/krellbot/venues/kraken.py']
    hits, _ = inv.rule_venue_clients_outside_boundary(git_src=repo.src(), base_ref=repo.base, head_ref=head, python_paths=paths)
    assert any(f.file == 'src/krellbot/cli.py' for f in hits)


def test_only_tokens_css_is_exempt_not_all_styles():
    assert inv.interesting('frontend/src/styles/buttons.css')
    assert not inv.interesting('frontend/src/styles/tokens.css')
    assert inv.interesting('frontend/src/components/brand/Dynamic.tsx')


def test_non_var_function_hex_is_not_a_fallback():
    hits = inv._scan_hex_in_file('.x { color: color-mix(in srgb, red, #abcdef); }\n', 'frontend/src/a.css')
    assert hits and hits[0].line == 1


def test_multiline_comments_preserve_diagnostic_line():
    hits = inv._scan_hex_in_file('/* one\n two */\n.x { color: #abcdef; }\n', 'frontend/src/a.css')
    assert hits and hits[0].line == 3


def test_allowlist_cannot_cover_a_changed_violation_on_same_line():
    a = inv.Finding('ui_hex_colors', 'frontend/src/a.css', 1, '#abc', 'old')
    b = inv.Finding('ui_hex_colors', 'frontend/src/a.css', 1, '#def', 'new')
    assert a.identity != b.identity
    reports = [inv.RuleReport('ui_hex_colors', True, 'fixture', [b])]
    assert inv.filter_against_allowlist(reports, {a.identity: a.__dict__})[0].findings == [b]


@pytest.mark.parametrize('duplicate', [False, True])
def test_allowlist_line_shift_does_not_turn_existing_debt_into_new_debt(duplicate):
    old = inv.Finding('ui_hex_colors', 'frontend/src/a.css', 4, '.x { color: #abc; }', 'fixture')
    moved = inv.Finding('ui_hex_colors', old.file, 5, old.snippet, 'same source shifted by a comment')
    added = inv.Finding('ui_hex_colors', old.file, 6, old.snippet, 'new duplicate violation')
    reports = [inv.RuleReport('ui_hex_colors', True, 'fixture', [moved, added] if duplicate else [moved])]
    result = inv.filter_against_allowlist(reports, {old.identity: old.__dict__})[0].findings
    # A source-preserving line move is old debt; a second occurrence is new.
    assert result == ([added] if duplicate else [])


def test_aria_multiline_and_const_literal_modifiers():
    text = 'const shortcut = "Mod+Alt+S";\nconst el = <button\n aria-keyshortcuts={shortcut}>X</button>;\n'
    hits = inv._scan_aria_in_file(text, 'frontend/src/a.tsx')
    assert hits and hits[0].line == 3


@pytest.mark.parametrize('old,new', [
    ('tests/test_a.py', 'tests/test_b.py'),
    ('tests/test_a.py', 'src/not_a_test.py'),
    ('frontend/src/a.test.ts', 'frontend/src/b.test.ts'),
    ('frontend/e2e/a.spec.ts', 'frontend/e2e/b.spec.ts'),
    ('frontend/journeys/a.spec.ts', 'frontend/journeys/b.spec.ts'),
])
@pytest.mark.parametrize('rewrite_after_rename', [False, True])
def test_baseline_test_rename_across_multiple_commits_is_rejected_cli(repo, old, new, rewrite_after_rename):
    """Protect a test present on base, regardless of intermediate PR commits."""
    repo.put(old, 'def test_original():\n    assert True\n')
    base = repo.commit()
    repo.put('unrelated.txt', 'first PR commit\n')
    repo.commit()
    (repo.path / new).parent.mkdir(parents=True, exist_ok=True)
    repo.git('mv', old, new)
    repo.commit()
    if rewrite_after_rename:
        repo.put(new, 'def test_rewritten_completely():\n    assert 123456 == 123456\n')
    repo.put('unrelated.txt', 'third PR commit\n')
    head = repo.commit()
    hits = ti.rule_test_file_deleted_or_renamed(git_src=repo.src(), base_ref=base, head_ref=head)
    assert any(f.file == old for f in hits)
    events, owner = repo.path / 'events.json', repo.path / 'owner.json'
    events.write_text('[]')
    owner.write_text(json.dumps({'owner': {'login': 'joe', 'id': 42}}))
    result = subprocess.run([
        sys.executable, '-m', 'scripts.test_integrity', '--workdir', str(repo.path),
        '--base', base, '--head', head, '--repo', 'joe/repo', '--pr', '1',
        '--events-file', str(events), '--repository-file', str(owner),
    ], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert old + ':1: test_file_deleted_or_renamed:' in result.stdout
