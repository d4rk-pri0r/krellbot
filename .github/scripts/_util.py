"""Trusted, stdlib-only Git data readers. Never load candidate Python modules."""
from __future__ import annotations
import fnmatch
import json
from pathlib import Path
import re
import subprocess
from typing import Any

_REF_OK = re.compile(r'[A-Za-z0-9_][A-Za-z0-9._/^~+\-]{0,199}\Z')


def git(workdir: Path, *args: str) -> bytes:
    p = subprocess.run(['git', '--no-pager', *args], cwd=workdir, capture_output=True, check=False)
    if p.returncode:
        raise RuntimeError(f'git {args[0]} failed: {p.stderr.decode(errors="replace").strip()}')
    return p.stdout


def resolve_ref(workdir: Path, ref: str) -> str:
    if not _REF_OK.fullmatch(ref):
        raise ValueError(f'unsafe git ref: {ref!r}')
    result = git(workdir, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40,64}', result):
        raise ValueError('git did not resolve a commit object')
    return result


def valid_path(path: str) -> str:
    if not path or path.startswith('/') or '\0' in path or any(x in ('', '.', '..') for x in path.split('/')):
        raise ValueError(f'unsafe repository path: {path!r}')
    return path


class GitSource:
    def __init__(self, workdir: Path):
        self.workdir = Path(workdir).resolve()
        self._refs: dict[str, str] = {}
        self._trees: dict[str, dict[str, tuple[str, str]]] = {}
        self._contents: dict[tuple[str, str], bytes] = {}

    def resolve(self, ref: str) -> str:
        if ref not in self._refs:
            self._refs[ref] = resolve_ref(self.workdir, ref)
        return self._refs[ref]

    def tree(self, ref: str) -> dict[str, tuple[str, str]]:
        sha = self.resolve(ref)
        if sha not in self._trees:
            tree = {}
            for entry in git(self.workdir, 'ls-tree', '-rz', sha).split(b'\0'):
                if not entry:
                    continue
                meta, name = entry.split(b'\t', 1)
                mode, kind, oid = meta.decode().split()
                if kind == 'blob':
                    tree[name.decode()] = (mode, oid)
            self._trees[sha] = tree
        return self._trees[sha]

    def read_bytes(self, ref: str, rel_path: str) -> bytes | None:
        valid_path(rel_path)
        sha = self.resolve(ref)
        tree = self.tree(sha)
        if rel_path not in tree:
            return None
        mode, oid = tree[rel_path]
        if mode not in ('100644', '100755'):
            raise ValueError(f'Non-regular source file is not readable as code: {rel_path}')
        key = (sha, rel_path)
        if key not in self._contents:
            self._contents[key] = git(self.workdir, 'cat-file', 'blob', oid)
        return self._contents[key]

    def read_text(self, ref: str, rel_path: str) -> str | None:
        data = self.read_bytes(ref, rel_path)
        return None if data is None else data.decode('utf-8', errors='replace')

    def list_paths(self, ref: str, prefix: str = '') -> list[str]:
        prefix = prefix.rstrip('/')
        if prefix:
            valid_path(prefix)
        return [p for p in self.tree(ref) if not prefix or p == prefix or p.startswith(prefix + '/')]

    def diff_paths(self, base: str, head: str) -> list[str]:
        a, b = self.resolve(base), self.resolve(head)
        return [p.decode() for p in git(self.workdir, 'diff', '--no-ext-diff', '--name-only', '-z', a + '...' + b, '--').split(b'\0') if p]


def git_source(workdir):
    return GitSource(workdir)


def run_git_show_text(workdir, ref, rel_path):
    return GitSource(workdir).read_text(ref, rel_path)


def run_git_show_bytes(workdir, ref, rel_path):
    return GitSource(workdir).read_bytes(ref, rel_path)


def run_git_ls_tree(workdir, ref, prefix=''):
    return GitSource(workdir).list_paths(ref, prefix)


def run_git_diff_name_only(workdir, base, head):
    return GitSource(workdir).diff_paths(base, head)


def fnmatch_globs(path, patterns):
    def match(parts, pattern):
        if not pattern:
            return not parts
        if pattern[0] == '**':
            return match(parts, pattern[1:]) or bool(parts and match(parts[1:], pattern))
        return bool(parts and fnmatch.fnmatchcase(parts[0], pattern[0]) and match(parts[1:], pattern[1:]))
    return any(match(path.split('/'), pat.split('/')) for pat in patterns)


def write_json_if_requested(path, payload):
    if path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')


def parse_allowlist(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('allowlist must be an object keyed by exact finding identity')
    for key, entry in data.items():
        if not isinstance(entry, dict) or not re.fullmatch(r'https://github\.com/[^/\s]+/[^/\s]+/issues/[1-9][0-9]*', entry.get('issue_url', '')):
            raise ValueError(f'allowlist entry {key!r} needs a specific issue URL')
        if not all(k in entry for k in ('rule', 'file', 'line', 'snippet')):
            raise ValueError(f'allowlist entry {key!r} needs rule/file/line/snippet evidence')
    return data


def load_trusted_allowlist(workdir, base_ref, explicit_path=None, rel_path_in_repo='.github/scripts/invariants-allowlist.json'):
    if explicit_path is not None:
        return parse_allowlist(Path(explicit_path).read_text()), f'explicit-trusted:{explicit_path}'
    source = GitSource(workdir)
    raw = source.read_text(base_ref, rel_path_in_repo)
    if raw is None:
        return {}, f'missing:{base_ref}:{rel_path_in_repo}'
    return parse_allowlist(raw), f'git:{source.resolve(base_ref)}:{rel_path_in_repo}'
