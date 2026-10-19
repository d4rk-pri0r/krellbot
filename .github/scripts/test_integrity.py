"""Static PR test-integrity counter; exceptions require an owner-applied label.

Run the trusted base copy as ``python -m scripts.test_integrity``. Candidate
files are read from Git objects as data; candidate code is never imported.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import difflib
import json
from pathlib import Path
import re
import subprocess
import sys
from . import _util

TEST_PATH_PATTERNS = ('tests/**', 'frontend/src/**/*.test.ts', 'frontend/src/**/*.test.tsx', 'frontend/e2e/**', 'frontend/journeys/**')
_MARKER_PATTERNS = tuple((name, re.compile(pattern)) for name, pattern in (
    ('pytest.mark.skip', r'\bpytest\s*\.\s*mark\s*\.\s*skip(?:if)?\b'),
    ('pytest.mark.xfail', r'\bpytest\s*\.\s*mark\s*\.\s*xfail\b'),
    ('pytest.skip(', r'\bpytest\s*\.\s*skip\s*\('),
    ('.skip(', r'\.\s*skip\s*\('), ('.only(', r'\.\s*only\s*\('),
    ('.todo(', r'\.\s*todo\s*\('), ('.fixme(', r'\.\s*fixme\s*\('),
    ('test.fail(', r'(?<![\w$])test\s*\.\s*fail\s*\('), ('xtest(', r'(?<![\w$])xtest\s*\('),
))
REMEDY = 'Restore the protected test contract, or ask the repository owner to apply the owner-approved label. The guard verifies the label actor through issue events.'


@dataclass
class Finding:
    rule: str
    file: str
    line: int
    snippet: str
    detail: str
    remedy: str = REMEDY


@dataclass
class RuleReport:
    rule: str
    findings: list[Finding]
    shipped: bool = True

    def to_dict(self):
        return {'rule': self.rule, 'shipped': self.shipped, 'findings': [asdict(f) for f in self.findings], 'finding_count': len(self.findings)}


def is_test_path(path):
    return _util.fnmatch_globs(path, TEST_PATH_PATTERNS)


def is_protected_doc(path):
    return path.startswith(('docs/journeys/', '.github/'))


def is_snapshot_path(path):
    return any(p == '__snapshots__' or p.endswith('-snapshots') for p in path.split('/')) or '.snap' in Path(path).suffixes


def classify_diff(git_src, base_ref, head_ref):
    base = git_src.resolve(base_ref)
    head = git_src.resolve(head_ref)
    chunks = iter(_util.git(git_src.workdir, 'diff', '--no-ext-diff', '--name-status', '-z', '-M', base + '...' + head, '--').split(b'\0'))
    added, renamed, deleted, modified = [], [], [], []
    for raw in chunks:
        if not raw:
            continue
        code = raw.decode()
        first = next(chunks).decode()
        if code.startswith('R'):
            renamed.append((first, next(chunks).decode()))
        elif code.startswith('C'):
            added.append(next(chunks).decode())
        elif code == 'A':
            added.append(first)
        elif code == 'D':
            deleted.append(first)
        elif code in ('M', 'T'):
            modified.append(first)
        else:
            raise ValueError(f'Unrecognized Git change status {code!r}; refusing to pass')
    return added, renamed, deleted, modified


def count_test_markers(text):
    return {'def_test_': len(re.findall(r'\bdef\s+test_\w*\b', text)),
            'it_or_test_call': len(re.findall(r'(?<![\w$])(?:it|test)\s*\(', text)),
            'assert': len(re.findall(r'\bassert\b', text)),
            'expect(': len(re.findall(r'(?<![\w$])expect\s*\(', text))}


def find_markers(text):
    found = []
    lines = text.splitlines()
    for label, pattern in _MARKER_PATTERNS:
        for match in pattern.finditer(text):
            line = text.count('\n', 0, match.start()) + 1
            found.append((line, lines[line - 1], label))
    return sorted(set(found))


def changed_lines(before, after):
    old, new = before.splitlines(), after.splitlines()
    indexes = set()
    for op, _a, _b, c, d in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if op != 'equal':
            indexes.update(range(c + 1, d + 1))
    return indexes


def rule_test_file_deleted_or_renamed(*, git_src, base_ref, head_ref):
    _, renamed, deleted, _ = classify_diff(git_src, base_ref, head_ref)
    changes = [(p, '(deleted)') for p in deleted] + [(a, f'(renamed to {b})') for a, b in renamed]
    return [Finding('test_file_deleted_or_renamed', p, 1, desc, 'A test file was deleted or renamed, including renames within the test tree.') for p, desc in changes if is_test_path(p)]


def rule_test_counts_decreased(*, git_src, base_ref, head_ref):
    _, renamed, deleted, modified = classify_diff(git_src, base_ref, head_ref)
    results = []
    for old_path, new_path in [(p, p) for p in deleted + modified] + renamed:
        if not is_test_path(old_path):
            continue
        before = git_src.read_text(base_ref, old_path) or ''
        after = git_src.read_text(head_ref, new_path) or ''
        a, b = count_test_markers(before), count_test_markers(after)
        line = min(changed_lines(before, after), default=1)
        for counter in a:
            if b[counter] < a[counter]:
                results.append(Finding('test_counts_decreased', new_path, line, f'{counter}: {a[counter]} -> {b[counter]}', 'Whole-word test/assertion count decreased in this file.'))
    return results


def rule_new_test_marker(*, git_src, base_ref, head_ref):
    added, renamed, _, modified = classify_diff(git_src, base_ref, head_ref)
    results = []
    for old_path, new_path in [(p, p) for p in added + modified] + renamed:
        if not is_test_path(new_path):
            continue
        before = git_src.read_text(base_ref, old_path) or ''
        after = git_src.read_text(head_ref, new_path) or ''
        added_lines = changed_lines(before, after)
        old_counts = Counter(label for _, _, label in find_markers(before))
        for line, snippet, label in find_markers(after):
            if line in added_lines or old_counts[label] <= 0:
                results.append(Finding('new_test_marker', new_path, line, snippet, f'Added {label} marker. Expected-failure markers also need explicit owner approval.'))
            old_counts[label] -= 1
    return results


def all_changed_paths(git_src, base_ref, head_ref):
    added, renamed, deleted, modified = classify_diff(git_src, base_ref, head_ref)
    return sorted(set(added + deleted + modified + [p for pair in renamed for p in pair]))


def rule_protected_docs_modified(*, git_src, base_ref, head_ref):
    return [Finding('protected_docs_modified', p, 1, '(protected path changed)', 'Any addition, removal, modification or rename under docs/journeys/ or .github/ needs approval.')
            for p in all_changed_paths(git_src, base_ref, head_ref) if is_protected_doc(p)]


def rule_snapshots_modified(*, git_src, base_ref, head_ref):
    return [Finding('snapshots_modified', p, 1, '(snapshot changed)', 'Snapshot additions, removals, modifications and renames need approval.')
            for p in all_changed_paths(git_src, base_ref, head_ref) if is_snapshot_path(p)]


@dataclass
class ApprovalStatus:
    approved: bool
    reason: str
    last_actor_login: str | None = None
    last_event_at: str | None = None

    def to_dict(self):
        return asdict(self)


def evaluate_owner_approval(*, repo, pr_number, owner_login, events, owner_id=None):
    relevant = [e for e in events if isinstance(e.get('label'), dict) and e['label'].get('name') == 'owner-approved' and e.get('event') in ('labeled', 'unlabeled')]
    if not relevant:
        return ApprovalStatus(False, 'No owner-approved label event exists.')
    if any(not isinstance(e.get('actor'), dict) or not e['actor'].get('login') or not e.get('created_at') for e in relevant):
        return ApprovalStatus(False, 'Malformed owner-approved label event; failing closed.')
    # GitHub events are chronological; ties retain their API order, with event IDs as a tie-breaker.
    last = sorted(enumerate(relevant), key=lambda pair: (pair[1]['created_at'], pair[1].get('id', pair[0])))[-1][1]
    actor = last['actor']['login']
    if last['event'] != 'labeled':
        return ApprovalStatus(False, 'owner-approved was removed.', actor, last['created_at'])
    if actor.casefold() != owner_login.casefold() or (owner_id is not None and last['actor'].get('id') != owner_id):
        return ApprovalStatus(False, f'owner-approved foreign apply by {actor!r}; repository owner is {owner_login!r}.', actor, last['created_at'])
    return ApprovalStatus(True, 'owner-approved applied by the repository owner', actor, last['created_at'])


def gh_json(args, workdir):
    p = subprocess.run(['gh', 'api', *args], cwd=workdir, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError('GitHub approval read failed; refusing approval: ' + p.stderr.strip())
    return json.loads(p.stdout)


def fetch_label_events(*, issue_number, repo, workdir, events_file=None):
    if events_file is not None:
        result = json.loads(Path(events_file).read_text())
    else:
        pages = gh_json(['--paginate', '--slurp', f'repos/{repo}/issues/{issue_number}/events?per_page=100'], workdir)
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise ValueError('Invalid paginated events response')
        result = [event for page in pages for event in page]
    if not isinstance(result, list) or any(not isinstance(e, dict) for e in result):
        raise ValueError('Invalid issue events; failing closed')
    return result


def evaluate_test_rules(*, git_src, base_ref, head_ref, approval=None):
    functions = (rule_test_file_deleted_or_renamed, rule_test_counts_decreased, rule_new_test_marker, rule_protected_docs_modified, rule_snapshots_modified)
    return [RuleReport(fn.__name__.removeprefix('rule_'), fn(git_src=git_src, base_ref=base_ref, head_ref=head_ref)) for fn in functions]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for option in ('base', 'head', 'repo', 'pr'):
        p.add_argument('--' + option, required=True)
    p.add_argument('--workdir', default='.')
    p.add_argument('--json')
    p.add_argument('--events-file', help='Offline checker tests only; NEVER pass from CI')
    p.add_argument('--repository-file', help='Offline checker tests only; NEVER pass from CI')
    args = p.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo) or not re.fullmatch(r'[1-9][0-9]*', args.pr):
        p.error('Valid owner/repository and positive PR number required')
    if bool(args.events_file) != bool(args.repository_file):
        p.error('Both offline fixture overrides are required together')
    workdir = Path(args.workdir).resolve()
    try:
        source = _util.GitSource(workdir)
        base, head = source.resolve(args.base), source.resolve(args.head)
        owner_data = json.loads(Path(args.repository_file).read_text()) if args.repository_file else gh_json([f'repos/{args.repo}'], workdir)
        owner = owner_data['owner']
        if not owner.get('login') or (not args.repository_file and not isinstance(owner.get('id'), int)):
            raise ValueError('Missing authoritative repository owner identity')
        events = fetch_label_events(issue_number=args.pr, repo=args.repo, workdir=workdir, events_file=args.events_file)
        approval = evaluate_owner_approval(repo=args.repo, pr_number=args.pr, owner_login=owner['login'], owner_id=owner.get('id'), events=events)
        if not args.events_file:
            labels = gh_json([f'repos/{args.repo}/issues/{args.pr}/labels?per_page=100', '--paginate', '--slurp'], workdir)
            if not any(l.get('name') == 'owner-approved' for page in labels for l in page):
                approval = ApprovalStatus(False, 'Current owner-approved label is absent.')
        reports = evaluate_test_rules(git_src=source, base_ref=base, head_ref=head)
        findings = [f for r in reports for f in r.findings]
        payload = {'base': base, 'head': head, 'repo': args.repo, 'pr': int(args.pr), 'approval': approval.to_dict(),
                   'rules': [r.to_dict() for r in reports],
                   'summary': {'total_findings': len(findings), 'owner_approved': approval.approved, 'waived': bool(findings and approval.approved)}}
        _util.write_json_if_requested(args.json, payload)
        for finding in findings:
            print(f'{finding.file}:{finding.line}: {finding.rule}: {finding.detail} {finding.snippet} {finding.remedy}')
        print(json.dumps({'approval': approval.to_dict(), 'summary': payload['summary']}))
        return int(bool(findings) and not approval.approved)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(f'test-integrity:1: approval-or-input-error: {exc}. {REMEDY}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
