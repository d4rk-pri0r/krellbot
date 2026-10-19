"""Negative controls for trusted-base workflow staging (local Git fixtures only)."""
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / '.github/workflows/public-oracle-policies.yml'


def git(cwd, *args):
    return subprocess.check_output(['git', *args], cwd=cwd, text=True).strip()


def put(root, name, text):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def commit(root):
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'fixture')
    return git(root, 'rev-parse', 'HEAD')


def stage_block():
    text = WORKFLOW.read_text()
    match = re.search(r"          python3 - <<'PY'\n(.*?)\n          PY", text, re.S)
    assert match is not None, 'trusted staging block is missing'
    block = match.group(1)
    return '\n'.join(x[10:] if x.startswith(' ' * 10) else x for x in block.splitlines())


def fixture(tmp_path, base_has_scripts=True, merged=False):
    remote = tmp_path / 'remote'
    remote.mkdir()
    git(remote, 'init', '-q', '-b', 'main')
    git(remote, 'config', 'user.name', 'Fixture')
    git(remote, 'config', 'user.email', 'fixture@example.invalid')
    put(remote, 'seed', 'data\n')
    if base_has_scripts:
        for name, text in {'__init__.py': '', '_util.py': '', 'invariants.py': 'IDENTITY = "trusted base"\n', 'invariants-allowlist.json': '{}'}.items():
            put(remote, '.github/scripts/' + name, text)
    base = commit(remote)
    git(remote, 'checkout', '-qb', 'topic')
    for name, text in {'__init__.py': '', '_util.py': '', 'invariants.py': 'raise RuntimeError("candidate must not execute")\n', 'invariants-allowlist.json': '{}'}.items():
        put(remote, '.github/scripts/' + name, text)
    head = commit(remote)
    git(remote, 'update-ref', 'refs/pull/1/head', head)
    git(remote, 'checkout', '-q', 'main')
    merge = None
    if merged:
        git(remote, 'merge', '--no-ff', '-qm', 'fixture merge', 'topic')
        merge = git(remote, 'rev-parse', 'HEAD')
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'clone', '-q', '--branch', 'main', str(remote), str(checkout)], check=True)
    pr = {'number': 1, 'head': {'sha': head}, 'base': {'sha': merge or base, 'ref': 'main', 'repo': {'full_name': 'd4rk-pri0r/krellbot'}}, 'merged': merged, 'merge_commit_sha': merge}
    event = tmp_path / 'event.json'
    event.write_text(json.dumps({'pull_request': pr}))
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    fake_gh = bin_dir / 'gh'
    fake_gh.write_text(f'#!{sys.executable}\nimport json\nprint({json.dumps(json.dumps(pr))})\n')
    fake_gh.chmod(0o755)
    env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
           'GITHUB_REPOSITORY': 'd4rk-pri0r/krellbot', 'GITHUB_EVENT_PATH': str(event),
           'GITHUB_SHA': head, 'GITHUB_OUTPUT': str(tmp_path / 'output'), 'RUNNER_TEMP': str(tmp_path / 'runner'),
           'POLICY_MODULE': 'invariants', 'AUDIT_PR': '1' if merged else ''}
    return checkout, env, base, head


def run_stage(checkout, env):
    return subprocess.run([sys.executable, '-I', '-c', stage_block()], cwd=checkout, env=env, capture_output=True, text=True)


def test_candidate_cannot_replace_trusted_base_script(tmp_path):
    checkout, env, _base, _head = fixture(tmp_path)
    result = run_stage(checkout, env)
    assert result.returncode == 0, result.stdout + result.stderr
    copied = Path(env['RUNNER_TEMP']) / 'policy-invariants/scripts/invariants.py'
    assert copied.read_text() == 'IDENTITY = "trusted base"\n'
    assert 'TRUSTED BASE' in result.stdout and 'BOOTSTRAP' not in result.stdout
    output = Path(env['GITHUB_OUTPUT']).read_text()
    assert '\\n' not in output
    assert {x.split('=', 1)[0] for x in output.splitlines()} == {'trusted', 'base', 'head', 'pr', 'source'}


def test_missing_base_script_uses_explicit_logged_bootstrap(tmp_path):
    checkout, env, _base, _head = fixture(tmp_path, base_has_scripts=False)
    result = run_stage(checkout, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'BOOTSTRAP' in result.stdout
    copied = Path(env['RUNNER_TEMP']) / 'policy-invariants/scripts/invariants.py'
    assert 'candidate must not execute' in copied.read_text()  # copied as bytes, never imported by staging


def test_merged_pr_audit_uses_premerge_base_not_empty_diff(tmp_path):
    checkout, env, base, head = fixture(tmp_path, merged=True)
    result = run_stage(checkout, env)
    assert result.returncode == 0, result.stdout + result.stderr
    output = dict(x.split('=', 1) for x in Path(env['GITHUB_OUTPUT']).read_text().splitlines())
    assert output['base'] == base and output['head'] == head
    assert git(checkout, 'diff', '--name-only', base + '...' + head)


def test_all_embedded_python_and_action_pins_are_valid():
    for path in (WORKFLOW, ROOT / '.github/workflows/ci.yml'):
        text = path.read_text()
        for block in re.findall(r"          python3 - <<'PY'\n(.*?)\n          PY", text, re.S):
            ast.parse('\n'.join(x[10:] if x.startswith(' ' * 10) else x for x in block.splitlines()))
        uses = re.findall(r'uses:\s+(\S+)', text)
        assert uses and all(re.fullmatch(r'[\w.-]+/[\w.-]+@[0-9a-f]{40}', u) for u in uses)
    text = WORKFLOW.read_text()
    assert 'pull_request_target:' in text and 'labeled, unlabeled' in text
    assert '--events-file' not in text and '--repository-file' not in text
    assert 'python3 -I' in text
    assert 'ref: main' in text and 'allow-unsafe-pr-checkout' not in text
